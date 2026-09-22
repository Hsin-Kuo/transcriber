"""TaskService.attach_progress —— 列表頁消 N+1 的批次進度合併。

重點不只是「合併結果對」，更是「不再逐筆重查」：用 spy store 數呼叫次數，
避免日後有人把它改回 per-task 查詢而測試照樣綠。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.progress_store import (  # noqa: E402
    InMemoryProgressStore,
    Phase,
)
from src.services.task_service import TaskService  # noqa: E402


class SpyProgressStore(InMemoryProgressStore):
    """記錄 get / get_many 的呼叫次數與收到的 id 批次。"""

    def __init__(self):
        super().__init__()
        self.get_calls = 0
        self.get_many_calls = 0
        self.last_ids = None

    def get(self, task_id):
        self.get_calls += 1
        return super().get(task_id)

    def get_many(self, task_ids):
        self.get_many_calls += 1
        self.last_ids = list(task_ids)
        return super().get_many(task_ids)


@pytest.fixture
def store():
    return SpyProgressStore()


@pytest.fixture
def service(store):
    # attach_progress 只碰 progress_store，不需要真的 task_repo
    return TaskService(task_repo=None, progress_store=store)


def _task(task_id, status="completed"):
    return {"_id": task_id, "task_id": task_id, "status": status}


class TestAttachProgressBatching:
    async def test_no_active_tasks_skips_store_entirely(self, service, store):
        """整頁都是已完成任務（列表頁常態）→ progress store 一次都不該被碰。"""
        tasks = [_task(f"t{i}") for i in range(10)]
        await service.attach_progress(tasks)
        assert store.get_many_calls == 0
        assert store.get_calls == 0

    async def test_uses_single_batched_call(self, service, store):
        """多筆進行中任務只打一次 get_many——這就是 N+1 的反向斷言。"""
        tasks = [_task(f"t{i}", status="processing") for i in range(10)]
        await service.attach_progress(tasks)
        assert store.get_many_calls == 1
        assert store.get_calls == 0

    async def test_only_queries_active_task_ids(self, service, store):
        """已完成任務不會有進行中進度，不該進批次查詢。"""
        tasks = [
            _task("done", status="completed"),
            _task("running", status="processing"),
            _task("queued", status="pending"),
            _task("dead", status="failed"),
        ]
        await service.attach_progress(tasks)
        assert sorted(store.last_ids) == ["queued", "running"]


class TestAttachProgressMerging:
    async def test_merges_snapshot_fields(self, service, store):
        store.set_phase("t1", Phase.TRANSCRIPTION, 0.5, message="轉錄中")
        tasks = [_task("t1", status="processing")]
        await service.attach_progress(tasks)
        assert tasks[0]["progress"] == "轉錄中"
        assert tasks[0]["phase"] == "transcription"
        assert tasks[0]["progress_percentage"] == 10.0 + 77.0 * 0.5

    async def test_merges_details(self, service, store):
        store.set_phase(
            "t1", Phase.TRANSCRIPTION, 0.5, details={"num_speakers": 3}
        )
        tasks = [_task("t1", status="processing")]
        await service.attach_progress(tasks)
        assert tasks[0]["num_speakers"] == 3

    async def test_task_without_snapshot_is_untouched(self, service):
        tasks = [_task("t1", status="processing")]
        await service.attach_progress(tasks)
        assert "phase" not in tasks[0]
        assert "progress_percentage" not in tasks[0]

    async def test_snapshots_do_not_bleed_across_tasks(self, service, store):
        store.set_phase("t1", Phase.PUNCTUATION, 1.0, message="t1 的訊息")
        tasks = [_task("t1", status="processing"), _task("t2", status="processing")]
        await service.attach_progress(tasks)
        assert tasks[0]["progress"] == "t1 的訊息"
        assert "progress" not in tasks[1]

    async def test_snapshot_never_overrides_status(self, service, store):
        """DB status 是權威值——router 靠這點才能安心把 active 篩選下推到 DB。

        details 是 orchestrator 自由填的 dict，這裡確認它無法改寫 status：
        否則會出現「篩 active 卻回傳 completed」的自相矛盾結果。
        """
        store.set_phase("t1", Phase.TRANSCRIPTION, 0.5, details={"status": "completed"})
        tasks = [_task("t1", status="processing")]
        await service.attach_progress(tasks)
        assert tasks[0]["status"] == "processing"

    async def test_protection_does_not_drop_other_details(self, service, store):
        """擋 status 不該連帶吃掉同一批的其他 details。"""
        store.set_phase(
            "t1", Phase.TRANSCRIPTION, 0.5,
            details={"status": "completed", "num_speakers": 2},
        )
        tasks = [_task("t1", status="processing")]
        await service.attach_progress(tasks)
        assert tasks[0]["status"] == "processing"
        assert tasks[0]["num_speakers"] == 2

    async def test_returns_same_list_object(self, service):
        tasks = [_task("t1")]
        assert await service.attach_progress(tasks) is tasks

    async def test_empty_list_is_safe(self, service):
        assert await service.attach_progress([]) == []
