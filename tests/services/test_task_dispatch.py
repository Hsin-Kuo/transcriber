"""LocalDispatch / Task dispatch seam 單元測試。

驗證 deepening 的價值——LocalDispatch 的並發閘門（run-now vs queue）可以用
mock 注入完整覆蓋，不需要真的 Mongo 或 thread pool。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.worker_job import TranscriptionJob  # noqa: E402
from src.services import task_dispatch as td  # noqa: E402
from src.services.task_dispatch import (  # noqa: E402
    DispatchResult,
    LocalDispatch,
    get_task_dispatch,
    init_task_dispatch,
)


def _make_local_dispatch(monkeypatch):
    """建一個 LocalDispatch，task_repo / executor 全 mock。"""
    # orchestrator 在 __init__ 建構時會呼 get_sync_db()，mock 掉避免打 mongo
    monkeypatch.setattr(td, "get_sync_db", lambda: MagicMock())

    task_repo = MagicMock()
    task_repo.count_all_by_status = AsyncMock()
    task_repo.update = AsyncMock()
    task_repo.get_oldest_pending = AsyncMock(return_value=None)

    task_service = MagicMock()
    task_service.task_repo = task_repo

    dispatch = LocalDispatch(
        task_service=task_service,
        progress_store=MagicMock(),
        whisper=MagicMock(),
        punctuation=MagicMock(),
        executor=MagicMock(),
    )
    return dispatch, task_repo, task_service


class TestLocalDispatchGate:
    @pytest.mark.asyncio
    async def test_runs_immediately_when_under_limit(self, monkeypatch, tmp_path):
        dispatch, task_repo, task_service = _make_local_dispatch(monkeypatch)
        task_repo.count_all_by_status.return_value = 0  # 沒有任務在跑

        result = await dispatch.submit(
            job=TranscriptionJob(task_id="t1"),
            audio_local_path=tmp_path / "input.mp3",
            temp_dir=tmp_path,
            user_tier="free",
        )

        assert result.status == "processing"
        assert result.queue_position == 0
        # 立即啟動：標 processing + submit 進 executor
        task_repo.update.assert_awaited_once_with("t1", {"status": "processing"})
        dispatch.executor.submit.assert_called_once()
        task_service.set_temp_dir.assert_called_once_with("t1", tmp_path)

    @pytest.mark.asyncio
    async def test_queues_when_at_limit(self, monkeypatch, tmp_path):
        dispatch, task_repo, _ = _make_local_dispatch(monkeypatch)
        # 第一次問 processing 數（滿載），第二次問 pending 數（顯示糖）
        task_repo.count_all_by_status.side_effect = [2, 5]

        result = await dispatch.submit(
            job=TranscriptionJob(task_id="t2"),
            audio_local_path=tmp_path / "input.mp3",
            temp_dir=tmp_path,
            user_tier="free",
        )

        assert result.status == "pending"
        assert result.queue_position == 5
        # 滿載：留 pending，不啟動
        task_repo.update.assert_not_awaited()
        dispatch.executor.submit.assert_not_called()


class TestSingleton:
    def test_get_before_init_raises(self):
        td._dispatch = None
        with pytest.raises(RuntimeError, match="尚未初始化"):
            get_task_dispatch()

    def test_init_then_get_returns_same(self):
        td._dispatch = None
        sentinel = MagicMock()
        init_task_dispatch(sentinel)
        assert get_task_dispatch() is sentinel


def test_dispatch_result_defaults():
    r = DispatchResult(status="pending")
    assert r.status == "pending"
    assert r.queue_position is None
