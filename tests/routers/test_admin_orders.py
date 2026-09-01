"""Admin 訂單/發票後台（PR-B）路由測試。

見 docs/INVOICE_SMILEPAY_INTEGRATION_PLAN.md §7、§10。分兩層：

1. 權限：wiring（每支 route 掛對 permission）已由 test_admin_rbac.py 的通用內省測試
   覆蓋；這裡再補「無權限 403 / BILLING_READ 唯讀不可寫」的行為測試，直接呼叫
   require_permission() 回傳的 dependency function（比照該檔手法）。
2. list/detail/void/retry/reissue：對真實 Mongo 跑（連不上整組 skip，比照
   test_admin_analytics_mongo.py）。void/retry/reissue 只 mock SmilePay HTTP 層
   （get_smilepay_service，比照 test_invoice_service.py 的做法）——invoice_service
   本身的業務邏輯不 mock，讓 admin router 層的職責（404/409/ValueError→4xx/audit）
   被真實跑過。
"""
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

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

from src.routers import admin as admin_router  # noqa: E402
from src.auth.rbac import Permission  # noqa: E402
from src.auth.dependencies import require_permission  # noqa: E402
from src.services import invoice_service as isvc  # noqa: E402
from src.utils.audit_logger import init_audit_logger  # noqa: E402
from src.database.repositories.audit_log_repo import AuditLogRepository  # noqa: E402

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

_MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")
_TEST_DB = f"admin_orders_test_{uuid.uuid4().hex[:8]}"


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

ADMIN = {"_id": ObjectId(), "email": "admin@x.com"}


class FakeRequest:
    """log_admin_action 只需要 .headers.get(...) / .client——不必真的建構 fastapi.Request。"""
    headers = {}
    client = None


def _mock_smilepay(monkeypatch, resp=None):
    """monkeypatch get_smilepay_service：只切斷 HTTP，invoice_service 業務邏輯照跑（比照
    test_invoice_service.py）。void_invoice 與 issue_invoice 共用同一個回應。"""
    svc = MagicMock()
    default_issue = {"Status": "0", "InvoiceNumber": "NEW001", "RandomNumber": "1234",
                      "InvoiceDate": "2026/08/08", "InvoiceType": "B2C"}
    svc.void_invoice = AsyncMock(return_value=resp or {"Status": "0"})
    svc.issue_invoice = AsyncMock(return_value=resp or default_issue)
    monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
    return svc


# ── 權限（無權限 403 / BILLING_READ 唯讀不可寫）───────────────────────────────

class _FakeUsers:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, query):
        return self._doc


class _FakeDB:
    def __init__(self, doc):
        self.users = _FakeUsers(doc)


class TestPermissions:
    async def test_support_role_cannot_read_billing(self):
        admin = {"_id": ObjectId()}
        db = _FakeDB({"_id": admin["_id"], "admin_role": "support"})  # SUPPORT 無 BILLING_READ
        checker = require_permission(Permission.BILLING_READ)
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=admin, db=db)
        assert exc.value.status_code == 403

    async def test_read_only_role_can_read_billing(self):
        admin = {"_id": ObjectId()}
        db = _FakeDB({"_id": admin["_id"], "admin_role": "read_only"})
        checker = require_permission(Permission.BILLING_READ)
        result = await checker(current_user=admin, db=db)
        assert result["_id"] == admin["_id"]

    async def test_read_only_role_cannot_write_billing(self):
        admin = {"_id": ObjectId()}
        db = _FakeDB({"_id": admin["_id"], "admin_role": "read_only"})
        checker = require_permission(Permission.BILLING_WRITE)
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=admin, db=db)
        assert exc.value.status_code == 403

    async def test_billing_role_can_write_billing(self):
        admin = {"_id": ObjectId()}
        db = _FakeDB({"_id": admin["_id"], "admin_role": "billing"})
        checker = require_permission(Permission.BILLING_WRITE)
        result = await checker(current_user=admin, db=db)
        assert result["_id"] == admin["_id"]


# ── _build_order_filter / _date_str_to_epoch（純邏輯）────────────────────────

class TestBuildOrderFilter:
    async def test_status_type_tier_filters(self):
        mongo, meta = await admin_router._build_order_filter(
            MagicMock(), email=None, status="paid", type="subscription", tier="pro",
            date_from=None, date_to=None,
        )
        assert mongo == {"status": "paid", "type": "subscription", "tier": "pro"}
        assert meta == {}

    async def test_date_range_converted_to_epoch_bounds(self):
        mongo, _ = await admin_router._build_order_filter(
            MagicMock(), email=None, status=None, type=None, tier=None,
            date_from="2026-08-01", date_to="2026-08-01",
        )
        assert mongo["created_at"]["$gte"] < mongo["created_at"]["$lte"]

    def test_invalid_date_format_ignored_not_500(self):
        assert admin_router._date_str_to_epoch("not-a-date") is None


# ── list / detail（真實 Mongo；$lookup 摘要規則）──────────────────────────────

@pytest.fixture
async def seeded_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    now = time.time()
    u1, u2 = ObjectId(), ObjectId()

    inv_issued = ObjectId()
    inv_voided_old = ObjectId()
    inv_voided_new = ObjectId()
    inv_o5_issued = ObjectId()
    inv_o5_voided = ObjectId()
    inv_failed = ObjectId()
    inv_needs_manual = ObjectId()
    inv_issued_no_number = ObjectId()

    await db.users.insert_many([
        {"_id": u1, "email": "a@x.com"},
        {"_id": u2, "email": "b@x.com"},
    ])
    await db.orders.insert_many([
        {"merchant_order_no": "O1", "type": "subscription", "tier": "pro", "billing_cycle": "monthly",
         "status": "paid", "amount_twd": 299, "user_id": str(u1), "paid_at": now, "created_at": now,
         "trade_id": "TXN123", "card_token": "SECRET_CARD_TOKEN_ABC"},
        {"merchant_order_no": "O2", "type": "extra_quota", "tier": None, "billing_cycle": None,
         "status": "paid", "amount_twd": 100, "user_id": str(u2), "paid_at": now - 10, "created_at": now - 10},
        {"merchant_order_no": "O3", "type": "subscription", "tier": "basic", "billing_cycle": "monthly",
         "status": "pending", "amount_twd": 99, "user_id": str(u1), "paid_at": None, "created_at": now - 20},
        {"merchant_order_no": "O5", "type": "subscription", "tier": "pro", "billing_cycle": "yearly",
         "status": "paid", "amount_twd": 2990, "user_id": str(u1), "paid_at": now - 1, "created_at": now - 1},
        {"merchant_order_no": "O6", "type": "subscription", "tier": "basic", "billing_cycle": "monthly",
         "status": "paid", "amount_twd": 99, "user_id": str(u1), "paid_at": now - 2, "created_at": now - 2},
        {"merchant_order_no": "O7", "type": "subscription", "tier": "basic", "billing_cycle": "monthly",
         "status": "paid", "amount_twd": 99, "user_id": str(u1), "paid_at": now - 3, "created_at": now - 3},
        {"merchant_order_no": "O8", "type": "subscription", "tier": "basic", "billing_cycle": "monthly",
         "status": "paid", "amount_twd": 99, "user_id": str(u1), "paid_at": now - 4, "created_at": now - 4},
    ])
    await db.invoices.insert_many([
        {"_id": inv_issued, "order_no": "O1", "user_id": str(u1), "data_id": "SL-O1", "status": "issued",
         "invoice_number": "AB123", "invoice_date": "2026/08/01", "created_at": now, "attempts": 1,
         "claimed_until": None, "last_error": None, "amount_twd": 299, "buyer": {"invoice_type": "personal"}},
        # O2：兩筆都 voided → 摘要應取「最新」的那筆（AB002）
        {"_id": inv_voided_old, "order_no": "O2", "user_id": str(u2), "data_id": "SL-O2", "status": "voided",
         "invoice_number": "AB001", "invoice_date": "2026/07/01", "created_at": now - 15,
         "voided_at": now - 14, "void_reason": "測試", "attempts": 1, "claimed_until": None,
         "last_error": None, "amount_twd": 100, "buyer": {"invoice_type": "personal"}},
        {"_id": inv_voided_new, "order_no": "O2", "user_id": str(u2), "data_id": "SL-O2-R1", "status": "voided",
         "invoice_number": "AB002", "invoice_date": "2026/07/05", "created_at": now - 12,
         "voided_at": now - 11, "void_reason": "測試2", "attempts": 1, "claimed_until": None,
         "last_error": None, "amount_twd": 100, "buyer": {"invoice_type": "personal"}},
        # O5：最新一筆是 voided、較舊那筆是 issued → 摘要應跳過新的 voided，取 issued
        {"_id": inv_o5_issued, "order_no": "O5", "user_id": str(u1), "data_id": "SL-O5", "status": "issued",
         "invoice_number": "ISS001", "invoice_date": "2026/06/01", "created_at": now - 100, "attempts": 1,
         "claimed_until": None, "last_error": None, "amount_twd": 2990, "buyer": {"invoice_type": "personal"}},
        {"_id": inv_o5_voided, "order_no": "O5", "user_id": str(u1), "data_id": "SL-O5-R1", "status": "voided",
         "invoice_number": "ISS001V", "invoice_date": "2026/06/05", "created_at": now - 1,
         "voided_at": now, "void_reason": "重開測試", "attempts": 1, "claimed_until": None,
         "last_error": None, "amount_twd": 2990, "buyer": {"invoice_type": "personal"}},
        {"_id": inv_failed, "order_no": "O6", "user_id": str(u1), "data_id": "SL-O6", "status": "failed",
         "invoice_number": None, "invoice_date": None, "created_at": now - 2, "attempts": 1,
         "next_retry_at": now - 1, "claimed_until": None,
         "last_error": {"status": "-9999", "desc": "測試失敗"}, "amount_twd": 99,
         "buyer": {"invoice_type": "personal"}},
        {"_id": inv_needs_manual, "order_no": "O7", "user_id": str(u1), "data_id": "SL-O7",
         "status": "needs_manual", "invoice_number": None, "invoice_date": None, "created_at": now - 3,
         "attempts": 2, "claimed_until": None,
         "last_error": {"status": "-10021", "desc": "統編錯誤"}, "amount_twd": 99,
         "buyer": {"invoice_type": "personal"}},
        # 邊界案例：status=issued 但 invoice_number 空（理論上不該發生，防禦性驗證用）
        {"_id": inv_issued_no_number, "order_no": "O8", "user_id": str(u1), "data_id": "SL-O8",
         "status": "issued", "invoice_number": None, "invoice_date": None, "created_at": now - 4,
         "attempts": 1, "claimed_until": None, "last_error": None, "amount_twd": 99,
         "buyer": {"invoice_type": "personal"}},
    ])
    ids = {
        "u1": u1, "u2": u2,
        "inv_issued": inv_issued, "inv_voided_old": inv_voided_old, "inv_voided_new": inv_voided_new,
        "inv_o5_issued": inv_o5_issued, "inv_o5_voided": inv_o5_voided,
        "inv_failed": inv_failed, "inv_needs_manual": inv_needs_manual,
        "inv_issued_no_number": inv_issued_no_number,
    }
    try:
        yield db, ids
    finally:
        await client.drop_database(_TEST_DB)
        client.close()


class TestListOrders:
    async def test_lookup_picks_latest_non_voided_or_falls_back_to_voided(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email=None, status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=None,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        assert result["total"] == 7
        by_order = {o["order_no"]: o for o in result["orders"]}
        assert by_order["O1"]["invoice"] == {"status": "issued", "invoice_number": "AB123",
                                              "invoice_date": "2026/08/01"}
        assert by_order["O1"]["user_email"] == "a@x.com"
        # 全 voided → 取最新那筆
        assert by_order["O2"]["invoice"]["invoice_number"] == "AB002"
        # 沒有任何 invoice
        assert by_order["O3"]["invoice"] is None
        # 最新是 voided、較舊是 issued → 跳過新的 voided
        assert by_order["O5"]["invoice"]["status"] == "issued"
        assert by_order["O5"]["invoice"]["invoice_number"] == "ISS001"

    async def test_filter_by_email(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email="b@x.com", status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=None,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        assert result["total"] == 1
        assert result["orders"][0]["order_no"] == "O2"

    async def test_filter_by_unknown_email_short_circuits_empty(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email="nobody@x.com", status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=None,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        assert result == {"orders": [], "total": 0, "skip": 0, "limit": 50}

    async def test_filter_by_invoice_status_none(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email=None, status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status="none", needs_attention=None,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        assert [o["order_no"] for o in result["orders"]] == ["O3"]

    async def test_filter_by_type_and_tier(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email=None, status=None, type="subscription", tier="pro",
            date_from=None, date_to=None, invoice_status=None, needs_attention=None,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        assert {o["order_no"] for o in result["orders"]} == {"O1", "O5"}

    async def test_pagination(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email=None, status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=None,
            skip=0, limit=2, admin=ADMIN, db=db,
        )
        assert result["total"] == 7
        assert len(result["orders"]) == 2

    async def test_default_response_flags_are_false_when_absent(self, seeded_db):
        """既有 O1~O8 都沒有這些對帳旗標欄位——回應要正確地把缺欄位正規化成 False，
        不是 None（前端直接當布林用）。"""
        db, _ids = seeded_db
        result = await admin_router.list_orders(
            email=None, status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=None,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        o1 = next(o for o in result["orders"] if o["order_no"] == "O1")
        assert o1["entitlement_pending"] is False
        assert o1["needs_manual"] is False
        assert o1["reconciliation_gave_up"] is False
        assert o1["refund_seen"] is False
        assert o1["refund_processed"] is False  # P1-5


class TestListOrdersNeedsAttention:
    """P3-J（第二意見審查）：needs_attention=True 一次篩出三種對帳補償旗標任一為
    True 的單；False/None 都不篩（維持既有全量列表行為）。

    L6（第二意見審查）：refund_seen **不再**是 needs_attention 的篩選條件之一——
    P1-5 之後它的語意已經從「退款待人工」變成「這筆單已經有退款結果了」（自動降級
    成功的 revoked/quota_deducted 也會寫它），繼續篩它會把『已經自動處理好』的單
    誤篩進『需要人工看一眼』。P4 專門驗證這個排除。
    """

    @pytest.fixture
    async def flagged_db(self, seeded_db):
        db, ids = seeded_db
        await db.orders.insert_many([
            {"merchant_order_no": "P1", "type": "extra_quota", "status": "paid", "amount_twd": 1,
             "user_id": str(ids["u1"]), "created_at": time.time(), "entitlement_pending": True},
            {"merchant_order_no": "P2", "type": "subscription", "status": "paid", "amount_twd": 1,
             "user_id": str(ids["u1"]), "created_at": time.time(), "needs_manual": True},
            {"merchant_order_no": "P3", "type": "subscription", "status": "pending", "amount_twd": 1,
             "user_id": str(ids["u1"]), "created_at": time.time(), "reconciliation_gave_up": True},
            # refund_seen 為 True 但 needs_manual 為 False：代表自動退款處置「已經
            # 有結果」（例如全額退款自動降級成功），不該落入 needs_attention。
            {"merchant_order_no": "P4", "type": "subscription", "status": "paid", "amount_twd": 1,
             "user_id": str(ids["u1"]), "created_at": time.time(), "refund_seen": True},
            # F7（跨 PR 複檢）：needs_refund 單獨為 True（_reject_duplicate 標的重複扣款
            # 待退款單，無 needs_manual）也必須進 needs_attention。
            {"merchant_order_no": "P5", "type": "subscription", "status": "paid", "amount_twd": 1,
             "user_id": str(ids["u1"]), "created_at": time.time(), "needs_refund": True},
        ])
        return db, ids

    async def test_needs_attention_true_filters_to_flagged_orders_only(self, flagged_db):
        db, _ids = flagged_db
        result = await admin_router.list_orders(
            email=None, status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=True,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        # L6：P4（只有 refund_seen）不該出現——已經有結果的退款不算『待人工』。
        # F7：P5（只有 needs_refund）必須出現——重複扣款待人工退款。
        assert {o["order_no"] for o in result["orders"]} == {"P1", "P2", "P3", "P5"}
        assert result["total"] == 4

    async def test_needs_attention_false_does_not_filter(self, flagged_db):
        db, _ids = flagged_db
        result = await admin_router.list_orders(
            email=None, status=None, type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=False,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        # 7 筆既有 seeded 訂單 + 5 筆新插入的旗標訂單
        assert result["total"] == 12

    async def test_needs_attention_combines_with_other_filters(self, flagged_db):
        db, _ids = flagged_db
        result = await admin_router.list_orders(
            email=None, status="pending", type=None, tier=None,
            date_from=None, date_to=None, invoice_status=None, needs_attention=True,
            skip=0, limit=50, admin=ADMIN, db=db,
        )
        assert {o["order_no"] for o in result["orders"]} == {"P3"}


class TestOrderDetail:
    async def test_detail_includes_full_invoice_history(self, seeded_db):
        db, _ids = seeded_db
        result = await admin_router.get_order_detail(order_no="O2", admin=ADMIN, db=db)
        assert result["order"]["merchant_order_no"] == "O2"
        assert result["order"]["user_email"] == "b@x.com"
        assert {inv["invoice_number"] for inv in result["invoices"]} == {"AB001", "AB002"}

    async def test_detail_404_for_missing_order(self, seeded_db):
        db, _ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.get_order_detail(order_no="NOPE", admin=ADMIN, db=db)
        assert exc.value.status_code == 404

    async def test_detail_excludes_card_token_but_keeps_trade_id(self, seeded_db):
        """finding #1：card_token 是 91APP 免 CVV 續扣憑證，BILLING_READ（含 read_only）
        不該拿得到；trade_id 是對帳交易序號要保留。"""
        db, _ids = seeded_db
        result = await admin_router.get_order_detail(order_no="O1", admin=ADMIN, db=db)
        assert "card_token" not in result["order"]
        assert result["order"]["trade_id"] == "TXN123"

    async def test_detail_surfaces_refund_processed_fields(self, seeded_db):
        """P1-5：refund_processed/refunded_at 是 admin 排查退款處置的可見性欄位。"""
        db, _ids = seeded_db
        await db.orders.update_one(
            {"merchant_order_no": "O1"},
            {"$set": {"refund_processed": True, "refunded_at": 12345}},
        )
        result = await admin_router.get_order_detail(order_no="O1", admin=ADMIN, db=db)
        assert result["order"]["refund_processed"] is True
        assert result["order"]["refunded_at"] == 12345


# ── void ─────────────────────────────────────────────────────────────────────

class TestVoidInvoice:
    async def test_success_marks_voided_and_writes_audit(self, seeded_db, monkeypatch):
        db, ids = seeded_db
        init_audit_logger(AuditLogRepository(db))
        _mock_smilepay(monkeypatch, resp={"Status": "0"})

        result = await admin_router.void_invoice(
            invoice_id=str(ids["inv_issued"]),
            body=admin_router.VoidInvoiceRequest(reason="測試作廢"),
            http_request=FakeRequest(), admin=ADMIN, db=db,
        )
        assert result["success"] is True
        assert result["invoice"]["status"] == "voided"

        updated = await db.invoices.find_one({"_id": ids["inv_issued"]})
        assert updated["status"] == "voided" and updated["void_reason"] == "測試作廢"

        log = await db.audit_logs.find_one({"action": "void_invoice"})
        assert log is not None and log["resource_id"] == str(ids["inv_issued"])

    async def test_smilepay_rejection_returns_400(self, seeded_db, monkeypatch):
        db, ids = seeded_db
        init_audit_logger(AuditLogRepository(db))
        _mock_smilepay(monkeypatch, resp={"Status": "-2009", "Desc": "已作廢過", "Nowstatus": "1"})

        with pytest.raises(HTTPException) as exc:
            await admin_router.void_invoice(
                invoice_id=str(ids["inv_o5_issued"]),
                body=admin_router.VoidInvoiceRequest(reason="重複作廢"),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["params"]["smilepay_status_code"] == "-2009"

    async def test_not_found_returns_404(self, seeded_db):
        db, _ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.void_invoice(
                invoice_id=str(ObjectId()),
                body=admin_router.VoidInvoiceRequest(reason="x"),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 404

    async def test_invalid_object_id_returns_404_not_500(self, seeded_db):
        db, _ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.void_invoice(
                invoice_id="not-a-valid-object-id",
                body=admin_router.VoidInvoiceRequest(reason="x"),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 404

    async def test_reason_over_20_chars_returns_400(self, seeded_db):
        db, ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.void_invoice(
                invoice_id=str(ids["inv_issued"]),
                body=admin_router.VoidInvoiceRequest(reason="x" * 21),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 400

    def test_reason_empty_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            admin_router.VoidInvoiceRequest(reason="")

    def test_reason_all_whitespace_rejected_by_pydantic(self):
        """finding #7：全空白理應視同「沒填」，strip 後空字串要撞 min_length=1。"""
        with pytest.raises(ValidationError):
            admin_router.VoidInvoiceRequest(reason="    ")

    def test_reason_is_stripped(self):
        body = admin_router.VoidInvoiceRequest(reason="  測試作廢  ")
        assert body.reason == "測試作廢"

    async def test_non_issued_status_returns_409(self, seeded_db):
        """finding #3：非 issued 的發票（如 failed）不可作廢——否則會拿空 invoice_number
        打 SmilePay 正式作廢 API。"""
        db, ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.void_invoice(
                invoice_id=str(ids["inv_failed"]),
                body=admin_router.VoidInvoiceRequest(reason="測試"),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409

    async def test_issued_without_invoice_number_returns_409(self, seeded_db):
        """finding #3 邊界案例：status=issued 但 invoice_number 空（理論上不該發生）
        也要擋，不能只看 status。"""
        db, ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.void_invoice(
                invoice_id=str(ids["inv_issued_no_number"]),
                body=admin_router.VoidInvoiceRequest(reason="測試"),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409


# ── retry ────────────────────────────────────────────────────────────────────

class TestRetryInvoice:
    async def test_success_via_attempt_issue(self, seeded_db, monkeypatch):
        db, ids = seeded_db
        init_audit_logger(AuditLogRepository(db))
        _mock_smilepay(monkeypatch, resp={"Status": "0", "InvoiceNumber": "RETRY001",
                                           "RandomNumber": "5678", "InvoiceDate": "2026/08/08",
                                           "InvoiceType": "B2C"})

        result = await admin_router.retry_invoice(
            invoice_id=str(ids["inv_failed"]), http_request=FakeRequest(), admin=ADMIN, db=db,
        )
        assert result["success"] is True
        assert result["invoice"]["status"] == "issued"
        assert result["invoice"]["invoice_number"] == "RETRY001"

        log = await db.audit_logs.find_one({"action": "retry_invoice"})
        assert log is not None

    async def test_invalid_status_returns_409(self, seeded_db):
        db, ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.retry_invoice(
                invoice_id=str(ids["inv_issued"]), http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409

    async def test_claim_miss_returns_409_and_does_not_write_audit(self, seeded_db, monkeypatch):
        """finding #4：搶不到 processing lease（模擬背景 sweep 正在處理同一張）要能
        分辨出來、回 409、且不可寫一筆「假裝成功」的 audit 記錄。"""
        db, ids = seeded_db
        init_audit_logger(AuditLogRepository(db))
        _mock_smilepay(monkeypatch)  # 不應該被呼叫到——lease 搶不到就短路了
        await db.invoices.update_one(
            {"_id": ids["inv_failed"]}, {"$set": {"claimed_until": time.time() + 60}},
        )

        with pytest.raises(HTTPException) as exc:
            await admin_router.retry_invoice(
                invoice_id=str(ids["inv_failed"]), http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409

        log = await db.audit_logs.find_one({"action": "retry_invoice"})
        assert log is None

    async def test_not_found_returns_404(self, seeded_db):
        db, _ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.retry_invoice(
                invoice_id=str(ObjectId()), http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 404

    async def test_order_missing_value_error_maps_to_404(self, seeded_db):
        db, ids = seeded_db
        await db.orders.delete_one({"merchant_order_no": "O6"})
        with pytest.raises(HTTPException) as exc:
            await admin_router.retry_invoice(
                invoice_id=str(ids["inv_failed"]), http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 404


# ── reissue ──────────────────────────────────────────────────────────────────

class TestReissueInvoice:
    async def test_success_creates_new_invoice(self, seeded_db, monkeypatch):
        db, ids = seeded_db
        init_audit_logger(AuditLogRepository(db))
        _mock_smilepay(monkeypatch, resp={"Status": "0", "InvoiceNumber": "REISSUE001",
                                           "RandomNumber": "9999", "InvoiceDate": "2026/08/08",
                                           "InvoiceType": "B2C"})

        result = await admin_router.reissue_invoice(
            invoice_id=str(ids["inv_voided_new"]),
            body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
            http_request=FakeRequest(), admin=ADMIN, db=db,
        )
        assert result["success"] is True
        assert result["invoice"]["status"] == "issued"
        assert result["invoice"]["order_no"] == "O2"
        assert result["invoice"]["data_id"] == "SL-O2-R2"  # 既有最大 R1 之後 +1

        log = await db.audit_logs.find_one({"action": "reissue_invoice"})
        assert log is not None

    async def test_with_corrected_buyer_switches_to_company(self, seeded_db, monkeypatch):
        db, ids = seeded_db
        init_audit_logger(AuditLogRepository(db))
        _mock_smilepay(monkeypatch, resp={"Status": "0", "InvoiceNumber": "REISSUE002",
                                           "RandomNumber": "1111", "InvoiceDate": "2026/08/08",
                                           "InvoiceType": "B2C2B"})

        body = admin_router.ReissueInvoiceRequest(corrected_buyer=admin_router.CorrectedBuyerModel(
            invoice_type="company", company_tax_id="12345678", company_name="測試公司",
        ))
        result = await admin_router.reissue_invoice(
            # O2 的發票全 voided（無 issued/進行中）——O5 有 issued 發票，重開會被
            # find_reissue_conflict 正確擋 409（複核 N1），不能當這個測試的來源
            invoice_id=str(ids["inv_voided_new"]), body=body,
            http_request=FakeRequest(), admin=ADMIN, db=db,
        )
        assert result["invoice"]["buyer"]["invoice_type"] == "company"
        assert result["invoice"]["buyer"]["company_tax_id"] == "12345678"

    async def test_invalid_status_returns_409(self, seeded_db):
        db, ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.reissue_invoice(
                invoice_id=str(ids["inv_issued"]),
                body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409

    async def test_order_with_issued_invoice_returns_409(self, seeded_db, monkeypatch):
        """複核 N1：O5 已有 issued 發票，對其 voided 舊發票重開必須 409——
        lease 只擋同時飛的請求，這條 gate 擋「重開成功後再按一次」的雙開票。"""
        db, ids = seeded_db
        smilepay = _mock_smilepay(monkeypatch, resp={"Status": "0"})
        with pytest.raises(HTTPException) as exc:
            await admin_router.reissue_invoice(
                invoice_id=str(ids["inv_o5_voided"]),
                body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409
        smilepay.issue_invoice.assert_not_awaited()  # 完全沒打 SmilePay
        # lease 已釋放，未卡死後續（issued 那張作廢後）的合法重開
        src = await db.invoices.find_one({"_id": ids["inv_o5_voided"]})
        assert src.get("reissue_claimed_until") is None

    async def test_not_found_returns_404(self, seeded_db):
        db, _ids = seeded_db
        with pytest.raises(HTTPException) as exc:
            await admin_router.reissue_invoice(
                invoice_id=str(ObjectId()),
                body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 404

    async def test_order_missing_value_error_maps_to_404(self, seeded_db):
        db, ids = seeded_db
        await db.orders.delete_one({"merchant_order_no": "O2"})
        with pytest.raises(HTTPException) as exc:
            await admin_router.reissue_invoice(
                invoice_id=str(ids["inv_voided_new"]),
                body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 404

    def test_corrected_buyer_company_missing_tax_id_rejected(self):
        with pytest.raises(ValidationError):
            admin_router.CorrectedBuyerModel(invoice_type="company", company_name="X")

    def test_corrected_buyer_invalid_carrier_format_rejected(self):
        with pytest.raises(ValidationError):
            admin_router.CorrectedBuyerModel(invoice_type="personal", carrier_num="bad-format")

    async def test_conflict_when_already_being_reissued_returns_409(self, seeded_db):
        """finding #2：雙擊/兩個 admin 併發重開同一張——第二個請求撞到還沒過期的
        reissue lease，必須被擋下回 409，不能各自算出不同 R{n} 都送出成功
        （一張舊發票變出兩張真發票）。"""
        db, ids = seeded_db
        await db.invoices.update_one(
            {"_id": ids["inv_voided_new"]},
            {"$set": {"reissue_claimed_until": time.time() + 60}},
        )

        with pytest.raises(HTTPException) as exc:
            await admin_router.reissue_invoice(
                invoice_id=str(ids["inv_voided_new"]),
                body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409

        # 沒有第二筆新 invoice 被建立
        siblings = await db.invoices.count_documents({"order_no": "O2"})
        assert siblings == 2

    async def test_duplicate_key_error_after_retries_maps_to_409(self, seeded_db, monkeypatch):
        """finding #5：next_reissue_seq 撞號重算一次後仍失敗（極端併發）要回 409，
        不可讓 DuplicateKeyError 原樣往上竄變成 500。"""
        db, ids = seeded_db
        from src.database.repositories.invoice_repo import InvoiceRepository as RealInvoiceRepo
        monkeypatch.setattr(RealInvoiceRepo, "create", AsyncMock(side_effect=DuplicateKeyError("dup data_id")))

        with pytest.raises(HTTPException) as exc:
            await admin_router.reissue_invoice(
                invoice_id=str(ids["inv_voided_new"]),
                body=admin_router.ReissueInvoiceRequest(corrected_buyer=None),
                http_request=FakeRequest(), admin=ADMIN, db=db,
            )
        assert exc.value.status_code == 409

        # 搶佔要被釋放，不可卡死之後的重開嘗試
        inv = await db.invoices.find_one({"_id": ids["inv_voided_new"]})
        assert inv["reissue_claimed_until"] is None
