"""InvoiceRepository 對真實 MongoDB 跑的行為測試（P2-14 金流體檢：reissue 防雙開）。

比照 tests/database/test_order_repo_mongo.py 的範式：連 mongodb://localhost:27020，
連不上整組 skip。partial unique index 的「同一 order 同時只能有一顆活躍發票」語意
是 MongoDB 索引層行為，mock 測不出真正的 DuplicateKeyError，只能對真 Mongo 跑。
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
    from pymongo.errors import DuplicateKeyError
except ImportError:  # pragma: no cover
    MongoClient = None

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from src.database.repositories.invoice_repo import InvoiceRepository  # noqa: E402

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = f"invoice_repo_mongo_test_{uuid.uuid4().hex[:8]}"


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
    await db.invoices.delete_many({})
    try:
        yield InvoiceRepository(db)
    finally:
        await client.drop_database(_TEST_DB)
        client.close()


class TestActiveInvoiceUniqueIndex:
    async def test_second_pending_doc_for_same_order_raises_duplicate_key(self, repo):
        await repo.create_indexes()
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                            "status": "pending", "buyer": {}, "amount_twd": 1})
        with pytest.raises(DuplicateKeyError):
            await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1-R1",
                                "status": "pending", "buyer": {}, "amount_twd": 1})

    async def test_issued_then_failed_for_same_order_also_conflicts(self, repo):
        """issued/pending/failed 三個狀態互相都算「活躍」——不是只有同狀態才擋。"""
        await repo.create_indexes()
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                            "status": "issued", "buyer": {}, "amount_twd": 1})
        with pytest.raises(DuplicateKeyError):
            await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1-R1",
                                "status": "failed", "buyer": {}, "amount_twd": 1})

    async def test_voided_and_needs_manual_coexist_legally(self, repo):
        """voided/needs_manual 不在 partial filter 內——同一 order 可以有多顆
        （作廢又重開的歷史、或多次 needs_manual 終局），不受這顆 index 限制。"""
        await repo.create_indexes()
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                            "status": "voided", "buyer": {}, "amount_twd": 1})
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1-R1",
                            "status": "voided", "buyer": {}, "amount_twd": 1})
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1-R2",
                            "status": "needs_manual", "buyer": {}, "amount_twd": 1})
        docs = await repo.list_by_order_no("O1")
        assert len(docs) == 3  # 全部成功落地，沒有任何一筆被 index 擋下

    async def test_different_orders_do_not_conflict(self, repo):
        await repo.create_indexes()
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                            "status": "pending", "buyer": {}, "amount_twd": 1})
        # 不同 order_no，即使同樣是 pending 也不該撞號
        await repo.create({"order_no": "O2", "user_id": "u1", "data_id": "SL-O2",
                            "status": "pending", "buyer": {}, "amount_twd": 1})
        docs1 = await repo.list_by_order_no("O1")
        docs2 = await repo.list_by_order_no("O2")
        assert len(docs1) == 1 and len(docs2) == 1

    async def test_index_build_failure_on_preexisting_conflicting_data_does_not_raise(self, repo):
        """C1：若上線前已有歷史違規資料（同 order 兩顆活躍 doc），建 index 會失敗——
        規格要求不自動修資料，只 log.error 讓應用照常啟動（不可讓 create_indexes()
        整個炸掉拖垮啟動流程）。"""
        # 繞過 repo.create（此時還沒建 index）直接塞兩顆違規歷史資料
        await repo.collection.insert_many([
            {"order_no": "LEGACY", "user_id": "u1", "data_id": "SL-LEGACY",
             "status": "pending", "buyer": {}, "amount_twd": 1,
             "attempts": 0, "claimed_until": None, "reissue_claimed_until": None,
             "allowance_numbers": [], "last_error": None},
            {"order_no": "LEGACY", "user_id": "u1", "data_id": "SL-LEGACY-R1",
             "status": "failed", "buyer": {}, "amount_twd": 1,
             "attempts": 0, "claimed_until": None, "reissue_claimed_until": None,
             "allowance_numbers": [], "last_error": None},
        ])
        # 不應該 raise——create_indexes() 內部要吞掉建 index 失敗
        await repo.create_indexes()
        # 應用仍可正常運作：其餘 index（data_id unique 等）依然有效
        docs = await repo.list_by_order_no("LEGACY")
        assert len(docs) == 2  # 歷史違規資料原封不動，沒有被自動 dedupe
