"""PR-C：使用者付款紀錄附掛發票摘要（設計 §4.3）。

分兩層：
1. `pick_user_facing_invoice`（純函式，`InvoiceRepository` 模組層級）——多筆歷史
   的挑選規則 + 回傳欄位白名單，不需要 Mongo。
2. `GET /subscriptions/orders`（`list_orders`）——對真實 Mongo 跑，驗證 join 組裝
   進到 response 的每一筆 order（連不上整組 skip，比照 test_admin_orders.py）。
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
from bson import ObjectId

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")
os.environ.setdefault("SMILEPAY_GRVC", "SEI0000000")
os.environ.setdefault("SMILEPAY_VERIFY_KEY", "0123456789ABCDEF0123456789ABCDEF")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import subscriptions as subs  # noqa: E402
from src.database.repositories.invoice_repo import pick_user_facing_invoice  # noqa: E402

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

_MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")
_TEST_DB = f"subs_orders_invoice_test_{uuid.uuid4().hex[:8]}"


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


# ── pick_user_facing_invoice：純邏輯，不需要 Mongo ──────────────────────────

def _inv(status, created_at, **extra):
    base = {
        "status": status, "created_at": created_at,
        "invoice_number": f"NUM-{status}-{created_at}", "random_number": "1234",
        "invoice_date": "2026/08/08",
        # 內部欄位：驗證絕不會被 pick_user_facing_invoice 帶出去
        "data_id": "SL-SECRET", "last_error": {"status": "-9999"}, "attempts": 3,
        "buyer": {"invoice_type": "personal", "carrier_num": "/AB12345"},
    }
    base.update(extra)
    return base


class TestPickUserFacingInvoice:
    def test_no_invoices_returns_none(self):
        assert pick_user_facing_invoice([]) is None

    def test_issued_returns_number_and_status(self):
        result = pick_user_facing_invoice([_inv("issued", 100)])
        assert result == {
            "invoice_number": "NUM-issued-100", "random_number": "1234",
            "invoice_date": "2026/08/08", "invoice_status": "issued",
        }

    def test_voided_returns_invoice_status_voided(self):
        result = pick_user_facing_invoice([_inv("voided", 100)])
        assert result["invoice_status"] == "voided"

    @pytest.mark.parametrize("status", ["pending", "failed", "needs_manual"])
    def test_internal_statuses_return_none(self, status):
        """對使用者一律顯示為「無」，不洩漏開票中/失敗等內部狀態。"""
        assert pick_user_facing_invoice([_inv(status, 100)]) is None

    def test_issued_preferred_over_newer_voided(self):
        """多筆歷史（作廢重開）：較新的 voided 不該蓋過較舊但仍 issued 的那筆。"""
        invoices = [_inv("issued", 100), _inv("voided", 200)]
        result = pick_user_facing_invoice(invoices)
        assert result["invoice_status"] == "issued"
        assert result["invoice_number"] == "NUM-issued-100"

    def test_all_voided_picks_latest(self):
        invoices = [_inv("voided", 100), _inv("voided", 300), _inv("voided", 200)]
        result = pick_user_facing_invoice(invoices)
        assert result["invoice_number"] == "NUM-voided-300"

    def test_multiple_issued_picks_latest(self):
        invoices = [_inv("issued", 100), _inv("issued", 300), _inv("issued", 200)]
        result = pick_user_facing_invoice(invoices)
        assert result["invoice_number"] == "NUM-issued-300"

    def test_mixed_pending_and_voided_falls_back_to_voided(self):
        invoices = [_inv("pending", 300), _inv("voided", 100)]
        result = pick_user_facing_invoice(invoices)
        assert result["invoice_status"] == "voided"

    def test_result_excludes_internal_fields(self):
        result = pick_user_facing_invoice([_inv("issued", 100)])
        assert set(result.keys()) == {"invoice_number", "random_number", "invoice_date", "invoice_status"}
        for leaked_field in ("data_id", "last_error", "attempts", "buyer"):
            assert leaked_field not in result


# ── GET /subscriptions/orders：真實 Mongo 整合 ──────────────────────────────
# ⚠️ skipif 只能掛在整合測試 class 上，不可用 module 層 pytestmark——CI 沒有 Mongo，
# module 層會把上面 TestPickUserFacingInvoice 的純邏輯測試（欄位白名單/狀態遮蔽的
# 安全斷言）一起跳過，CI 綠燈但零覆蓋。
_requires_mongo = pytest.mark.skipif(
    not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}"
)


@pytest.fixture
async def seeded_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    now = time.time()
    user = {"_id": ObjectId()}

    await db.orders.insert_many([
        # O-ISSUED：有一張 issued 發票（含 card_token/trade_id，驗證回傳白名單會濾掉）
        {"merchant_order_no": "O-ISSUED", "type": "subscription", "tier": "pro",
         "billing_cycle": "monthly", "status": "paid", "amount_twd": 299,
         "user_id": str(user["_id"]), "paid_at": now, "created_at": now,
         "card_token": "SECRET_TOKEN_MUST_NOT_LEAK", "trade_id": "PT12345",
         "invoice_snapshot": {"invoice_type": "personal"}},
        # O-VOIDED：唯一一張發票已作廢
        {"merchant_order_no": "O-VOIDED", "type": "subscription", "tier": "basic",
         "billing_cycle": "monthly", "status": "paid", "amount_twd": 99,
         "user_id": str(user["_id"]), "paid_at": now - 1, "created_at": now - 1},
        # O-PENDING-INVOICE：發票還在 needs_manual → 使用者端應看到「無」
        {"merchant_order_no": "O-PENDING-INVOICE", "type": "subscription", "tier": "basic",
         "billing_cycle": "monthly", "status": "paid", "amount_twd": 99,
         "user_id": str(user["_id"]), "paid_at": now - 2, "created_at": now - 2},
        # O-NO-INVOICE：完全沒有 invoice doc
        {"merchant_order_no": "O-NO-INVOICE", "type": "subscription", "tier": "basic",
         "billing_cycle": "monthly", "status": "failed", "amount_twd": 99,
         "user_id": str(user["_id"]), "paid_at": None, "created_at": now - 3},
        # O-REOPENED：先 voided 再 issued（重開成功）→ 應取較新的 issued
        {"merchant_order_no": "O-REOPENED", "type": "subscription", "tier": "pro",
         "billing_cycle": "yearly", "status": "paid", "amount_twd": 2990,
         "user_id": str(user["_id"]), "paid_at": now - 4, "created_at": now - 4},
        # 別人的訂單：owner 過濾（list_by_user 本身已做，這裡確認不會混進來）
        {"merchant_order_no": "O-OTHER-USER", "type": "subscription", "tier": "pro",
         "billing_cycle": "monthly", "status": "paid", "amount_twd": 299,
         "user_id": str(ObjectId()), "paid_at": now, "created_at": now},
    ])
    await db.invoices.insert_many([
        {"order_no": "O-ISSUED", "user_id": str(user["_id"]), "data_id": "SL-O-ISSUED",
         "status": "issued", "invoice_number": "AB111", "random_number": "1111",
         "invoice_date": "2026/08/08", "created_at": now, "attempts": 1,
         "last_error": None, "buyer": {"invoice_type": "personal"}},
        {"order_no": "O-VOIDED", "user_id": str(user["_id"]), "data_id": "SL-O-VOIDED",
         "status": "voided", "invoice_number": "AB222", "random_number": "2222",
         "invoice_date": "2026/08/01", "created_at": now - 1, "attempts": 1,
         "last_error": None, "buyer": {"invoice_type": "personal"}},
        {"order_no": "O-PENDING-INVOICE", "user_id": str(user["_id"]), "data_id": "SL-O-PENDING",
         "status": "needs_manual", "invoice_number": None, "random_number": None,
         "invoice_date": None, "created_at": now - 2, "attempts": 2,
         "last_error": {"status": "-10021"}, "buyer": {"invoice_type": "personal"}},
        # O-REOPENED：舊的 voided（較早）+ 新的 issued（較晚，重開成功）
        {"order_no": "O-REOPENED", "user_id": str(user["_id"]), "data_id": "SL-O-REOPENED",
         "status": "voided", "invoice_number": "CC001", "random_number": "3333",
         "invoice_date": "2026/06/01", "created_at": now - 100, "attempts": 1,
         "last_error": None, "buyer": {"invoice_type": "personal"}},
        {"order_no": "O-REOPENED", "user_id": str(user["_id"]), "data_id": "SL-O-REOPENED-R1",
         "status": "issued", "invoice_number": "CC002", "random_number": "4444",
         "invoice_date": "2026/06/02", "created_at": now - 50, "attempts": 1,
         "last_error": None, "buyer": {"invoice_type": "personal"}},
    ])
    try:
        yield db, user
    finally:
        await client.drop_database(_TEST_DB)
        client.close()


@_requires_mongo
class TestListOrdersInvoiceJoin:
    async def test_issued_order_returns_full_invoice_fields(self, seeded_db):
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        by_order = {o["merchant_order_no"]: o for o in result["orders"]}
        assert by_order["O-ISSUED"]["invoice"] == {
            "invoice_number": "AB111", "random_number": "1111",
            "invoice_date": "2026/08/08", "invoice_status": "issued",
        }

    async def test_order_fields_whitelisted_no_card_token(self, seeded_db):
        """回傳不可整包 order doc 下發：card_token（免 CVV 續扣憑證）/trade_id/
        invoice_snapshot 等內部欄位不得出現在使用者端回應（staging E2E 抓到的既有洩漏）。"""
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        by_order = {o["merchant_order_no"]: o for o in result["orders"]}
        row = by_order["O-ISSUED"]
        for leaked in ("card_token", "trade_id", "invoice_snapshot", "user_id",
                       "expires_at", "period_no"):
            assert leaked not in row, f"{leaked} 不該下發到使用者端"
        # 前端會用的欄位必須都在
        for needed in ("merchant_order_no", "type", "tier", "billing_cycle",
                       "amount_twd", "status", "created_at", "paid_at", "invoice", "_id"):
            assert needed in row

    async def test_voided_order_reports_voided_status(self, seeded_db):
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        by_order = {o["merchant_order_no"]: o for o in result["orders"]}
        assert by_order["O-VOIDED"]["invoice"]["invoice_status"] == "voided"

    async def test_needs_manual_invoice_hidden_as_none(self, seeded_db):
        """pending/failed/needs_manual 對使用者一律顯示為「無」，不洩漏內部狀態。"""
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        by_order = {o["merchant_order_no"]: o for o in result["orders"]}
        assert by_order["O-PENDING-INVOICE"]["invoice"] is None

    async def test_order_without_any_invoice_returns_none(self, seeded_db):
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        by_order = {o["merchant_order_no"]: o for o in result["orders"]}
        assert by_order["O-NO-INVOICE"]["invoice"] is None

    async def test_reopened_order_picks_newer_issued_over_older_voided(self, seeded_db):
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        by_order = {o["merchant_order_no"]: o for o in result["orders"]}
        assert by_order["O-REOPENED"]["invoice"]["invoice_status"] == "issued"
        assert by_order["O-REOPENED"]["invoice"]["invoice_number"] == "CC002"

    async def test_response_never_leaks_internal_invoice_fields(self, seeded_db):
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        for o in result["orders"]:
            if o["invoice"] is not None:
                assert set(o["invoice"].keys()) == {
                    "invoice_number", "random_number", "invoice_date", "invoice_status",
                }

    async def test_other_users_orders_not_included(self, seeded_db):
        db, user = seeded_db
        result = await subs.list_orders(limit=20, skip=0, current_user=user, db=db)
        assert "O-OTHER-USER" not in {o["merchant_order_no"] for o in result["orders"]}
