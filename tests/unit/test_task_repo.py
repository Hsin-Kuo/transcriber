"""T5-a TaskRepository 測試。

需要連得到的 MongoDB（MONGODB_URL 或 localhost:27020），連不上整組 skip。
覆蓋 CRUD、find_by_user 篩選（status / tags AND / 排除已刪除）、以及 Task
dispatch seam 用的 count_all_by_status / get_oldest_pending。
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from src.database.repositories.task_repo import TaskRepository  # noqa: E402

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


@pytest.fixture
async def repo():
    client = AsyncIOMotorClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    db = client[_TEST_DB]
    await db.tasks.delete_many({})
    yield TaskRepository(db)
    await db.tasks.delete_many({})
    client.close()


def _doc(*, user_id="u1", status="completed", task_type="paragraph",
         tags=None, created_at=1700000000, deleted=False, flat_user=False) -> dict:
    """造一筆 task doc。flat_user=True 走扁平 user_id（向後相容格式）。"""
    task_id = str(uuid.uuid4())
    doc = {
        "_id": task_id,
        "task_id": task_id,
        "status": status,
        "task_type": task_type,
        "tags": tags or [],
        "timestamps": {"created_at": created_at},
    }
    if flat_user:
        doc["user_id"] = user_id
    else:
        doc["user"] = {"user_id": user_id}
    if deleted:
        doc["deleted"] = True
    return doc


class TestOwnedBy:
    """owned_by 是 ownership 條件的單一真實來源（純函式，不碰 DB）。"""

    def test_returns_nested_path_only(self):
        assert TaskRepository.owned_by("u1") == {"user.user_id": "u1"}

    def test_is_static(self):
        # 不需要實例即可呼叫（呼叫端可拼進 composed filter）
        assert TaskRepository.owned_by("x")["user.user_id"] == "x"


class TestCrud:
    async def test_create_and_get_by_id(self, repo):
        doc = _doc(status="completed")
        await repo.create(doc)
        got = await repo.get_by_id(doc["_id"])
        assert got is not None and got["status"] == "completed"

    async def test_get_by_id_and_user_nested(self, repo):
        doc = _doc(user_id="alice")
        await repo.create(doc)
        assert await repo.get_by_id_and_user(doc["_id"], "alice") is not None
        assert await repo.get_by_id_and_user(doc["_id"], "bob") is None

    async def test_get_by_id_and_user_flat_not_matched(self, repo):
        """舊扁平 user_id 相容分支已移除：扁平 doc 不再被 ownership 查詢命中
        （fail-safe — 拒絕存取而非洩漏）。prod 已無扁平資料（2026-06 probe）。"""
        doc = _doc(user_id="alice", flat_user=True)
        await repo.create(doc)
        assert await repo.get_by_id_and_user(doc["_id"], "alice") is None

    async def test_update_returns_true_and_persists(self, repo):
        doc = _doc(status="pending")
        await repo.create(doc)
        assert await repo.update(doc["_id"], {"status": "processing"}) is True
        assert (await repo.get_by_id(doc["_id"]))["status"] == "processing"

    async def test_soft_delete_keeps_doc_marked(self, repo):
        doc = _doc()
        await repo.create(doc)
        assert await repo.soft_delete(doc["_id"], "u1") is True
        got = await repo.get_by_id(doc["_id"])
        assert got is not None and got["deleted"] is True

    async def test_delete_removes_doc(self, repo):
        doc = _doc()
        await repo.create(doc)
        assert await repo.delete(doc["_id"], "u1") is True
        assert await repo.get_by_id(doc["_id"]) is None


class TestFindByUser:
    async def test_excludes_soft_deleted_by_default(self, repo):
        await repo.create(_doc())
        await repo.create(_doc(deleted=True))
        assert len(await repo.find_by_user("u1")) == 1

    async def test_include_deleted_returns_all(self, repo):
        await repo.create(_doc())
        await repo.create(_doc(deleted=True))
        assert len(await repo.find_by_user("u1", include_deleted=True)) == 2

    async def test_filter_by_status(self, repo):
        await repo.create(_doc(status="completed"))
        await repo.create(_doc(status="failed"))
        rows = await repo.find_by_user("u1", status="completed")
        assert len(rows) == 1 and rows[0]["status"] == "completed"

    async def test_tags_use_and_logic(self, repo):
        await repo.create(_doc(tags=["work", "urgent"]))
        await repo.create(_doc(tags=["work"]))
        # 同時含 work + urgent 的只有第一筆（$all = AND）
        assert len(await repo.find_by_user("u1", tags=["work", "urgent"])) == 1
        # 只篩 work → 兩筆都含
        assert len(await repo.find_by_user("u1", tags=["work"])) == 2

    async def test_count_by_user_excludes_deleted(self, repo):
        await repo.create(_doc(status="completed"))
        await repo.create(_doc(status="completed"))
        await repo.create(_doc(deleted=True))
        assert await repo.count_by_user("u1") == 2


class TestUserScopedQueries:
    """ownership 集中後新增/沿用的 user-scoped 方法。"""

    async def test_count_active_by_user(self, repo):
        await repo.create(_doc(status="pending"))
        await repo.create(_doc(status="processing"))
        await repo.create(_doc(status="completed"))
        await repo.create(_doc(status="pending", deleted=True))
        await repo.create(_doc(status="processing", user_id="other"))
        assert await repo.count_active_by_user("u1") == 2

    async def test_delete_all_for_user_scoped(self, repo):
        await repo.create(_doc(user_id="alice"))
        await repo.create(_doc(user_id="alice", status="pending"))
        await repo.create(_doc(user_id="bob"))
        deleted = await repo.delete_all_for_user("alice")
        assert deleted == 2
        assert await repo.count_by_user("bob") == 1

    async def test_anonymize_all_for_user(self, repo):
        # 造一筆含 PII / 內容參照的完成任務
        d = _doc(user_id="alice", tags=["會議", "客戶"])
        d["user"]["user_email"] = "alice@example.com"
        d["custom_name"] = "客戶王小明訪談"
        d["file"] = {"filename": "王小明_面試.mp3", "size_mb": 3.2}
        d["result"] = {"audio_file": "uploads/pro/x.mp3", "audio_filename": "x.mp3",
                       "text_length": 1234, "word_count": 200}
        d["stats"] = {"duration_seconds": 42, "token_usage": {"total": 10}}
        d["models"] = {"transcription": "large-v3"}
        await repo.create(d)
        await repo.create(_doc(user_id="bob"))  # 不受影響

        n = await repo.anonymize_all_for_user("alice", now=1700009999)
        assert n == 1

        task = await repo.get_by_id(d["_id"])
        # PII / 內容參照被清除
        assert task["user"]["user_email"] is None
        assert task["custom_name"] is None
        assert task["tags"] == []
        assert task["file"]["filename"] is None
        assert task["result"]["audio_file"] is None
        assert task["result"]["audio_filename"] is None
        # 統計欄位保留、任務仍存在、標記匿名化時間
        assert task["user"]["user_id"] == "alice"       # 假名鍵保留
        assert task["status"] == "completed"
        assert task["stats"]["duration_seconds"] == 42
        assert task["stats"]["token_usage"]["total"] == 10
        assert task["models"]["transcription"] == "large-v3"
        assert task["result"]["text_length"] == 1234    # 字數統計（非 PII）保留
        assert task["anonymized_at"] == 1700009999
        # bob 不受影響（任務數不變、未被匿名化）
        assert await repo.count_by_user("bob") == 1

    async def test_get_audio_refs_projects_minimal(self, repo):
        d1 = _doc(user_id="alice")
        d1["result"] = {"audio_file": "uploads/pro/x.mp3"}
        d1["config"] = {"language": "zh"}  # 不該被投影出來
        await repo.create(d1)
        await repo.create(_doc(user_id="bob"))
        refs = await repo.get_audio_refs_for_user("alice")
        assert len(refs) == 1
        assert refs[0]["result"]["audio_file"] == "uploads/pro/x.mp3"
        assert "config" not in refs[0]


class TestDispatchQueries:
    """Task dispatch seam（LocalDispatch 並發閘門 / 撿單器）用的查詢。"""

    async def test_count_all_by_status_is_global(self, repo):
        await repo.create(_doc(status="processing"))
        await repo.create(_doc(status="processing", user_id="other-user"))
        await repo.create(_doc(status="pending"))
        # 全系統計數，跨 user
        assert await repo.count_all_by_status("processing") == 2
        assert await repo.count_all_by_status("pending") == 1

    async def test_get_oldest_pending_returns_earliest(self, repo):
        await repo.create(_doc(status="pending", created_at=2000))
        await repo.create(_doc(status="pending", created_at=1000))
        await repo.create(_doc(status="completed", created_at=500))
        oldest = await repo.get_oldest_pending()
        assert oldest is not None
        assert oldest["status"] == "pending"
        assert oldest["timestamps"]["created_at"] == 1000  # 最舊的 pending

    async def test_get_oldest_pending_none_when_no_pending(self, repo):
        await repo.create(_doc(status="completed"))
        assert await repo.get_oldest_pending() is None
