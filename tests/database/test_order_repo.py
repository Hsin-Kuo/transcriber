"""OrderRepository 的 claim_paid / mark_failed_unless_paid 原子語意單元測試
（P0-1/P0-3 金流體檢；F6 第二意見審查補測）。

比照 tests/database/test_job_lease_repo.py 的寫法：mock collection.update_one，直接
斷言送進 Mongo 的 filter/update document 形狀，確保「status != paid 才能寫」這條
併發防線真的長在查詢條件裡，不是只在 Python 這層口頭承諾。
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

from src.database.repositories.order_repo import OrderRepository  # noqa: E402


class _FakeCursor:
    """`db.orders.find(...)` 回傳的 motor cursor 極簡替身（`async for` + 可鏈式 `.sort()`/`.limit()`）。"""

    def __init__(self, docs):
        self.docs = docs
        self.limit_value = None
        self.sort_args = None

    def sort(self, key, direction=1):
        self.sort_args = (key, direction)
        return self

    def limit(self, n):
        self.limit_value = n
        return self

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _make_repo(modified_count=1):
    db = MagicMock()
    collection = MagicMock()
    result = MagicMock()
    result.modified_count = modified_count
    collection.update_one = AsyncMock(return_value=result)
    db.orders = collection
    return OrderRepository(db), collection, result


class TestClaimPaid:
    async def test_filter_requires_status_not_paid(self):
        repo, collection, _ = _make_repo()
        ok = await repo.claim_paid("SL1")
        assert ok is True
        filt, update = collection.update_one.await_args.args
        assert filt == {"merchant_order_no": "SL1", "status": {"$ne": "paid"}}

    async def test_set_writes_status_paid_and_paid_at(self):
        repo, collection, _ = _make_repo()
        await repo.claim_paid("SL1")
        _, update = collection.update_one.await_args.args
        assert update["$set"]["status"] == "paid"
        assert "paid_at" in update["$set"]
        assert "updated_at" in update["$set"]

    async def test_extra_updates_merged_into_set(self):
        repo, collection, _ = _make_repo()
        await repo.claim_paid("SL1", extra_updates={"trade_id": "T1"})
        _, update = collection.update_one.await_args.args
        assert update["$set"]["trade_id"] == "T1"
        assert update["$set"]["status"] == "paid"  # extra_updates 不會蓋掉 status

    async def test_no_extra_updates_does_not_add_none_fields(self):
        repo, collection, _ = _make_repo()
        await repo.claim_paid("SL1", extra_updates=None)
        _, update = collection.update_one.await_args.args
        assert set(update["$set"].keys()) == {"status", "paid_at", "updated_at"}

    async def test_modified_count_zero_returns_false(self):
        """搶不到（已經是 paid，$ne 條件不命中）→ modified_count=0 → False。"""
        repo, collection, _ = _make_repo(modified_count=0)
        ok = await repo.claim_paid("SL1")
        assert ok is False


class TestMarkFailedUnlessPaid:
    async def test_filter_requires_status_not_paid(self):
        repo, collection, _ = _make_repo()
        ok = await repo.mark_failed_unless_paid("SL1", {"status": "failed"})
        assert ok is True
        filt, update = collection.update_one.await_args.args
        assert filt == {"merchant_order_no": "SL1", "status": {"$ne": "paid"}}
        assert update["$set"]["status"] == "failed"
        assert "updated_at" in update["$set"]

    async def test_does_not_mutate_caller_dict(self):
        """updates 是呼叫端傳入的 dict，方法內部要 copy 再加 updated_at，不能就地改。"""
        repo, collection, _ = _make_repo()
        original = {"status": "failed"}
        await repo.mark_failed_unless_paid("SL1", original)
        assert original == {"status": "failed"}  # 呼叫端的 dict 沒被污染

    async def test_already_paid_order_returns_false(self):
        """已 paid 的單收到遲到的失敗通知 → $ne 條件不命中 → modified_count=0 → False。"""
        repo, collection, _ = _make_repo(modified_count=0)
        ok = await repo.mark_failed_unless_paid("SL1", {"status": "failed"})
        assert ok is False


class TestClaimMarker:
    """P1-9：$inc 副作用改走 marker 先搶後施——同一個 marker 第二次呼叫必須輸。"""

    async def test_filter_requires_marker_not_true(self):
        repo, collection, _ = _make_repo()
        ok = await repo.claim_marker("SL1", "quota_granted")
        assert ok is True
        filt, update = collection.update_one.await_args.args
        assert filt == {"merchant_order_no": "SL1", "quota_granted": {"$ne": True}}
        assert update["$set"]["quota_granted"] is True
        assert "updated_at" in update["$set"]

    async def test_second_call_loses(self):
        """modified_count=0（已經被設為 True）→ False，供呼叫端判斷『這次不用再施加』。"""
        repo, collection, _ = _make_repo(modified_count=0)
        ok = await repo.claim_marker("SL1", "quota_granted")
        assert ok is False


class TestIncrementEntitlementRetry:
    async def test_inc_and_returns_new_value(self):
        db = MagicMock()
        collection = MagicMock()
        collection.find_one_and_update = AsyncMock(return_value={"entitlement_retry_count": 3})
        db.orders = collection
        repo = OrderRepository(db)
        new_count = await repo.increment_entitlement_retry("SL1")
        assert new_count == 3
        filt, update = collection.find_one_and_update.await_args.args
        assert filt == {"merchant_order_no": "SL1"}
        assert update["$inc"] == {"entitlement_retry_count": 1}

    async def test_missing_doc_returns_zero(self):
        db = MagicMock()
        collection = MagicMock()
        collection.find_one_and_update = AsyncMock(return_value=None)
        db.orders = collection
        repo = OrderRepository(db)
        assert await repo.increment_entitlement_retry("GONE") == 0


class TestSweepExpiredPendingOrdersLeavesTradeIdOrdersAlone:
    """P1-9 讓路：有 trade_id 的 pending 單不再被這支 1 小時 sweep 標 expired
    ——它們歸 payment_reconciliation 對帳 sweep 管。document 形狀斷言（比照
    TestClaimPaid 的風格），不連真 Mongo。
    """

    async def test_filter_excludes_orders_with_trade_id(self):
        db = MagicMock()
        collection = MagicMock()
        result = MagicMock()
        result.modified_count = 0
        collection.update_many = AsyncMock(return_value=result)
        db.orders = collection
        repo = OrderRepository(db)
        await repo.sweep_expired_pending_orders()
        filt, update = collection.update_many.await_args.args
        assert filt["trade_id"] == {"$in": [None, ""]}
        assert filt["status"] == "pending"
        assert update["$set"]["status"] == "expired"


class TestIterForReconciliation:
    """P1-9：對帳 sweep 撈單條件——document 形狀斷言，重點是 gave_up/refund_seen
    旗標排除在查詢層 + 單輪上限（第二意見審查 P1-C/P2-E）。
    """

    async def test_query_shape(self):
        db = MagicMock()
        collection = MagicMock()
        cursor = _FakeCursor([])
        collection.find = MagicMock(return_value=cursor)
        db.orders = collection
        repo = OrderRepository(db)
        _ = [o async for o in repo.iter_for_reconciliation(900)]
        filt = collection.find.call_args.args[0]
        assert filt["status"] == {"$in": ["pending", "expired"]}
        assert filt["trade_id"] == {"$nin": [None, ""]}
        assert filt["reconciliation_gave_up"] == {"$ne": True}
        assert filt["refund_seen"] == {"$ne": True}
        assert "created_at" in filt and "$lte" in filt["created_at"]
        assert cursor.limit_value == OrderRepository.RECONCILIATION_BATCH_LIMIT
        # 批次輪替（第二意見審查）：依 last_reconciled_at 升冪，缺欄位（從未處理）在最前
        assert cursor.sort_args == ("last_reconciled_at", 1)


class TestIterEntitlementPending:
    async def test_query_shape(self):
        """P0-A（第二意見審查）：`$lt` 對缺欄位的文件不生效（type bracketing，跟
        sort() 的 BSON 排序規則是兩回事）——必須用 `$not: {"$gte": ...}}` 才能連
        缺欄位的文件一起撈到。真 Mongo 行為驗證見 test_order_repo_mongo.py。
        """
        db = MagicMock()
        collection = MagicMock()
        collection.find = MagicMock(return_value=_FakeCursor([]))
        db.orders = collection
        repo = OrderRepository(db)
        _ = [o async for o in repo.iter_entitlement_pending(5)]
        filt = collection.find.call_args.args[0]
        assert filt == {"entitlement_pending": True, "entitlement_retry_count": {"$not": {"$gte": 5}}}


class TestStampReconciliationFirstSeen:
    """P1-D（第二意見審查）：只在欄位不存在時寫入，document 形狀斷言。"""

    async def test_filter_excludes_existing_field(self):
        db = MagicMock()
        collection = MagicMock()
        collection.update_one = AsyncMock()
        db.orders = collection
        repo = OrderRepository(db)
        await repo.stamp_reconciliation_first_seen("SL1", 1000.0)
        filt, update = collection.update_one.await_args.args
        assert filt == {"merchant_order_no": "SL1", "reconciliation_first_seen_at": {"$exists": False}}
        assert update["$set"]["reconciliation_first_seen_at"] == 1000.0
