"""T5-d 轉錄流程整合測試 — Task dispatch seam（LocalDispatch）。

安全網：真 test Mongo + 真 TranscriptionOrchestrator + 假 processor。驗證 local
派發流程的**整合行為**——submit() 立即啟動 / 滿載排隊、撿單器接走 pending Task
→ orchestrator 跑完 → 任務 completed——不碰真 Whisper（轉錄品質由各 processor
自己的測試負責）。

前置：連得到的 MongoDB（MONGODB_URL 或 localhost:27020），連不上整組 skip；
      ffmpeg（orchestrator PREPARATION 的 convert_to_mp3 真的會跑）。
"""
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("DEPLOY_ENV", "local")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from bson import ObjectId  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import src.services.task_dispatch as td  # noqa: E402
from src.database.repositories.task_repo import TaskRepository  # noqa: E402
from src.models.worker_job import TranscriptionJob  # noqa: E402
from src.services.progress_store import InMemoryProgressStore  # noqa: E402
from src.services.task_dispatch import LocalDispatch  # noqa: E402
from src.services.task_service import TaskService  # noqa: E402
from src.utils.shared_state import TaskStateStore  # noqa: E402

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = "transcriber_test"


def _mongo_available() -> bool:
    if MongoClient is None:
        return False
    try:
        c = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=1000)
        c.admin.command("ping")
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}"
)


# ── fakes ────────────────────────────────────────────────

class FakeWhisper:
    """罐頭轉錄結果——不碰真 Whisper。"""

    def transcribe(self, mp3_path, language=None, progress_callback=None):
        if progress_callback is not None:
            progress_callback(1.0, 1.0)
        return "hello world", [
            {"text": "hello", "start": 0.0, "end": 0.5},
            {"text": "world", "start": 0.5, "end": 1.0},
        ], "en"

    def transcribe_in_chunks(self, mp3_path, language=None, progress_callback=None):
        return self.transcribe(mp3_path, language, progress_callback)


class FakePunctuation:
    def process(self, text, provider=None, language=None, progress_callback=None):
        if progress_callback is not None:
            progress_callback(1, 1)
        return text + "。", "fake-model", {"total": 1}


# ── fixtures ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def sync_client():
    client = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    yield client
    client.drop_database(_TEST_DB)
    client.close()


@pytest.fixture
def sync_db(sync_client):
    """orchestrator（sync pymongo）視角的 test DB；每個 test 清空 collection。"""
    database = sync_client[_TEST_DB]
    for coll in ("tasks", "transcriptions", "segments", "reservations", "users"):
        database[coll].delete_many({})
    return database


@pytest.fixture
async def motor_db():
    """task_repo（async motor）視角的同一個 test DB。"""
    client = AsyncIOMotorClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    yield client[_TEST_DB]
    client.close()


@pytest.fixture
def tiny_audio(tmp_path):
    """ffmpeg 生 1 秒靜音 wav 到 work/input.wav（撿單器靠 input.* 命名定位音檔）。"""
    work = tmp_path / "work"
    work.mkdir()
    path = work / "input.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "1", str(path)],
        check=True, capture_output=True,
    )
    return path


# ── helpers ──────────────────────────────────────────────

def _make_dispatch(monkeypatch, sync_db, motor_db, executor) -> LocalDispatch:
    """真 LocalDispatch：orchestrator 用 sync test DB，task_repo 用 motor test DB。"""
    monkeypatch.setattr(td, "get_sync_db", lambda: sync_db)
    progress_store = InMemoryProgressStore()
    task_service = TaskService(TaskRepository(motor_db), progress_store, TaskStateStore())
    return LocalDispatch(
        task_service=task_service,
        progress_store=progress_store,
        whisper=FakeWhisper(),
        punctuation=FakePunctuation(),
        executor=executor,
    )


def _insert_task(sync_db, *, status="pending", config=None) -> str:
    """插入一筆 task doc（模擬 router 已 task_repo.create）。"""
    task_id = str(uuid.uuid4())
    sync_db.tasks.insert_one({
        "_id": task_id,
        "task_id": task_id,
        "status": status,
        "task_type": "paragraph",
        "user": {"user_id": str(ObjectId()), "tier": "free"},
        "config": config or {},
        "file": {"filename": "meeting.m4a"},
        "stats": {"audio_duration_seconds": 1},
        "keep_audio": False,
        "timestamps": {"created_at": 1700000000},
    })
    return task_id


# ── tests ────────────────────────────────────────────────

class TestSubmitFlow:
    async def test_submit_runs_immediately_then_completes(
        self, monkeypatch, sync_db, motor_db, tiny_audio
    ):
        """submit() 未滿載 → 立即跑真 orchestrator → 任務 completed、transcription 落地。"""
        executor = ThreadPoolExecutor(max_workers=2)
        dispatch = _make_dispatch(monkeypatch, sync_db, motor_db, executor)
        task_id = _insert_task(sync_db, status="pending")

        result = await dispatch.submit(
            job=TranscriptionJob(task_id=task_id, language="en", use_chunking=False),
            audio_local_path=tiny_audio,
            temp_dir=tiny_audio.parent,
            user_tier="free",
        )
        executor.shutdown(wait=True)  # 等 orchestrator 在 thread 跑完

        assert result.status == "processing"
        assert sync_db.tasks.find_one({"_id": task_id})["status"] == "completed"
        assert sync_db.transcriptions.find_one({"_id": task_id}) is not None

    async def test_submit_queues_when_at_capacity(
        self, monkeypatch, sync_db, motor_db, tiny_audio
    ):
        """已有 MAX_CONCURRENT_TASKS 個 processing → submit() 留 pending、不啟動。"""
        executor = ThreadPoolExecutor(max_workers=2)
        dispatch = _make_dispatch(monkeypatch, sync_db, motor_db, executor)
        for _ in range(LocalDispatch.MAX_CONCURRENT_TASKS):
            _insert_task(sync_db, status="processing")
        task_id = _insert_task(sync_db, status="pending")

        result = await dispatch.submit(
            job=TranscriptionJob(task_id=task_id),
            audio_local_path=tiny_audio,
            temp_dir=tiny_audio.parent,
            user_tier="free",
        )
        executor.shutdown(wait=True)

        assert result.status == "pending"
        # 滿載 → 沒被啟動，狀態仍 pending
        assert sync_db.tasks.find_one({"_id": task_id})["status"] == "pending"


class TestPoller:
    async def test_poller_dequeues_and_completes(
        self, monkeypatch, sync_db, motor_db, tiny_audio
    ):
        """撿單器接走 pending Task → 真 orchestrator 跑完 → completed。"""
        executor = ThreadPoolExecutor(max_workers=2)
        dispatch = _make_dispatch(monkeypatch, sync_db, motor_db, executor)
        task_id = _insert_task(
            sync_db, status="pending",
            config={"language": "en", "chunk_audio": False, "punct_provider": "gemini"},
        )
        # 模擬 submit() 已登記 temp_dir（撿單器靠它定位 input.* 音檔）
        dispatch.task_service.set_temp_dir(task_id, tiny_audio.parent)

        await dispatch._poll_once()
        executor.shutdown(wait=True)

        assert sync_db.tasks.find_one({"_id": task_id})["status"] == "completed"
        assert sync_db.transcriptions.find_one({"_id": task_id}) is not None

    async def test_poller_marks_failed_when_audio_missing(
        self, monkeypatch, sync_db, motor_db, tmp_path
    ):
        """撿單器：登記的 temp_dir 內找不到 input.* → 任務標 failed。"""
        executor = ThreadPoolExecutor(max_workers=1)
        dispatch = _make_dispatch(monkeypatch, sync_db, motor_db, executor)
        task_id = _insert_task(sync_db, status="pending")
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        dispatch.task_service.set_temp_dir(task_id, empty_dir)

        await dispatch._poll_once()
        executor.shutdown(wait=True)

        task = sync_db.tasks.find_one({"_id": task_id})
        assert task["status"] == "failed"
        assert task["error"]["code"] == "AUDIO_MISSING"
