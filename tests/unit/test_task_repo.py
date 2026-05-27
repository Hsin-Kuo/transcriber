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

    async def test_get_by_id_and_user_flat_format(self, repo):
        doc = _doc(user_id="alice", flat_user=True)
        await repo.create(doc)
        assert await repo.get_by_id_and_user(doc["_id"], "alice") is not None

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
