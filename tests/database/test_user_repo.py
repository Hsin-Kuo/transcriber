"""UserRepository.update_subscription_fields 的原子語意單元測試
（P0-2(b) 金流體檢；F6/F7 第二意見審查補測）。

比照 tests/database/test_order_repo.py 的寫法：mock collection.update_one，直接
斷言 filter/update document 形狀——guard 必須進 filter（不能滲進 $set 反而變成
「順便把 guard 欄位也設成 guard 值」）、$set 的 key 必須全部帶 `subscription.` 前綴
（不能不小心整段覆蓋）、guard 命中與否要用 matched_count 判斷（F7：modified_count
在「值沒變」時會誤報 stale）。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.database.repositories.user_repo import UserRepository  # noqa: E402


def _make_repo(matched_count=1, modified_count=1):
    db = MagicMock()
    collection = MagicMock()
    result = MagicMock()
    result.matched_count = matched_count
    result.modified_count = modified_count
    collection.update_one = AsyncMock(return_value=result)
    db.users = collection
    return UserRepository(db), collection, result


class TestUpdateSubscriptionFields:
    async def test_set_keys_are_all_prefixed_with_subscription(self):
        repo, collection, _ = _make_repo()
        await repo.update_subscription_fields(str(ObjectId()), {"status": "active", "tier": "pro"})
        _, update = collection.update_one.await_args.args
        set_doc = update["$set"]
        assert set_doc["subscription.status"] == "active"
        assert set_doc["subscription.tier"] == "pro"
        assert "status" not in set_doc  # 不帶前綴的裸鍵不該出現（不是整包覆蓋）
        assert "tier" not in set_doc
        assert "updated_at" in set_doc  # 頂層欄位，不帶 subscription. 前綴

    async def test_guard_is_merged_into_filter_not_set(self):
        repo, collection, _ = _make_repo()
        uid = str(ObjectId())
        guard = {"subscription.next_charge_at": 1000}
        await repo.update_subscription_fields(uid, {"status": "active"}, guard=guard)
        filt, update = collection.update_one.await_args.args
        assert filt["subscription.next_charge_at"] == 1000
        assert filt["_id"] == ObjectId(uid)
        assert "subscription.next_charge_at" not in update["$set"]

    async def test_no_guard_filters_only_by_id(self):
        repo, collection, _ = _make_repo()
        uid = str(ObjectId())
        await repo.update_subscription_fields(uid, {"status": "active"}, guard=None)
        filt, _ = collection.update_one.await_args.args
        assert filt == {"_id": ObjectId(uid)}

    async def test_invalid_object_id_returns_false_without_db_call(self):
        repo, collection, _ = _make_repo()
        ok = await repo.update_subscription_fields("not-a-valid-object-id", {"status": "active"})
        assert ok is False
        collection.update_one.assert_not_awaited()

    async def test_guard_miss_returns_false(self):
        """guard 不符 → filter 不命中任何文件 → matched_count=0 → False。"""
        repo, collection, _ = _make_repo(matched_count=0, modified_count=0)
        ok = await repo.update_subscription_fields(
            str(ObjectId()), {"status": "active"}, guard={"subscription.next_charge_at": 999}
        )
        assert ok is False

    async def test_matched_but_value_unchanged_still_returns_true(self):
        """F7 核心場景：guard 有命中（matched_count=1），但要寫的值剛好跟現有值相同，
        Mongo 回報 modified_count=0——這不是 stale，是「本來就是這個值」，必須回 True，
        否則呼叫端（例如 /cancel）會把等冪的重複請求誤判成 409 併發衝突。
        """
        repo, collection, _ = _make_repo(matched_count=1, modified_count=0)
        ok = await repo.update_subscription_fields(
            str(ObjectId()), {"status": "active"}, guard={"subscription.next_charge_at": 1000}
        )
        assert ok is True
