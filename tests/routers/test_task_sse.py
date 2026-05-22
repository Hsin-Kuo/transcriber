"""SSE task-events 串流診斷 — 重現「completed 沒即時推送」回報。

直接驅動 task_status_events 的 event_generator，用 scripted task 狀態序列
(processing → completed)，斷言後端有送出含 completed 的匿名 data: frame
(前端 EventSource.onmessage 只收匿名 data:，不收具名 event:)。
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers.tasks import task_status_events  # noqa: E402


class FakeTaskService:
    """get_task 回傳 scripted 序列；超出後固定回最後一筆。"""

    def __init__(self, sequence):
        self._seq = list(sequence)
        self._i = 0

    async def get_task(self, task_id, user_id=None):
        v = self._seq[self._i] if self._i < len(self._seq) else self._seq[-1]
        self._i += 1
        return v


async def _collect(resp):
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk)
    return chunks


async def test_sse_emits_anonymous_completed_data_frame(monkeypatch):
    """轉錄完成時，SSE 必須送出『匿名 data: frame 且 status=completed』。"""
    async def _no_sleep(*a, **k):
        pass
    monkeypatch.setattr("src.routers.tasks.asyncio.sleep", _no_sleep)

    proc = {"_id": "t1", "task_id": "t1", "status": "processing",
            "progress": "轉錄處理中", "progress_percentage": 85}
    done = {"_id": "t1", "task_id": "t1", "status": "completed"}
    # perm-check + iter1(proc) + iter2(completed)
    svc = FakeTaskService([proc, proc, done])

    resp = await task_status_events("t1", task_service=svc, current_user={"_id": "u1"})
    chunks = await _collect(resp)

    # 匿名 data: frame = onmessage 收得到的；具名 event: frame onmessage 收不到
    anon_data = [c for c in chunks if c.startswith("data: ")]
    completed = [
        c for c in anon_data
        if json.loads(c[len("data: "):].strip()).get("status") == "completed"
    ]
    assert completed, (
        "SSE 沒送出含 completed 的匿名 data: frame —— 前端 onmessage 收不到完成。\n"
        f"chunks={chunks}"
    )
