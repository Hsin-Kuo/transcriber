"""encrypt_existing_card_tokens migration 對真實 MongoDB 跑的行為測試（金流體檢 P2-10）。

比照 tests/database/test_order_repo_mongo.py 的範式：連 mongodb://localhost:27020，
連不上整組 skip。這裡測的是 migration 腳本本身的查詢/寫入行為（明文變 v1:、已加密
的不動、可 decrypt 回原值），不是 cipher 演算法本身（那部分見
tests/utils/test_card_token_cipher.py）。
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

from src.database.migrations import encrypt_existing_card_tokens as mig  # noqa: E402
from src.utils.card_token_cipher import decrypt  # noqa: E402

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = f"card_token_migration_test_{uuid.uuid4().hex[:8]}"


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
async def db(monkeypatch):
    # migrate() 讀模組級 MONGODB_URL/DB_NAME 全域常數，指到隔離的測試資料庫。
    monkeypatch.setattr(mig, "MONGODB_URL", _MONGO_URL)
    monkeypatch.setattr(mig, "DB_NAME", _TEST_DB)
    client = AsyncIOMotorClient(_MONGO_URL)
    database = client[_TEST_DB]
    await database.users.delete_many({})
    await database.orders.delete_many({})
    try:
        yield database
    finally:
        await client.drop_database(_TEST_DB)
        client.close()


class TestMigrateCardTokens:
    async def test_plaintext_encrypted_and_existing_v1_left_untouched(self, db):
        await db.users.insert_many([
            {"_id": "u1", "subscription": {"card_token": "PLAINTEXT1"}},
            {"_id": "u2", "subscription": {"card_token": "v1:already-encrypted"}},
            {"_id": "u3", "subscription": {}},  # 無 card_token，應被查詢排除
            {"_id": "u4", "subscription": {"card_token": ""}},  # 空字串，應被排除
        ])
        await db.orders.insert_many([
            {"merchant_order_no": "O1", "card_token": "PLAINTEXT2"},
            {"merchant_order_no": "O2", "card_token": "v1:already-encrypted-2"},
            {"merchant_order_no": "O3"},  # 無 card_token 欄位
        ])

        await mig.migrate()

        u1 = await db.users.find_one({"_id": "u1"})
        assert u1["subscription"]["card_token"].startswith("v1:")
        assert decrypt(u1["subscription"]["card_token"]) == "PLAINTEXT1"

        u2 = await db.users.find_one({"_id": "u2"})
        assert u2["subscription"]["card_token"] == "v1:already-encrypted"  # 冪等：未變動

        u3 = await db.users.find_one({"_id": "u3"})
        assert "card_token" not in u3["subscription"]

        o1 = await db.orders.find_one({"merchant_order_no": "O1"})
        assert o1["card_token"].startswith("v1:")
        assert decrypt(o1["card_token"]) == "PLAINTEXT2"

        o2 = await db.orders.find_one({"merchant_order_no": "O2"})
        assert o2["card_token"] == "v1:already-encrypted-2"

        o3 = await db.orders.find_one({"merchant_order_no": "O3"})
        assert "card_token" not in o3

    async def test_rerun_is_idempotent(self, db):
        await db.users.insert_one({"_id": "u1", "subscription": {"card_token": "PLAINTEXT1"}})
        await db.orders.insert_one({"merchant_order_no": "O1", "card_token": "PLAINTEXT2"})

        await mig.migrate()
        u1_first = await db.users.find_one({"_id": "u1"})
        o1_first = await db.orders.find_one({"merchant_order_no": "O1"})

        await mig.migrate()  # 重跑
        u1_second = await db.users.find_one({"_id": "u1"})
        o1_second = await db.orders.find_one({"merchant_order_no": "O1"})

        assert u1_second["subscription"]["card_token"] == u1_first["subscription"]["card_token"]
        assert o1_second["card_token"] == o1_first["card_token"]

    async def test_no_pending_records_is_noop(self, db, capsys):
        await db.users.insert_one({"_id": "u1", "subscription": {"card_token": "v1:x"}})
        await mig.migrate()
        out = capsys.readouterr().out
        assert "沒有需要加密的存量" in out
