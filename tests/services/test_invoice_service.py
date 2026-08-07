"""InvoiceService（SmilePay 電子發票）單元測試。

比照 test_renewal_service.py 的形狀：monkeypatch repo/service，聚焦業務規則
（對映/分類/lease/sweep/降級/跨期），HTTP 一律 mock，不打真 API。

`FakeCollection` 是一個極簡的 in-memory Mongo 替身（支援 find_one_and_update 的
$setOnInsert/$set、find 的 $or/$lte/$lt/$in/$nin/$ne、data_id unique 檢查），
讓 InvoiceRepository 的 lease/sweep 查詢邏輯可以在不連真 Mongo 的情況下被真正跑過，
而不只是斷言 mock 的呼叫參數。
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")
os.environ.setdefault("SMILEPAY_GRVC", "SEI1004730")
os.environ.setdefault("SMILEPAY_VERIFY_KEY", "7C623AEFC6C2AEB7F11047CD29B50F4E")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

from src.database.repositories.invoice_repo import InvoiceRepository  # noqa: E402
from src.services import invoice_service as isvc  # noqa: E402
from src.utils.time_utils import get_utc_timestamp  # noqa: E402


# ── Fake Mongo double ────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **kw):
        return self

    async def to_list(self, length=None):
        return self.docs[:length] if length else list(self.docs)

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _match(doc, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict) and any(str(op).startswith("$") for op in v.keys()):
            dv = doc.get(k)
            for op, val in v.items():
                if op == "$lte" and not (dv is not None and dv <= val):
                    return False
                if op == "$lt" and not (dv is not None and dv < val):
                    return False
                if op == "$in" and dv not in val:
                    return False
                if op == "$nin" and dv in val:
                    return False
                if op == "$ne" and dv == val:
                    return False
            continue
        if doc.get(k) != v:
            return False
    return True


class FakeCollection:
    def __init__(self):
        self.docs = {}

    async def create_index(self, *a, **kw):
        return None

    async def insert_one(self, doc):
        doc = dict(doc)
        _id = doc.get("_id") or ObjectId()
        doc["_id"] = _id
        if "data_id" in doc and any(d.get("data_id") == doc["data_id"] for d in self.docs.values()):
            raise DuplicateKeyError("dup data_id")
        self.docs[_id] = doc
        return SimpleNamespace(inserted_id=_id)

    async def find_one(self, query):
        for d in self.docs.values():
            if _match(d, query):
                return dict(d)
        return None

    @staticmethod
    def _apply(doc, update, is_insert=False):
        if is_insert and "$setOnInsert" in update:
            doc.update(update["$setOnInsert"])
        if "$set" in update:
            doc.update(update["$set"])

    async def find_one_and_update(self, query, update, upsert=False, return_document=True):
        for d in self.docs.values():
            if _match(d, query):
                self._apply(d, update)
                return dict(d)
        if upsert:
            base = {k: v for k, v in query.items() if not k.startswith("$") and not isinstance(v, dict)}
            self._apply(base, update, is_insert=True)
            _id = base.get("_id") or ObjectId()
            base["_id"] = _id
            self.docs[_id] = base
            return dict(base)
        return None

    async def update_one(self, query, update):
        for d in self.docs.values():
            if _match(d, query):
                self._apply(d, update)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)

    def find(self, query):
        return FakeCursor([dict(d) for d in self.docs.values() if _match(d, query)])


def _repo():
    db = MagicMock()
    db.invoices = FakeCollection()
    return InvoiceRepository(db), db


# ── classify_invoice_error ───────────────────────────────────────────────────

class TestClassify:
    def test_transient(self):
        for code in ("-10046", "-10071", "-9999"):
            assert isvc.classify_invoice_error(code) == "transient"

    def test_carrier_bad(self):
        for code in ("-10052", "-10053", "-10056", "-10057", "-10058"):
            assert isvc.classify_invoice_error(code) == "carrier_bad"

    def test_buyer_bad(self):
        for code in ("-10021", "-10023", "-10025"):
            assert isvc.classify_invoice_error(code) == "buyer_bad"

    def test_unknown_fallback(self):
        assert isvc.classify_invoice_error("-10061") == "unknown"
        assert isvc.classify_invoice_error(None) == "unknown"
        assert isvc.classify_invoice_error("0") == "unknown"  # 成功碼另外處理，不落分類表


# ── build_invoice_fields（設計 §5 對映表）───────────────────────────────────

def _order(**over):
    base = {
        "merchant_order_no": "SLSUB1234567890", "type": "subscription",
        "tier": "pro", "billing_cycle": "monthly", "amount_twd": 999,
    }
    base.update(over)
    return base


class TestBuildInvoiceFields:
    def test_b2c_no_carrier(self):
        f = isvc.build_invoice_fields(_order(), {"invoice_type": "personal"},
                                       {"email": "foo.bar@example.com"}, data_id="D1")
        assert f["Buyer_id"] is None if "Buyer_id" in f else "Buyer_id" not in f
        assert "CarrierType" not in f
        assert f["Name"] == "foobar"  # email local-part 去符號 fallback
        assert f["ALLAmount"] == "999" and f["Amount"] == "999"
        assert f["Description"] == "SoundLite Pro方案(月繳)"

    def test_b2c_with_valid_carrier(self):
        buyer = {"invoice_type": "personal", "carrier_num": "/AB12345"}
        f = isvc.build_invoice_fields(_order(), buyer, {"email": "a@b.com"}, data_id="D2")
        assert f["CarrierType"] == "3J0002"
        assert f["CarrierID"] == "/AB12345" == f["CarrierID2"]

    def test_b2c_invalid_carrier_raises_carrier_bad(self):
        buyer = {"invoice_type": "personal", "carrier_num": "NOTVALID"}
        with pytest.raises(isvc.InvoiceFieldError) as ei:
            isvc.build_invoice_fields(_order(), buyer, {"email": "a@b.com"}, data_id="D3")
        assert ei.value.kind == "carrier_bad"

    def test_b2b_valid(self):
        buyer = {"invoice_type": "company", "company_tax_id": "12345678", "company_name": "測試公司"}
        f = isvc.build_invoice_fields(_order(), buyer, {"email": "a@b.com"}, data_id="D4")
        assert f["Buyer_id"] == "12345678"
        assert f["CompanyName"] == "測試公司"
        assert f["UnitTAX"] == "Y"
        assert "Name" not in f and "CarrierType" not in f

    def test_b2b_invalid_tax_id_raises_buyer_bad(self):
        buyer = {"invoice_type": "company", "company_tax_id": "123", "company_name": "X"}
        with pytest.raises(isvc.InvoiceFieldError) as ei:
            isvc.build_invoice_fields(_order(), buyer, {"email": "a@b.com"}, data_id="D5")
        assert ei.value.kind == "buyer_bad"

    def test_b2b_missing_company_name_raises_buyer_bad(self):
        buyer = {"invoice_type": "company", "company_tax_id": "12345678", "company_name": ""}
        with pytest.raises(isvc.InvoiceFieldError) as ei:
            isvc.build_invoice_fields(_order(), buyer, {"email": "a@b.com"}, data_id="D6")
        assert ei.value.kind == "buyer_bad"

    def test_extra_quota_uses_label_and_quantity(self):
        order = _order(type="extra_quota", quantity=2, unit_price_twd=39, amount_twd=78,
                        label="60 分鐘轉錄額度")
        f = isvc.build_invoice_fields(order, {"invoice_type": "personal"}, {"email": "a@b.com"}, data_id="D7")
        assert f["Description"] == "60 分鐘轉錄額度"
        assert f["Quantity"] == "2" and f["UnitPrice"] == "39" and f["Amount"] == "78"

    def test_amount_mismatch_raises_calc_error(self):
        order = _order(type="extra_quota", quantity=2, unit_price_twd=39, amount_twd=999)  # 應為 78
        with pytest.raises(isvc.InvoiceFieldError) as ei:
            isvc.build_invoice_fields(order, {"invoice_type": "personal"}, {"email": "a@b.com"}, data_id="D8")
        assert ei.value.kind == "calc_error"

    def test_visa_last4_passthrough(self):
        f = isvc.build_invoice_fields(_order(card_last4="1234"), {"invoice_type": "personal"},
                                       {"email": "a@b.com"}, data_id="D9")
        assert f["Visa_Last4"] == "1234"


# ── snapshot builders（設計 §3.2 key 對映）───────────────────────────────────

class TestSnapshotBuilders:
    def test_from_request_personal(self):
        req = SimpleNamespace(invoice_type="personal", carrier_type="1", carrier_num="/AB12345",
                               company_tax_id=None, company_name=None)
        snap = isvc.build_invoice_snapshot_from_request(req)
        assert snap == {
            "invoice_type": "personal", "carrier_type": "1", "carrier_num": "/AB12345",
            "company_tax_id": None, "company_name": None,
        }

    def test_from_request_none_when_no_invoice_type(self):
        req = SimpleNamespace(invoice_type=None, carrier_type=None, carrier_num=None,
                               company_tax_id=None, company_name=None)
        assert isvc.build_invoice_snapshot_from_request(req) is None

    def test_from_user_invoice_info_maps_type_key(self):
        info = {"type": "company", "company_tax_id": "12345678", "company_name": "X"}
        snap = isvc.build_invoice_snapshot_from_user_invoice_info(info)
        assert snap["invoice_type"] == "company"  # 鍵已從 `type` 對映成 `invoice_type`
        assert snap["company_tax_id"] == "12345678"

    def test_from_user_invoice_info_empty(self):
        assert isvc.build_invoice_snapshot_from_user_invoice_info(None) is None
        assert isvc.build_invoice_snapshot_from_user_invoice_info({}) is None

    def test_resolve_prefers_order_snapshot(self):
        order = {"invoice_snapshot": {"invoice_type": "personal", "carrier_num": None,
                                       "carrier_type": None, "company_tax_id": None, "company_name": None}}
        user = {"invoice_info": {"type": "company", "company_tax_id": "12345678", "company_name": "X"}}
        buyer = isvc.resolve_buyer_snapshot(order, user)
        assert buyer["invoice_type"] == "personal"

    def test_resolve_falls_back_to_user_invoice_info(self):
        order = {}  # 既有 paid 訂單無 snapshot
        user = {"invoice_info": {"type": "company", "company_tax_id": "12345678", "company_name": "X"}}
        buyer = isvc.resolve_buyer_snapshot(order, user)
        assert buyer["invoice_type"] == "company" and buyer["company_tax_id"] == "12345678"

    def test_resolve_defaults_to_personal_no_carrier(self):
        buyer = isvc.resolve_buyer_snapshot({}, None)
        assert buyer["invoice_type"] == "personal" and buyer["carrier_num"] is None


# ── lease 搶佔與釋放 + upsert_initial 冪等 ────────────────────────────────────

class TestLease:
    async def test_upsert_initial_idempotent_on_data_id(self):
        repo, _ = _repo()
        buyer = {"invoice_type": "personal"}
        d1 = await repo.upsert_initial(order_no="O1", user_id="u1", data_id="SL-O1", buyer=buyer,
                                        amount_twd=100, deadline_at=get_utc_timestamp() + 1000)
        d2 = await repo.upsert_initial(order_no="O1", user_id="u1", data_id="SL-O1", buyer=buyer,
                                        amount_twd=100, deadline_at=get_utc_timestamp() + 999999)
        assert d1["_id"] == d2["_id"]
        assert d2["deadline_at"] == d1["deadline_at"]  # 重入不覆蓋（$setOnInsert）

    async def test_claim_succeeds_when_unclaimed(self):
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "pending", "buyer": {}, "amount_twd": 100})
        claimed = await repo.claim_for_processing(doc["_id"])
        assert claimed is not None
        assert claimed["claimed_until"] > get_utc_timestamp()

    async def test_second_claim_blocked_while_leased(self):
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "pending", "buyer": {}, "amount_twd": 100})
        first = await repo.claim_for_processing(doc["_id"])
        assert first is not None
        second = await repo.claim_for_processing(doc["_id"])
        assert second is None  # 另一 process 正在處理

    async def test_claim_available_again_after_lease_expires(self):
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "pending", "buyer": {}, "amount_twd": 100})
        await repo.claim_for_processing(doc["_id"], lease_seconds=-10)  # 立刻視為過期
        again = await repo.claim_for_processing(doc["_id"])
        assert again is not None

    async def test_release_clears_lease(self):
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "pending", "buyer": {}, "amount_twd": 100})
        await repo.claim_for_processing(doc["_id"])
        await repo.release_claim(doc["_id"])
        again = await repo.claim_for_processing(doc["_id"])
        assert again is not None

    async def test_claim_rejects_terminal_status(self):
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "issued", "buyer": {}, "amount_twd": 100})
        assert await repo.claim_for_processing(doc["_id"]) is None


# ── sweep 撈單：next_retry_at=null 防守 + deadline 告警獨立性 + 跨期 gate ──────

class TestRepoSweepQueries:
    async def test_iter_due_for_retry_includes_null_next_retry_at(self):
        repo, _ = _repo()
        now = get_utc_timestamp()
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "pending",
                            "buyer": {}, "amount_twd": 1, "next_retry_at": None})
        await repo.create({"order_no": "O2", "user_id": "u1", "data_id": "d2", "status": "failed",
                            "buyer": {}, "amount_twd": 1, "next_retry_at": now - 10})
        await repo.create({"order_no": "O3", "user_id": "u1", "data_id": "d3", "status": "failed",
                            "buyer": {}, "amount_twd": 1, "next_retry_at": now + 999999})
        await repo.create({"order_no": "O4", "user_id": "u1", "data_id": "d4", "status": "issued",
                            "buyer": {}, "amount_twd": 1, "next_retry_at": now - 10})
        due = [d async for d in repo.iter_due_for_retry(now)]
        order_nos = {d["order_no"] for d in due}
        assert order_nos == {"O1", "O2"}  # null 防守 + 到期者；未到期與 issued 排除

    async def test_iter_deadline_warnings_excludes_issued_and_alerted(self):
        repo, _ = _repo()
        now = get_utc_timestamp()
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "pending",
                            "buyer": {}, "amount_twd": 1, "deadline_at": now + 100})
        await repo.create({"order_no": "O2", "user_id": "u1", "data_id": "d2", "status": "issued",
                            "buyer": {}, "amount_twd": 1, "deadline_at": now + 100})
        await repo.create({"order_no": "O3", "user_id": "u1", "data_id": "d3", "status": "pending",
                            "buyer": {}, "amount_twd": 1, "deadline_at": now + 100, "deadline_alerted": True})
        warned = [d async for d in repo.iter_deadline_warnings(now, 6 * 3600)]
        assert [d["order_no"] for d in warned] == ["O1"]


class TestSweep:
    """run_invoice_retry_sweep：monkeypatch InvoiceRepository/OrderRepository/UserRepository
    與 _attempt_issue，聚焦排程邏輯本身（撈單/跨期/告警），不重複測 _attempt_issue 內部行為。
    """

    def _patch(self, monkeypatch, *, orders=None):
        repo, _ = _repo()
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)

        order_repo = MagicMock()
        order_map = orders or {}
        order_repo.get_by_order_no = AsyncMock(side_effect=lambda no: order_map.get(no))
        monkeypatch.setattr(isvc, "OrderRepository", lambda db: order_repo)

        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value={"email": "a@b.com"})
        monkeypatch.setattr(isvc, "UserRepository", lambda db: user_repo)

        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        alert = MagicMock()
        monkeypatch.setattr(isvc, "_capture_invoice_alert", alert)
        return repo, order_repo, attempt, alert

    async def test_deadline_alert_independent_of_retry_eligibility(self, monkeypatch):
        now = get_utc_timestamp()
        repo, order_repo, attempt, alert = self._patch(monkeypatch)
        # next_retry_at 還很久（不該被撈去重試），但 deadline 快到了（該告警）
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "pending",
                            "buyer": {}, "amount_twd": 1,
                            "next_retry_at": now + 999999, "deadline_at": now + 100,
                            "first_attempt_at": now})
        counts = await isvc.run_invoice_retry_sweep(MagicMock())
        assert counts["deadline_warned"] == 1
        assert counts["retried"] == 0  # 未到期不重試——deadline 告警與 retry 條件互相獨立
        alert.assert_called_once()

    async def test_deadline_alert_only_fires_once(self, monkeypatch):
        now = get_utc_timestamp()
        repo, order_repo, attempt, alert = self._patch(monkeypatch)
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "pending",
                            "buyer": {}, "amount_twd": 1,
                            "next_retry_at": now + 999999, "deadline_at": now + 100,
                            "first_attempt_at": now})
        await isvc.run_invoice_retry_sweep(MagicMock())
        await isvc.run_invoice_retry_sweep(MagicMock())
        assert alert.call_count == 1  # mark_deadline_alerted 防第二輪重複告警

    async def test_cross_period_blocks_retry_and_alerts(self, monkeypatch):
        now = get_utc_timestamp()
        far_past = now - 200 * 86400  # 保證跨過雙月期別邊界
        repo, order_repo, attempt, alert = self._patch(monkeypatch)
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "pending",
                            "buyer": {}, "amount_twd": 1,
                            "next_retry_at": now - 10, "deadline_at": now + 999999,
                            "first_attempt_at": far_past})
        counts = await isvc.run_invoice_retry_sweep(MagicMock())
        assert counts["cross_period_blocked"] == 1
        attempt.assert_not_awaited()  # 跨期不重試，轉 needs_manual
        assert repo.collection.docs and next(iter(repo.collection.docs.values()))["status"] == "needs_manual"

    async def test_same_period_retries_via_attempt_issue(self, monkeypatch):
        now = get_utc_timestamp()
        order = {"merchant_order_no": "O1"}
        repo, order_repo, attempt, alert = self._patch(monkeypatch, orders={"O1": order})
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "failed",
                            "buyer": {}, "amount_twd": 1,
                            "next_retry_at": now - 10, "deadline_at": now + 999999,
                            "first_attempt_at": now})
        counts = await isvc.run_invoice_retry_sweep(MagicMock())
        assert counts["retried"] == 1
        attempt.assert_awaited_once()

    async def test_missing_order_is_skipped_not_crashed(self, monkeypatch):
        now = get_utc_timestamp()
        repo, order_repo, attempt, alert = self._patch(monkeypatch, orders={})
        await repo.create({"order_no": "GONE", "user_id": "u1", "data_id": "d1", "status": "failed",
                            "buyer": {}, "amount_twd": 1,
                            "next_retry_at": now - 10, "deadline_at": now + 999999,
                            "first_attempt_at": now})
        counts = await isvc.run_invoice_retry_sweep(MagicMock())
        assert counts["order_missing"] == 1
        attempt.assert_not_awaited()

    async def test_poison_doc_does_not_stall_the_whole_sweep(self, monkeypatch):
        """finding #3 回歸測試：iter_due_for_retry 沒有 sort，若一筆炸掉的 doc 不推進
        next_retry_at，它會每輪都排最前面、擋住後面所有筆。這裡讓第一筆 order_repo 查詢
        直接丟例外（模擬任何一步炸掉），驗證第二筆仍被處理，且第一筆被標記 failed 並排入
        下一個 backoff（不再卡在最前面）。
        """
        now = get_utc_timestamp()
        good_order = {"merchant_order_no": "O2"}
        repo, order_repo, attempt, alert = self._patch(monkeypatch, orders={"O2": good_order})
        order_repo.get_by_order_no = AsyncMock(side_effect=[RuntimeError("db hiccup"), good_order])
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "d1", "status": "failed",
                            "buyer": {}, "amount_twd": 1, "attempts": 0,
                            "next_retry_at": now - 10, "deadline_at": now + 999999,
                            "first_attempt_at": now})
        await repo.create({"order_no": "O2", "user_id": "u1", "data_id": "d2", "status": "failed",
                            "buyer": {}, "amount_twd": 1,
                            "next_retry_at": now - 10, "deadline_at": now + 999999,
                            "first_attempt_at": now})
        counts = await isvc.run_invoice_retry_sweep(MagicMock())
        assert counts["errored"] == 1
        assert counts["retried"] == 1  # 第二筆仍正常處理，沒被第一筆拖垮
        attempt.assert_awaited_once()

        poisoned = await repo.get_by_id(next(d["_id"] for d in repo.collection.docs.values() if d["order_no"] == "O1"))
        assert poisoned["status"] == "failed"
        assert poisoned["attempts"] == 1
        assert poisoned["next_retry_at"] > now  # 已推進到下一個 backoff，不再排最前面
        assert poisoned["claimed_until"] is None


# ── _attempt_issue：分類分流 + 降級重開 + -10072 + 網路例外 ───────────────────

class TestAttemptIssue:
    def _svc(self, monkeypatch, resp=None, side_effect=None):
        svc = MagicMock()
        if side_effect is not None:
            svc.issue_invoice = AsyncMock(side_effect=side_effect)
        else:
            svc.issue_invoice = AsyncMock(return_value=resp or {"Status": "0", "InvoiceNumber": "AB12345678",
                                                                 "RandomNumber": "1234", "InvoiceType": "B2C"})
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        return svc

    async def _doc(self, repo, **over):
        base = {"order_no": "O1", "user_id": "u1", "data_id": "SL-O1", "status": "pending",
                "buyer": {"invoice_type": "personal"}, "amount_twd": 999, "attempts": 0}
        base.update(over)
        return await repo.create(base)

    async def test_success_marks_issued(self, monkeypatch):
        repo, _ = _repo()
        self._svc(monkeypatch)
        doc = await self._doc(repo)
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "issued" and saved["invoice_number"] == "AB12345678"
        assert saved["claimed_until"] is None

    async def test_claim_missed_skips_call(self, monkeypatch):
        repo, _ = _repo()
        svc = self._svc(monkeypatch)
        doc = await self._doc(repo, status="issued")  # 已終態，claim 拿不到
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        svc.issue_invoice.assert_not_awaited()

    async def test_field_error_short_circuits_before_api_call(self, monkeypatch):
        repo, _ = _repo()
        svc = self._svc(monkeypatch)
        doc = await self._doc(repo, buyer={"invoice_type": "company", "company_tax_id": "bad"})
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        svc.issue_invoice.assert_not_awaited()
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "needs_manual"

    async def test_duplicate_data_id_needs_manual(self, monkeypatch):
        repo, _ = _repo()
        self._svc(monkeypatch, resp={"Status": "-10072", "Desc": "dup"})
        doc = await self._doc(repo)
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "needs_manual"
        assert saved["last_error"]["status"] == "-10072"

    async def test_transient_sets_backoff_and_stays_retryable(self, monkeypatch):
        repo, _ = _repo()
        self._svc(monkeypatch, resp={"Status": "-10071", "Desc": "no track"})
        doc = await self._doc(repo, attempts=0)
        before = get_utc_timestamp()
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "failed"
        assert saved["attempts"] == 1
        assert saved["next_retry_at"] - before == pytest.approx(5 * 60, abs=5)  # 第一次 5 分鐘
        assert saved["claimed_until"] is None

    async def test_buyer_bad_needs_manual_and_alerts(self, monkeypatch):
        repo, _ = _repo()
        self._svc(monkeypatch, resp={"Status": "-10021", "Desc": "統編錯誤"})
        alert = MagicMock()
        monkeypatch.setattr(isvc, "_capture_invoice_alert", alert)
        doc = await self._doc(repo)
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "needs_manual"
        alert.assert_called_once()

    async def test_carrier_bad_degrades_and_reopens_as_b2c(self, monkeypatch):
        repo, _ = _repo()
        svc = MagicMock()
        # 第一次回載具錯，降級重開後第二次成功
        svc.issue_invoice = AsyncMock(side_effect=[
            {"Status": "-10052", "Desc": "carrier bad"},
            {"Status": "0", "InvoiceNumber": "AB00000001", "RandomNumber": "5678", "InvoiceType": "B2C"},
        ])
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        doc = await self._doc(repo, buyer={"invoice_type": "personal", "carrier_num": "/AB12345"})
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        assert svc.issue_invoice.await_count == 2
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "issued"
        assert saved["data_id"] == "SL-O1-B2C"  # 換了新 data_id
        assert saved["buyer"]["carrier_num"] is None  # 降級為無載具

    async def test_carrier_bad_after_degrade_falls_back_needs_manual(self, monkeypatch):
        # 病態情況：降級後仍回載具相關碼 → 不可再遞迴降級，保守 needs_manual
        repo, _ = _repo()
        svc = MagicMock()
        svc.issue_invoice = AsyncMock(return_value={"Status": "-10052", "Desc": "still bad"})
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        doc = await self._doc(repo, buyer={"invoice_type": "personal", "carrier_num": "/AB12345"})
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        assert svc.issue_invoice.await_count == 2
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "needs_manual"

    async def test_local_carrier_format_error_also_degrades_not_needs_manual(self, monkeypatch):
        """finding #2 回歸測試：本地 sanity check（build_invoice_fields）抓到的載具格式錯，
        要跟 SmilePay 回 -10056 一樣走自動降級，不是就地 needs_manual——本地檢查根本沒送出
        API 呼叫，第一次 issue_invoice 呼叫就該是降級後、不帶載具的版本。
        """
        repo, _ = _repo()
        svc = MagicMock()
        svc.issue_invoice = AsyncMock(return_value={
            "Status": "0", "InvoiceNumber": "AB00000002", "RandomNumber": "9999", "InvoiceType": "B2C",
        })
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        # carrier_num 本地格式就不合法（"BAD" 不符 /[0-9A-Z+\-.]{7}），build_invoice_fields
        # 會直接拋 InvoiceFieldError("carrier_bad", ...)，不曾送出 API。
        doc = await self._doc(repo, buyer={"invoice_type": "personal", "carrier_num": "BAD"})
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        # 只呼叫一次 API：本地檢查失敗後直接降級重試，降級後的欄位合法可一次成功
        assert svc.issue_invoice.await_count == 1
        sent_fields = svc.issue_invoice.await_args.kwargs
        assert "CarrierType" not in sent_fields  # 降級後才送出的請求不帶載具
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "issued"
        assert saved["data_id"] == "SL-O1-B2C"
        assert saved["buyer"]["carrier_num"] is None

    async def test_company_carrier_bad_from_api_does_not_degrade(self, monkeypatch):
        """finding #7 護欄：company（B2B）買受人若從 API 收到載具類錯誤碼，不可自動降級成
        無統編 B2C（企業要統編抵稅）——直接 needs_manual。正常情況 B2B 請求根本不帶
        CarrierType，這裡模擬 API 端異常回應，驗證保守防線確實生效。
        """
        repo, _ = _repo()
        svc = MagicMock()
        svc.issue_invoice = AsyncMock(return_value={"Status": "-10052", "Desc": "carrier bad"})
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        doc = await self._doc(repo, buyer={"invoice_type": "company", "company_tax_id": "12345678",
                                           "company_name": "測試公司"})
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        assert svc.issue_invoice.await_count == 1  # 沒有降級重試的第二次呼叫
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "needs_manual"
        assert saved["buyer"]["invoice_type"] == "company"  # 未被改成 personal

    async def test_read_timeout_needs_manual(self, monkeypatch):
        repo, _ = _repo()
        self._svc(monkeypatch, side_effect=httpx.ReadTimeout("timeout"))
        doc = await self._doc(repo)
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "needs_manual"
        assert saved["last_error"]["status"] == "response_lost"

    async def test_connect_error_fails_and_retries(self, monkeypatch):
        repo, _ = _repo()
        self._svc(monkeypatch, side_effect=httpx.ConnectError("boom"))
        doc = await self._doc(repo)
        await isvc._attempt_issue(MagicMock(), repo, doc, _order(), {"email": "a@b.com"})
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "failed"
        assert saved["last_error"]["status"] == "connect_error"
        assert saved["next_retry_at"] is not None


# ── issue_for_order：settle 重入防護第一層 ───────────────────────────────────

class TestIssueForOrder:
    async def test_skips_when_already_issued(self, monkeypatch):
        called = {"upsert": False}

        repo = MagicMock()
        repo.get_active_by_order_no = AsyncMock(return_value={"status": "issued"})

        async def _upsert(**kw):
            called["upsert"] = True

        repo.upsert_initial = _upsert
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        monkeypatch.setattr(isvc, "UserRepository", lambda db: MagicMock(get_by_id=AsyncMock(return_value={"email": "a@b.com"})))
        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        await isvc.issue_for_order(MagicMock(), _order())
        assert called["upsert"] is False
        attempt.assert_not_awaited()

    async def test_builds_doc_and_attempts_when_none_exists(self, monkeypatch):
        repo = MagicMock()
        repo.get_active_by_order_no = AsyncMock(return_value=None)
        repo.upsert_initial = AsyncMock(return_value={"_id": "iid1"})
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        monkeypatch.setattr(isvc, "UserRepository", lambda db: MagicMock(get_by_id=AsyncMock(return_value={"email": "a@b.com"})))
        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        await isvc.issue_for_order(MagicMock(), _order())
        attempt.assert_awaited_once()
        kwargs = repo.upsert_initial.await_args.kwargs
        assert kwargs["data_id"] == "SL-SLSUB1234567890"

    async def test_reuses_existing_non_voided_doc_instead_of_upserting(self, monkeypatch):
        """finding #4 回歸測試：重入（settle 重入或 sweep 二次觸發）不可用固定 data_id
        重新 upsert——若該 doc 已被降級改過 data_id，會插出第二筆並在下次降級時撞
        unique index。重入時必須沿用 get_active_by_order_no 找到的既有 doc（原樣，含
        它可能已經被改過的 data_id）。
        """
        existing_doc = {"_id": "iid-existing", "status": "pending", "data_id": "SL-SLSUB1234567890-B2C"}
        repo = MagicMock()
        repo.get_active_by_order_no = AsyncMock(return_value=existing_doc)
        repo.upsert_initial = AsyncMock(side_effect=AssertionError("不該呼叫 upsert_initial"))
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        monkeypatch.setattr(isvc, "UserRepository", lambda db: MagicMock(get_by_id=AsyncMock(return_value={"email": "a@b.com"})))
        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        await isvc.issue_for_order(MagicMock(), _order())
        repo.upsert_initial.assert_not_called()
        attempt.assert_awaited_once()
        # 傳給 _attempt_issue 的必須是原本那顆 doc（保留其已被改過的 data_id）
        passed_doc = attempt.await_args.args[2]
        assert passed_doc["data_id"] == "SL-SLSUB1234567890-B2C"

    async def test_deadline_at_uses_order_paid_at_not_issue_time(self, monkeypatch):
        """finding #9：deadline 要用 order.paid_at 當基準，不是開票嘗試當下——否則補開
        舊單（sweep 重試 issue_for_order）算出的 deadline 會被無限往後推，告警永不觸發。
        """
        repo = MagicMock()
        repo.get_active_by_order_no = AsyncMock(return_value=None)
        repo.upsert_initial = AsyncMock(return_value={"_id": "iid1"})
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        monkeypatch.setattr(isvc, "UserRepository", lambda db: MagicMock(get_by_id=AsyncMock(return_value={"email": "a@b.com"})))
        monkeypatch.setattr(isvc, "_attempt_issue", AsyncMock())

        paid_at = get_utc_timestamp() - 10000  # 早於「現在」很久（模擬補開舊單）
        await isvc.issue_for_order(MagicMock(), _order(paid_at=paid_at))
        kwargs = repo.upsert_initial.await_args.kwargs
        assert kwargs["deadline_at"] == pytest.approx(paid_at + isvc._DEADLINE_SECONDS_B2C, abs=2)


# ── void / reissue ───────────────────────────────────────────────────────────

class TestVoidAndReissue:
    async def test_void_success(self, monkeypatch):
        svc = MagicMock()
        svc.void_invoice = AsyncMock(return_value={"Status": "0"})
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "issued", "buyer": {}, "amount_twd": 1,
                                  "invoice_number": "AB1", "invoice_date": "2026/08/07"})
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        result = await isvc.void_invoice_for(MagicMock(), doc, "測試退款", "admin1")
        assert result["success"] is True
        saved = await repo.get_by_id(doc["_id"])
        assert saved["status"] == "voided"

    async def test_void_passes_through_nowstatus_error(self, monkeypatch):
        svc = MagicMock()
        svc.void_invoice = AsyncMock(return_value={"Status": "-2008", "Desc": "bad state", "Nowstatus": "3"})
        monkeypatch.setattr(isvc, "get_smilepay_service", lambda: svc)
        repo, _ = _repo()
        doc = await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1",
                                  "status": "issued", "buyer": {}, "amount_twd": 1,
                                  "invoice_number": "AB1", "invoice_date": "2026/08/07"})
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        result = await isvc.void_invoice_for(MagicMock(), doc, "測試退款", "admin1")
        assert result["success"] is False and result["now_status"] == "3"

    async def test_reissue_rejects_wrong_status(self):
        with pytest.raises(ValueError):
            await isvc.reissue(MagicMock(), {"status": "issued"})

    async def test_reissue_rejects_when_order_not_found(self, monkeypatch):
        """finding #6 回歸測試：order 查無時必須拒絕，不可 `order or {}` 續跑——那會用
        amount_twd=0 組出零元發票送 SmilePay。且不該有任何新 invoice doc 被建立。
        """
        repo, _ = _repo()
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        order_repo = MagicMock()
        order_repo.get_by_order_no = AsyncMock(return_value=None)
        monkeypatch.setattr(isvc, "OrderRepository", lambda db: order_repo)
        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        invoice = {"status": "voided", "order_no": "GONE", "user_id": "u1", "amount_twd": 1, "buyer": {}}
        with pytest.raises(ValueError):
            await isvc.reissue(MagicMock(), invoice, admin_id="admin1")
        attempt.assert_not_awaited()
        assert repo.collection.docs == {}  # 沒有孤兒 invoice doc 被建立

    async def test_reissue_concurrent_data_id_collision_retries(self, monkeypatch):
        repo, _ = _repo()
        # 預先塞一筆 R1，模擬併發：next_reissue_seq 先回 1（撞號）、重算後回 2（成功）。
        await repo.create({"order_no": "O1", "user_id": "u1", "data_id": "SL-O1-R1",
                            "status": "voided", "buyer": {}, "amount_twd": 1})
        monkeypatch.setattr(repo, "next_reissue_seq", AsyncMock(side_effect=[1, 2]))
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        order_repo = MagicMock()
        order_repo.get_by_order_no = AsyncMock(return_value=_order())
        monkeypatch.setattr(isvc, "OrderRepository", lambda db: order_repo)
        monkeypatch.setattr(isvc, "UserRepository", lambda db: MagicMock(get_by_id=AsyncMock(return_value={"email": "a@b.com"})))
        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        invoice = {"status": "voided", "order_no": "O1", "user_id": "u1", "amount_twd": 1, "buyer": {}}
        result = await isvc.reissue(MagicMock(), invoice, admin_id="admin1")
        assert result["data_id"] == "SL-O1-R2"
        attempt.assert_awaited_once()

    async def test_reissue_with_corrected_buyer_updates_user_invoice_info(self, monkeypatch):
        repo, _ = _repo()
        monkeypatch.setattr(isvc, "InvoiceRepository", lambda db: repo)
        order_repo = MagicMock()
        order_repo.get_by_order_no = AsyncMock(return_value=_order())
        monkeypatch.setattr(isvc, "OrderRepository", lambda db: order_repo)
        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value={"email": "a@b.com"})
        user_repo.update_invoice_info = AsyncMock(return_value=True)
        monkeypatch.setattr(isvc, "UserRepository", lambda db: user_repo)
        attempt = AsyncMock()
        monkeypatch.setattr(isvc, "_attempt_issue", attempt)

        invoice = {"status": "needs_manual", "order_no": "O1", "user_id": "u1", "amount_twd": 1, "buyer": {}}
        corrected = {"invoice_type": "company", "company_tax_id": "12345678", "company_name": "新公司"}
        await isvc.reissue(MagicMock(), invoice, corrected_buyer=corrected, admin_id="admin1")
        user_repo.update_invoice_info.assert_awaited_once()
        saved_info = user_repo.update_invoice_info.await_args.args[1]
        assert saved_info["type"] == "company" and saved_info["company_tax_id"] == "12345678"
