"""TranscriptionJob schema 測試（M1.5）。

驗證 typed contract：required 欄位、defaults、forward compat（extra ignore）、
serialize round-trip。
"""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.worker_job import TranscriptionJob  # noqa: E402


class TestRequiredFields:
    def test_task_id_is_required(self):
        with pytest.raises(ValidationError) as exc:
            TranscriptionJob()
        assert "task_id" in str(exc.value)

    def test_minimal_valid_construction(self):
        job = TranscriptionJob(task_id="abc-123")
        assert job.task_id == "abc-123"
        # Defaults
        assert job.language is None
        assert job.use_chunking is True
        assert job.use_punctuation is True
        assert job.punctuation_provider == "gemini"
        assert job.use_diarization is False
        assert job.max_speakers is None


class TestForwardCompat:
    """extra='ignore' 讓舊版 Worker 不會被新 Server 多送的欄位炸到。"""

    def test_unknown_field_ignored(self):
        # Worker 收到未來版 server 多送的欄位，不該炸
        job = TranscriptionJob.model_validate({
            "task_id": "t1",
            "language": "zh",
            "future_field_we_dont_know_yet": "value",
            "another_one": {"nested": True},
        })
        assert job.task_id == "t1"
        assert job.language == "zh"
        # 確認未知欄位不會被丟進 model
        assert not hasattr(job, "future_field_we_dont_know_yet")


class TestTypeValidation:
    def test_task_id_must_be_str(self):
        with pytest.raises(ValidationError):
            TranscriptionJob(task_id=12345)  # type: ignore[arg-type]

    def test_max_speakers_optional_int(self):
        # int OK
        TranscriptionJob(task_id="t", max_speakers=5)
        # None OK
        TranscriptionJob(task_id="t", max_speakers=None)
        # 字串會被 coerce（Pydantic v2 默認）or 拒絕？保守驗實際行為
        with pytest.raises(ValidationError):
            TranscriptionJob(task_id="t", max_speakers="not-a-number")  # type: ignore[arg-type]


class TestRoundTrip:
    def test_dump_then_validate_preserves_fields(self):
        original = TranscriptionJob(
            task_id="round-trip-1",
            language="en",
            use_chunking=False,
            use_punctuation=True,
            punctuation_provider="openai",
            use_diarization=True,
            max_speakers=3,
        )
        # 模擬 server → JSON → SQS → worker → validate
        as_dict = original.model_dump()
        rehydrated = TranscriptionJob.model_validate(as_dict)
        assert rehydrated == original

    def test_no_signature_field_in_dump(self):
        """確認 signature 不被 model 知道（envelope 在外）。"""
        job = TranscriptionJob(task_id="t")
        dumped = job.model_dump()
        assert "_signature" not in dumped
        assert "signature" not in dumped


class TestNormalization:
    """max_speakers == 1 時 diarization 無意義，model 層強制關閉（兩 adapter 一致）。"""

    def test_single_speaker_disables_diarization(self):
        job = TranscriptionJob(task_id="t", use_diarization=True, max_speakers=1)
        assert job.use_diarization is False

    def test_multi_speaker_keeps_diarization(self):
        job = TranscriptionJob(task_id="t", use_diarization=True, max_speakers=3)
        assert job.use_diarization is True

    def test_ui_language_defaults_none(self):
        assert TranscriptionJob(task_id="t").ui_language is None
