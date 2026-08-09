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


class TestClaimRefundProcessedRealMongo:
    """P1-5：退款處理冪等閘門——形狀比照 claim_paid，回歸驗證「缺欄位可搶、第一次
    True 第二次 False」，且一併寫入 refund_seen（讓對帳 sweep 的排除條件天然生效）。
    """

    async def test_first_call_true_second_call_false_on_missing_field(self, repo):
        await repo.collection.insert_one({"merchant_order_no": "O1"})
        first = await repo.claim_refund_processed("O1")
        second = await repo.claim_refund_processed("O1")
        assert first is True
        assert second is False
        doc = await repo.collection.find_one({"merchant_order_no": "O1"})
        assert doc["refund_processed"] is True
        assert doc["refund_seen"] is True
        assert isinstance(doc["refunded_at"], (int, float))

    async def test_missing_order_cannot_be_claimed(self, repo):
        # 呼叫端（handle_full_refund/flag_partial_refund）在呼叫這個方法前已先確認
        # order 存在；這裡驗證查詢層本身對不存在的單天然回 False（不會誤報成功）。
        claimed = await repo.claim_refund_processed("NOPE")
        assert claimed is False


class TestHasNewerPaidSubscriptionOrderRealMongo:
    """P1-5 時效檢查（fail-safe 核心）：全額退款要不要自動降級，取決於使用者之後
    是否已經重新付款過。"""

    async def test_no_other_paid_order_returns_false(self, repo):
        await repo.collection.insert_one({
            "merchant_order_no": "O1", "user_id": "u1", "type": "subscription",
            "status": "paid", "paid_at": 1000,
        })
        assert await repo.has_newer_paid_subscription_order("u1", 1000) is False

    async def test_newer_paid_subscription_order_returns_true(self, repo):
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "user_id": "u1", "type": "subscription",
             "status": "paid", "paid_at": 1000},
            {"merchant_order_no": "O2", "user_id": "u1", "type": "renewal",
             "status": "paid", "paid_at": 2000},
        ])
        assert await repo.has_newer_paid_subscription_order("u1", 1000) is True

    async def test_older_paid_order_does_not_count_as_newer(self, repo):
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "user_id": "u1", "type": "subscription",
             "status": "paid", "paid_at": 2000},
            {"merchant_order_no": "O2", "user_id": "u1", "type": "subscription",
             "status": "paid", "paid_at": 1000},
        ])
        assert await repo.has_newer_paid_subscription_order("u1", 2000) is False

    async def test_non_subscription_type_is_excluded(self, repo):
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "user_id": "u1", "type": "subscription",
             "status": "paid", "paid_at": 1000},
            {"merchant_order_no": "O2", "user_id": "u1", "type": "extra_quota",
             "status": "paid", "paid_at": 2000},
        ])
        assert await repo.has_newer_paid_subscription_order("u1", 1000) is False

    async def test_other_user_does_not_count(self, repo):
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "user_id": "u1", "type": "subscription",
             "status": "paid", "paid_at": 1000},
            {"merchant_order_no": "O2", "user_id": "u2", "type": "subscription",
             "status": "paid", "paid_at": 2000},
        ])
        assert await repo.has_newer_paid_subscription_order("u1", 1000) is False

    async def test_pending_order_does_not_count(self, repo):
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "user_id": "u1", "type": "subscription",
             "status": "paid", "paid_at": 1000},
            {"merchant_order_no": "O2", "user_id": "u1", "type": "subscription",
             "status": "pending", "paid_at": None},
        ])
        assert await repo.has_newer_paid_subscription_order("u1", 1000) is False


class TestRefundPartialAndFullGatesAreIndependentRealMongo:
    """M5（第二意見審查）回歸：`claim_marker("refund_partial_flagged")`（部分退款
    閘門）與 `claim_refund_processed`（全額退款閘門）是完全不同的欄位，對同一張
    order 呼叫互不影響——部分退款(6)先到不會卡住之後抵達的全額退款(7)。"""

    async def test_partial_marker_does_not_block_full_refund_claim(self, repo):
        await repo.collection.insert_one({"merchant_order_no": "O1"})
        partial_claimed = await repo.claim_marker("O1", "refund_partial_flagged")
        full_claimed = await repo.claim_refund_processed("O1")
        assert partial_claimed is True
        assert full_claimed is True
        doc = await repo.collection.find_one({"merchant_order_no": "O1"})
        assert doc["refund_partial_flagged"] is True
        assert doc["refund_processed"] is True

    async def test_full_refund_claim_does_not_block_partial_marker(self, repo):
        """反向順序同樣互不干擾（雖然業務上 7 先於 6 抵達較罕見）。"""
        await repo.collection.insert_one({"merchant_order_no": "O1"})
        full_claimed = await repo.claim_refund_processed("O1")
        partial_claimed = await repo.claim_marker("O1", "refund_partial_flagged")
        assert full_claimed is True
        assert partial_claimed is True


class TestRefundAuditRealMongo:
    """M3：paid 單退款稽核 lane 的查詢/輪替 stamp 真 Mongo 行為。"""

    async def test_iter_excludes_orders_with_refund_outcome(self, repo):
        # 排除鍵是 refund_seen（N1，第二意見複核）：全額（claim_refund_processed 同時寫
        # refund_processed+refund_seen）與部分（flag_partial_refund 寫 refund_seen+
        # refund_partial_flagged）兩條路徑都會設它——部分退款單不得每天被重新稽核。
        now = get_utc_timestamp()
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "status": "paid", "type": "subscription", "paid_at": now},
            {"merchant_order_no": "O2", "status": "paid", "type": "subscription", "paid_at": now,
             "refund_processed": True, "refund_seen": True},
            {"merchant_order_no": "O3", "status": "paid", "type": "subscription", "paid_at": now,
             "refund_partial_flagged": True, "refund_seen": True, "needs_manual": True},
        ])
        docs = [d async for d in repo.iter_for_refund_audit()]
        assert {d["merchant_order_no"] for d in docs} == {"O1"}

    async def test_iter_excludes_non_subscription_non_extra_quota_types(self, repo):
        now = get_utc_timestamp()
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "status": "paid", "type": "subscription", "paid_at": now},
            {"merchant_order_no": "O2", "status": "paid", "type": "extra_quota", "paid_at": now},
            {"merchant_order_no": "O3", "status": "paid", "type": "something_else", "paid_at": now},
        ])
        docs = [d async for d in repo.iter_for_refund_audit()]
        assert {d["merchant_order_no"] for d in docs} == {"O1", "O2"}

    async def test_iter_excludes_non_paid_status(self, repo):
        now = get_utc_timestamp()
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "status": "paid", "type": "subscription", "paid_at": now},
            {"merchant_order_no": "O2", "status": "pending", "type": "subscription", "paid_at": None},
        ])
        docs = [d async for d in repo.iter_for_refund_audit()]
        assert {d["merchant_order_no"] for d in docs} == {"O1"}

    async def test_iter_excludes_orders_older_than_window(self, repo):
        now = get_utc_timestamp()
        await repo.collection.insert_many([
            {"merchant_order_no": "O1", "status": "paid", "type": "subscription", "paid_at": now},
            {"merchant_order_no": "O2", "status": "paid", "type": "subscription",
             "paid_at": now - OrderRepository.REFUND_AUDIT_WINDOW_SECONDS - 10},
        ])
        docs = [d async for d in repo.iter_for_refund_audit()]
        assert {d["merchant_order_no"] for d in docs} == {"O1"}

    async def test_stamp_refund_audited_writes_timestamp(self, repo):
        await repo.collection.insert_one({"merchant_order_no": "O1"})
        t1 = get_utc_timestamp()
        await repo.stamp_refund_audited("O1", t1)
        doc = await repo.collection.find_one({"merchant_order_no": "O1"})
        assert doc["refund_audited_at"] == t1

    async def test_iter_sorts_by_refund_audited_at_ascending_for_rotation(self, repo):
        """輪替：缺欄位（從未稽核過）排最前，已稽核過的依時間升冪排在後面。"""
        now = get_utc_timestamp()
        await repo.collection.insert_many([
            {"merchant_order_no": "RECENT", "status": "paid", "type": "subscription",
             "paid_at": now, "refund_audited_at": now - 10},
            {"merchant_order_no": "NEVER", "status": "paid", "type": "subscription", "paid_at": now},
            {"merchant_order_no": "OLDEST", "status": "paid", "type": "subscription",
             "paid_at": now, "refund_audited_at": now - 999},
        ])
        docs = [d async for d in repo.iter_for_refund_audit()]
        assert [d["merchant_order_no"] for d in docs] == ["NEVER", "OLDEST", "RECENT"]
