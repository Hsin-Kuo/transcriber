"""WorkerDispatch 單元測試（M1.1）。

驗證 seam 的價值——用 mock 注入 sqs_client / handoff_uploader 完整覆蓋
dispatch 邏輯，不需要 boto3 也不需要 SQS 帳號。
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.worker_job import TranscriptionWorkerJob  # noqa: E402
from src.services.worker_dispatch import WorkerDispatch  # noqa: E402


def _make_job(**overrides):
    """Helper：給測試用的 default Job + 可覆寫欄位"""
    base = dict(
        task_id="task-1",
        language="zh",
        use_chunking=True,
        use_punctuation=True,
        punctuation_provider="gemini",
        use_diarization=False,
        max_speakers=None,
    )
    base.update(overrides)
    return TranscriptionWorkerJob(**base)


def _make_dispatch(
    *,
    sqs_client=None,
    sqs_queue_url="https://sqs.example.com/queue",
    worker_secret="test-secret-32-chars-minimum-len",
    handoff_uploader=None,
):
    return WorkerDispatch(
        sqs_client=sqs_client or MagicMock(),
        sqs_queue_url=sqs_queue_url,
        worker_secret=worker_secret,
        handoff_uploader=handoff_uploader or MagicMock(),
    )


@pytest.fixture
def fake_audio(tmp_path: Path) -> Path:
    """產生 temp_dir 與 audio file 模擬上傳路徑。"""
    temp_dir = tmp_path / "task_workdir"
    temp_dir.mkdir()
    audio = temp_dir / "input.mp3"
    audio.write_bytes(b"ID3\x04\x00" + b"\x00" * 100)
    return audio


class TestSignSqsPayload:
    def test_signed_when_secret_set(self):
        d = _make_dispatch(worker_secret="my-secret")
        signed = d._sign({"task_id": "abc"})
        assert "_signature" in signed
        expected = hmac.new(
            b"my-secret",
            json.dumps({"task_id": "abc"}, sort_keys=True, separators=(",", ":")).encode(),
            hashlib.sha256,
        ).hexdigest()
        assert signed["_signature"] == expected
        # original keys preserved
        assert signed["task_id"] == "abc"

    def test_unsigned_when_secret_empty(self):
        d = _make_dispatch(worker_secret="")
        payload = {"task_id": "abc"}
        assert d._sign(payload) == payload  # 原 dict 不變

    def test_sign_is_deterministic(self):
        d = _make_dispatch(worker_secret="secret")
        s1 = d._sign({"a": 1, "b": 2})
        s2 = d._sign({"b": 2, "a": 1})  # 不同 dict 順序
        assert s1["_signature"] == s2["_signature"]  # sort_keys=True 保證一致


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_uploads_and_sends_sqs(self, fake_audio: Path):
        sqs = MagicMock()
        uploader = MagicMock()
        d = _make_dispatch(sqs_client=sqs, handoff_uploader=uploader)

        await d._dispatch(
            job=_make_job(task_id="task-1"),
            audio_local_path=fake_audio,
            temp_dir=fake_audio.parent,
            user_tier="pro",
        )

        # Handoff uploader 被呼叫且帶正確參數 (task_id, local_path, ext)
        # ext 從 audio_local_path.suffix 推導，與 user_tier 無關
        uploader.assert_called_once_with("task-1", fake_audio, "mp3")

        # SQS send_message 被呼叫
        sqs.send_message.assert_called_once()
        call_kwargs = sqs.send_message.call_args.kwargs
        assert call_kwargs["QueueUrl"] == "https://sqs.example.com/queue"
        body = json.loads(call_kwargs["MessageBody"])
        assert body["task_id"] == "task-1"
        assert body["language"] == "zh"
        assert body["use_chunking"] is True
        assert "_signature" in body

        # temp_dir 被清理
        assert not fake_audio.parent.exists()

    @pytest.mark.asyncio
    async def test_skips_sqs_when_url_empty(self, fake_audio: Path):
        sqs = MagicMock()
        uploader = MagicMock()
        d = _make_dispatch(sqs_client=sqs, sqs_queue_url="", handoff_uploader=uploader)

        await d._dispatch(
            job=_make_job(task_id="task-2"),
            audio_local_path=fake_audio,
            temp_dir=fake_audio.parent,
            user_tier="free",
        )

        uploader.assert_called_once()
        sqs.send_message.assert_not_called()  # 沒 URL 就不送
        assert not fake_audio.parent.exists()


class TestFailurePath:
    @pytest.mark.asyncio
    async def test_s3_failure_raises_after_cleanup(self, fake_audio: Path, monkeypatch):
        sqs = MagicMock()
        uploader = MagicMock(side_effect=RuntimeError("S3 down"))
        d = _make_dispatch(sqs_client=sqs, handoff_uploader=uploader)

        # 攔截 get_sync_db 避免真的打 mongo
        update_mock = MagicMock()
        fake_db = MagicMock()
        fake_db.tasks.update_one = update_mock
        monkeypatch.setattr(
            "src.services.worker_dispatch.get_sync_db",
            lambda: fake_db,
        )

        with pytest.raises(RuntimeError, match="S3 down"):
            await d._dispatch(
                job=_make_job(task_id="task-fail"),
                audio_local_path=fake_audio,
                temp_dir=fake_audio.parent,
                user_tier="free",
            )

        # SQS 沒被呼叫（S3 先掛）
        sqs.send_message.assert_not_called()
        # Task 被標 failed
        update_mock.assert_called_once()
        update_args = update_mock.call_args.args
        assert update_args[0] == {"_id": "task-fail"}
        update_op = update_args[1]["$set"]
        assert update_op["status"] == "failed"
        assert update_op["error"]["code"] == "UPLOAD_FAILED"
        assert "S3 down" in update_op["error"]["message"]
        # temp_dir 仍被清掉
        assert not fake_audio.parent.exists()

    @pytest.mark.asyncio
    async def test_sqs_failure_marks_task_failed(self, fake_audio: Path, monkeypatch):
        sqs = MagicMock()
        sqs.send_message.side_effect = RuntimeError("SQS unreachable")
        uploader = MagicMock()
        d = _make_dispatch(sqs_client=sqs, handoff_uploader=uploader)

        fake_db = MagicMock()
        monkeypatch.setattr(
            "src.services.worker_dispatch.get_sync_db",
            lambda: fake_db,
        )

        with pytest.raises(RuntimeError, match="SQS unreachable"):
            await d._dispatch(
                job=_make_job(task_id="task-sqs"),
                audio_local_path=fake_audio,
                temp_dir=fake_audio.parent,
                user_tier="free",
            )

        uploader.assert_called_once()  # S3 上傳已成功
        fake_db.tasks.update_one.assert_called_once()  # 但 task 仍被標 failed


class TestSingleton:
    def test_get_before_init_raises(self):
        # reset module global
        import src.services.worker_dispatch as mod
        mod._instance = None
        from src.services.worker_dispatch import get_worker_dispatch
        with pytest.raises(RuntimeError, match="尚未初始化"):
            get_worker_dispatch()

    def test_init_then_get_returns_same(self):
        import src.services.worker_dispatch as mod
        mod._instance = None
        from src.services.worker_dispatch import (
            init_worker_dispatch,
            get_worker_dispatch,
        )
        d = _make_dispatch()
        init_worker_dispatch(d)
        assert get_worker_dispatch() is d
