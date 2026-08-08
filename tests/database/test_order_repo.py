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
