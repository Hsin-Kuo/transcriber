"""JobLeaseRepository（背景 job 的 per-window leader lease，P0-2(a) 金流體檢）單元測試。

形狀比照 processed_webhook_repo 的 claim()：`_id` unique insert + DuplicateKeyError
判斷輸贏。這裡直接 mock collection.insert_one 來驗證 claim_window 的兩種結果，不需要
真 Mongo。
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

from pymongo.errors import DuplicateKeyError  # noqa: E402

from src.database.repositories.job_lease_repo import JobLeaseRepository  # noqa: E402


def _make_repo(insert_side_effect=None):
    db = MagicMock()
    collection = MagicMock()
    collection.insert_one = AsyncMock(side_effect=insert_side_effect)
    db.job_leases = collection
    return JobLeaseRepository(db), collection


class TestClaimWindow:
    async def test_insert_success_returns_true(self):
        repo, collection = _make_repo()
        ok = await repo.claim_window("renewal_sweep", 1800)
        assert ok is True
        collection.insert_one.assert_awaited_once()
        doc = collection.insert_one.await_args.args[0]
        assert doc["job"] == "renewal_sweep"
        assert doc["_id"].startswith("renewal_sweep:")

    async def test_duplicate_key_returns_false(self):
        repo, collection = _make_repo(insert_side_effect=DuplicateKeyError("dup"))
        ok = await repo.claim_window("renewal_sweep", 1800)
        assert ok is False

    async def test_same_window_produces_same_key(self):
        """同一個時間窗內兩次呼叫算出來的 _id 相同（互斥的關鍵：window 是 floor 除法）。"""
        repo, _ = _make_repo()
        window_seconds = 1_000_000  # 極大窗口，確保兩次呼叫落在同一個 window
        keys = []

        async def _capture(doc):
            keys.append(doc["_id"])

        repo.collection.insert_one = AsyncMock(side_effect=_capture)
        await repo.claim_window("order_cleanup", window_seconds)
        await repo.claim_window("order_cleanup", window_seconds)
        assert keys[0] == keys[1]

    async def test_different_jobs_do_not_collide(self):
        repo, collection = _make_repo()
        await repo.claim_window("renewal_sweep", 1800)
        await repo.claim_window("invoice_retry", 1800)
        keys = [c.args[0]["_id"] for c in collection.insert_one.await_args_list]
        assert keys[0] != keys[1]
        assert keys[0].startswith("renewal_sweep:")
        assert keys[1].startswith("invoice_retry:")


class TestCreateIndexes:
    async def test_creates_ttl_index_on_created_at(self):
        db = MagicMock()
        collection = MagicMock()
        collection.create_index = AsyncMock()
        db.job_leases = collection
        repo = JobLeaseRepository(db)
        await repo.create_indexes()
        collection.create_index.assert_awaited_once_with(
            "created_at", expireAfterSeconds=7 * 24 * 3600
        )
