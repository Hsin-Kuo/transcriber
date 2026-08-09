"""OrderRepository 對真實 MongoDB 跑的行為測試（P1-9 對帳補償 sweep，第二意見審查 P0-A）。

比照 tests/unit/test_presence_repo.py 的範式：連 mongodb://localhost:27020，連不上
整組 skip。存在的理由：`iter_entitlement_pending` 的 `$lt` vs `$not: {"$gte": ...}}`
差異是 MongoDB 的 range-query type bracketing 行為，mock-based 的 document 形狀斷言
測不出「缺欄位的文件到底有沒有被撈到」——這條路只能對真 Mongo 跑才算數（審查者已
實測證實 `$lt` 版本是死碼，這裡把那次實測釘成回歸測試）。
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

from src.database.repositories.order_repo import OrderRepository  # noqa: E402
from src.utils.time_utils import get_utc_timestamp  # noqa: E402

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = f"order_repo_mongo_test_{uuid.uuid4().hex[:8]}"


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


pytestmark = pytest.mark.skipif(not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}")


@pytest.fixture
async def repo():
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    await db.orders.delete_many({})
    try:
        yield OrderRepository(db)
    finally:
        await client.drop_database(_TEST_DB)
        client.close()


class TestIterEntitlementPendingRealMongo:
    """地雷回歸：`$lt` 對缺欄位文件不生效，`$not: {"$gte": ...}}` 才對。"""

    async def test_missing_retry_count_field_is_picked_up(self, repo):
        # 模擬 _mark_entitlement_pending 忘記初始化欄位的情境（本 PR 已修正初始化，
        # 這裡直接繞過 repo 方法手動插入缺欄位的 doc，專門驗證查詢層本身的行為）。
        await repo.collection.insert_one({
            "merchant_order_no": "O1", "entitlement_pending": True,
        })
        docs = [d async for d in repo.iter_entitlement_pending(5)]
        assert {d["merchant_order_no"] for d in docs} == {"O1"}

    async def test_retry_count_below_max_is_picked_up(self, repo):
        await repo.collection.insert_one({
            "merchant_order_no": "O2", "entitlement_pending": True, "entitlement_retry_count": 3,
        })
        docs = [d async for d in repo.iter_entitlement_pending(5)]
        assert {d["merchant_order_no"] for d in docs} == {"O2"}

    async def test_retry_count_at_max_is_excluded(self, repo):
        await repo.collection.insert_one({
            "merchant_order_no": "O3", "entitlement_pending": True, "entitlement_retry_count": 5,
        })
        docs = [d async for d in repo.iter_entitlement_pending(5)]
        assert docs == []

    async def test_not_pending_is_excluded(self, repo):
        await repo.collection.insert_one({
            "merchant_order_no": "O4", "entitlement_pending": False,
        })
        docs = [d async for d in repo.iter_entitlement_pending(5)]
        assert docs == []

    async def test_mixed_batch_picks_only_eligible(self, repo):
        await repo.collection.insert_many([
            {"merchant_order_no": "MISSING", "entitlement_pending": True},
            {"merchant_order_no": "LOW", "entitlement_pending": True, "entitlement_retry_count": 1},
            {"merchant_order_no": "MAXED", "entitlement_pending": True, "entitlement_retry_count": 5},
            {"merchant_order_no": "NOT_PENDING", "entitlement_pending": False},
        ])
        docs = [d async for d in repo.iter_entitlement_pending(5)]
        assert {d["merchant_order_no"] for d in docs} == {"MISSING", "LOW"}


class TestClaimMarkerRealMongo:
    async def test_first_call_true_second_call_false_on_missing_field(self, repo):
        await repo.collection.insert_one({"merchant_order_no": "O1"})
        first = await repo.claim_marker("O1", "quota_granted")
        second = await repo.claim_marker("O1", "quota_granted")
        assert first is True
        assert second is False
        doc = await repo.collection.find_one({"merchant_order_no": "O1"})
        assert doc["quota_granted"] is True


class TestStampReconciliationFirstSeenRealMongo:
    async def test_only_writes_once(self, repo):
        await repo.collection.insert_one({"merchant_order_no": "O1"})
        t1 = get_utc_timestamp()
        await repo.stamp_reconciliation_first_seen("O1", t1)
        await repo.stamp_reconciliation_first_seen("O1", t1 + 999)
        doc = await repo.collection.find_one({"merchant_order_no": "O1"})
        assert doc["reconciliation_first_seen_at"] == t1
