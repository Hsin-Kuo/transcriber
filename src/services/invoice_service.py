"""SmilePay 電子發票業務層。

設計唯一事實來源：docs/INVOICE_SMILEPAY_INTEGRATION_PLAN.md §4.2（+ §5 對映表、
§6 冪等表）；API 細節見 docs/INVOICE_SMILEPAY_API.md。

比照 renewal_service.py 的形狀：module-level 純函數 + 背景 sweep，不用 class。

呼叫鏈：
- OrderSettlement.settle() 白名單 outcome → create_background_task(issue_for_order(...))
- 背景 sweep（periodic_invoice_retry）每 10 分鐘：撈到期重試 + 獨立 deadline 告警 + 跨期 gate
- reissue() / void_invoice_for()：admin 後台（PR-B）呼叫的服務層入口，本 PR 只實作+測試

🔴 Verify_key 絕不可進 log／Sentry breadcrumb（smilepay_service 已確保不進 URL；本檔一律
只 log 業務欄位如 order_no/data_id/status_code，不觸碰 Verify_key）。動到 payment 相關 diff
走 judgment-rubrics §5。
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from pymongo.errors import DuplicateKeyError

from ..database.repositories.invoice_repo import InvoiceRepository
from ..database.repositories.order_repo import OrderRepository
from ..database.repositories.user_repo import UserRepository
from ..utils.smilepay_service import get_smilepay_service
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

log = get_logger(__name__)

# 台北時區（e-invoice 日期/期別一律用台北當地時間；台灣無 DST，固定 +8 即可，
# 比照 utils/time_utils.format_timestamp 的既有慣例，不引入 zoneinfo tz database 依賴）。
_TPE = timezone(timedelta(hours=8))

INVOICE_RETRY_INTERVAL_SECONDS = 600
DEADLINE_WARNING_SECONDS = 6 * 3600
_DEADLINE_SECONDS_B2C = 48 * 3600
_DEADLINE_SECONDS_B2B = 168 * 3600

_TAX_ID_RE = re.compile(r"^\d{8}$")
_CARRIER_RE = re.compile(r"^/[0-9A-Z+\-.]{7}$")

# 錯誤分類表（設計 §4.2）
_TRANSIENT_CODES = {"-10046", "-10071", "-9999"}
_CARRIER_BAD_CODES = {"-10052", "-10053", "-10056", "-10057", "-10058"}
_BUYER_BAD_CODES = {"-10021", "-10023", "-10025"}
_DATA_ID_DUPLICATE = "-10072"

# transient backoff：5min → 30min → 2hr → 之後每 4hr（設計 §4.2）
_BACKOFF_SCHEDULE = (5 * 60, 30 * 60, 2 * 3600)
_BACKOFF_STEADY = 4 * 3600

_TIER_LABELS = {"basic": "Basic", "pro": "Pro"}
_CYCLE_LABELS = {"monthly": "月繳", "yearly": "年繳"}


class InvoiceFieldError(Exception):
    """buyer/金額資料未過開票前 sanity check，不可送 SmilePay（走永久性失敗分流，設計 §3.3.3）。"""

    def __init__(self, kind: str, reason: str):
        self.kind = kind  # "buyer_bad" | "carrier_bad" | "calc_error"
        self.reason = reason
        super().__init__(reason)


# ── 錯誤分類（純函數，比照 renewal_service.classify_failure）───────────────────

def classify_invoice_error(status_code: Optional[str]) -> str:
    """transient | carrier_bad | buyer_bad | unknown。"""
    code = str(status_code) if status_code is not None else ""
    if code in _TRANSIENT_CODES:
        return "transient"
    if code in _CARRIER_BAD_CODES:
        return "carrier_bad"
    if code in _BUYER_BAD_CODES:
        return "buyer_bad"
    return "unknown"


def _next_retry_delay(attempts: int) -> int:
    idx = attempts - 1
    if 0 <= idx < len(_BACKOFF_SCHEDULE):
        return _BACKOFF_SCHEDULE[idx]
    return _BACKOFF_STEADY


def _period_key(ts: float):
    """雙月期別（台灣電子發票報稅期）：(year, 0..5)。用台北當地日期判定。"""
    dt = datetime.fromtimestamp(ts, tz=_TPE)
    return (dt.year, (dt.month - 1) // 2)


def _invoice_date_time(now_ts: float):
    dt = datetime.fromtimestamp(now_ts, tz=_TPE)
    return dt.strftime("%Y/%m/%d"), dt.strftime("%H:%M:%S")


def _deadline_seconds(buyer: Dict[str, Any]) -> int:
    return _DEADLINE_SECONDS_B2B if (buyer or {}).get("invoice_type") == "company" else _DEADLINE_SECONDS_B2C


def _deadline_at(order: Dict[str, Any], buyer: Dict[str, Any], now: float) -> float:
    """deadline 基準用 order.paid_at（付款成功時刻），不是「開票嘗試當下」——否則補開
    舊單（sweep 重試、reissue）算出的 deadline 會被無限往後推，告警永遠不會觸發。
    沒有 paid_at（理論上不會發生）才 fallback 用 now。
    """
    base = order.get("paid_at") or now
    return base + _deadline_seconds(buyer)


# ── 文字清洗（設計 §5：禁 | 與符號，避免打壞明細對齊）──────────────────────────

_SANITIZE_STRIP_RE = re.compile(r"[^\w\s()（）]", re.UNICODE)


def sanitize_item_text(text: Optional[str], max_len: int = 256) -> str:
    """去除符號（含 `|`）、壓縮空白、截長度。`\\w` 在 Python3 unicode 字串下已涵蓋中文字元。"""
    if not text:
        return ""
    cleaned = _SANITIZE_STRIP_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len]


def _b2c_buyer_name(email: Optional[str]) -> str:
    """B2C 買受人姓名：users schema 目前沒有顯示名欄位（純 email 帳號體系），
    直接用 email local-part（去符號、截 30 字、空值 fallback "customer"）。"""
    local = (email or "").split("@")[0]
    return sanitize_item_text(local, 30) or "customer"


def _subscription_description(order: Dict[str, Any]) -> str:
    tier = _TIER_LABELS.get(order.get("tier"), str(order.get("tier") or ""))
    cycle = _CYCLE_LABELS.get(order.get("billing_cycle"), str(order.get("billing_cycle") or ""))
    return sanitize_item_text(f"SoundLite {tier}方案({cycle})", 256)


# ── invoice_snapshot 建構（設計 §3.2；user.invoice_info 的鍵是 `type`，需對映）────

def build_invoice_snapshot_from_request(request_data) -> Optional[Dict[str, Any]]:
    """checkout/升級/加購建單用：request model 欄位已是 snapshot 形狀，直接組。"""
    invoice_type = getattr(request_data, "invoice_type", None)
    if invoice_type not in ("personal", "company"):
        return None
    if invoice_type == "personal":
        return {
            "invoice_type": "personal",
            "carrier_type": getattr(request_data, "carrier_type", None),
            "carrier_num": getattr(request_data, "carrier_num", None),
            "company_tax_id": None,
            "company_name": None,
        }
    return {
        "invoice_type": "company",
        "carrier_type": None,
        "carrier_num": None,
        "company_tax_id": getattr(request_data, "company_tax_id", None),
        "company_name": getattr(request_data, "company_name", None),
    }


def build_invoice_snapshot_from_user_invoice_info(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """update-card / renewal_service 建單用：user.invoice_info 的鍵是 `type`，對映成 `invoice_type`。"""
    info = info or {}
    itype = info.get("type")
    if itype not in ("personal", "company"):
        return None
    if itype == "personal":
        return {
            "invoice_type": "personal",
            "carrier_type": info.get("carrier_type") or None,
            "carrier_num": info.get("carrier_num") or None,
            "company_tax_id": None,
            "company_name": None,
        }
    return {
        "invoice_type": "company",
        "carrier_type": None,
        "carrier_num": None,
        "company_tax_id": info.get("company_tax_id") or None,
        "company_name": info.get("company_name") or None,
    }


def resolve_buyer_snapshot(order: Dict[str, Any], user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """開票用 buyer 來源：order.invoice_snapshot 優先；既有 paid 訂單無 snapshot 時 fallback
    讀 user.invoice_info（同樣經 key 對映）；兩者皆無則視為個人無載具。
    """
    snap = order.get("invoice_snapshot")
    if snap:
        return snap
    mapped = build_invoice_snapshot_from_user_invoice_info((user or {}).get("invoice_info"))
    if mapped:
        return mapped
    return {
        "invoice_type": "personal", "carrier_type": None, "carrier_num": None,
        "company_tax_id": None, "company_name": None,
    }


# ── 開票參數對映（設計 §5）───────────────────────────────────────────────────

def build_invoice_fields(order: Dict[str, Any], buyer: Dict[str, Any], user: Optional[Dict[str, Any]],
                          *, data_id: str) -> Dict[str, Any]:
    """把 order + buyer snapshot 組成送 SmilePay 的欄位。

    開票前 server 端 sanity check（設計 §3.3.3）：統編非 8 碼數字、company 缺抬頭、
    載具格式錯 → 拋 InvoiceFieldError，呼叫端據 `.kind` 走永久性失敗分流，不送 SmilePay。
    """
    buyer = buyer or {}
    user = user or {}
    invoice_type = buyer.get("invoice_type") or "personal"
    email = user.get("email") or ""

    company_tax_id = ""
    company_name = ""
    carrier_num = ""
    if invoice_type == "company":
        company_tax_id = (buyer.get("company_tax_id") or "").strip()
        company_name = sanitize_item_text(buyer.get("company_name"), 30)
        if not _TAX_ID_RE.match(company_tax_id):
            raise InvoiceFieldError("buyer_bad", f"統編格式錯誤：{company_tax_id!r}")
        if not company_name:
            raise InvoiceFieldError("buyer_bad", "公司戶缺少抬頭 company_name")
    else:
        carrier_num = (buyer.get("carrier_num") or "").strip()
        if carrier_num and not _CARRIER_RE.match(carrier_num):
            raise InvoiceFieldError("carrier_bad", f"載具格式錯誤：{carrier_num!r}")

    order_type = order.get("type", "subscription")
    if order_type == "extra_quota":
        description = sanitize_item_text(order.get("label") or "額外額度", 256)
        quantity = int(order.get("quantity") or 1)
        unit_price = int(order.get("unit_price_twd") if order.get("unit_price_twd") is not None else order.get("amount_twd", 0))
    else:
        description = _subscription_description(order)
        quantity = 1
        unit_price = int(order.get("amount_twd", 0))

    amount = quantity * unit_price
    all_amount = int(order.get("amount_twd", 0))
    if amount != all_amount:
        raise InvoiceFieldError("calc_error", f"金額驗算不符：{quantity}x{unit_price}={amount} != {all_amount}")

    invoice_date, invoice_time = _invoice_date_time(get_utc_timestamp())

    fields: Dict[str, Any] = {
        "InvoiceDate": invoice_date,
        "InvoiceTime": invoice_time,
        "Intype": "07",
        "TaxType": "1",
        "DonateMark": "0",
        "data_id": data_id,
        "orderid": str(order.get("merchant_order_no", ""))[:30],
        "Description": description,
        "Quantity": str(quantity),
        "UnitPrice": str(unit_price),
        "Amount": str(amount),
        "ALLAmount": str(all_amount),
        "Email": email,
    }
    card_last4 = order.get("card_last4")
    if card_last4:
        fields["Visa_Last4"] = str(card_last4)

    if invoice_type == "company":
        fields["Buyer_id"] = company_tax_id
        fields["CompanyName"] = company_name
        fields["UnitTAX"] = "Y"
    else:
        fields["Name"] = _b2c_buyer_name(email)
        if carrier_num:
            fields["CarrierType"] = "3J0002"
            fields["CarrierID"] = carrier_num
            fields["CarrierID2"] = carrier_num

    return fields


# ── Sentry alert（比照 order_settlement._capture_refund_alert）────────────────

def _capture_invoice_alert(invoice: Dict[str, Any], kind: str, detail: str) -> None:
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("invoice.issue", kind)
            scope.set_context("invoice", {
                "order_no": invoice.get("order_no"),
                "data_id": invoice.get("data_id"),
                "user_id": invoice.get("user_id"),
                "detail": detail,
            })
            sentry_sdk.capture_message(
                f"發票需人工處理：order={invoice.get('order_no')} kind={kind} detail={detail}",
                level="error",
            )
    except Exception:
        pass


async def _finalize_needs_manual(invoice_repo: InvoiceRepository, invoice: Dict[str, Any], *,
                                  kind: str, desc: str, attempts: Optional[int] = None,
                                  last_error: Optional[Dict[str, Any]] = None) -> None:
    updates: Dict[str, Any] = {
        "status": "needs_manual",
        "claimed_until": None,
        "last_error": last_error or {"status": kind, "desc": desc},
    }
    if attempts is not None:
        updates["attempts"] = attempts
    await invoice_repo.update(invoice["_id"], updates)
    log.error("invoice.issue.needs_manual", order_no=invoice.get("order_no"),
              data_id=invoice.get("data_id"), kind=kind, desc=desc)
    _capture_invoice_alert(invoice, kind, desc)


# ── 開立（單筆嘗試：claim → 呼叫 → 依結果落庫）─────────────────────────────────

async def _attempt_issue(db, invoice_repo: InvoiceRepository, invoice_doc: Dict[str, Any],
                          order: Dict[str, Any], user: Optional[Dict[str, Any]], *, _degraded: bool = False) -> None:
    invoice_id = invoice_doc["_id"]
    claimed = await invoice_repo.claim_for_processing(invoice_id)
    if not claimed:
        log.info("invoice.issue.claim_missed", order_no=invoice_doc.get("order_no"))
        return

    buyer = claimed.get("buyer") or {}
    try:
        fields = build_invoice_fields(order, buyer, user, data_id=claimed["data_id"])
    except InvoiceFieldError as e:
        # 本地 sanity check 抓到的載具格式錯，比照 SmilePay 回 -10056 類的處置：
        # 自動降級（設計 §4.2），不要就地丟 needs_manual（build_invoice_fields 只在
        # invoice_type=personal 分支才會拋 carrier_bad，company 買受人不會走到這裡）。
        if e.kind == "carrier_bad" and not _degraded:
            await _degrade_and_reopen(db, invoice_repo, claimed, order, user,
                                       {"status": "carrier_format", "desc": e.reason})
            return
        await _finalize_needs_manual(invoice_repo, claimed, kind=e.kind, desc=e.reason)
        return

    svc = get_smilepay_service()
    try:
        resp = await svc.issue_invoice(**fields)
    except httpx.ReadTimeout:
        # 結果不明（response 遺失）：data_id 冪等只保證同期別內，跨期重送可能真開兩張——
        # 不賭 -10072，人工核對速買配後台最安全（設計 §4.2/§6）。
        await _finalize_needs_manual(invoice_repo, claimed, kind="response_lost",
                                      desc="read timeout，結果不明，需人工核對速買配後台")
        return
    except httpx.HTTPError:
        # connect error（請求未送出）：安全重試。
        attempts = int(claimed.get("attempts", 0)) + 1
        await invoice_repo.update(invoice_id, {
            "status": "failed",
            "attempts": attempts,
            "next_retry_at": get_utc_timestamp() + _next_retry_delay(attempts),
            "last_error": {"status": "connect_error", "desc": "連線失敗，請求可能未送達"},
            "claimed_until": None,
        })
        return

    status_code = str(resp.get("Status", ""))
    attempts = int(claimed.get("attempts", 0)) + 1

    if status_code == "0":
        await invoice_repo.update(invoice_id, {
            "status": "issued",
            "invoice_type": resp.get("InvoiceType") or buyer.get("invoice_type"),
            "invoice_number": resp.get("InvoiceNumber"),
            "random_number": resp.get("RandomNumber"),
            "invoice_date": resp.get("InvoiceDate"),
            "attempts": attempts,
            "claimed_until": None,
            "last_error": None,
        })
        log.info("invoice.issue.success", order_no=claimed.get("order_no"),
                 invoice_number=resp.get("InvoiceNumber"))
        return

    if status_code == _DATA_ID_DUPLICATE:
        await _finalize_needs_manual(
            invoice_repo, claimed, kind="duplicate_data_id",
            desc="data_id 重複，前次可能已成功但號碼取不回，需上速買配後台人工回填",
            attempts=attempts, last_error={"status": status_code, "desc": resp.get("Desc", "")},
        )
        return

    category = classify_invoice_error(status_code)
    last_error = {"status": status_code, "desc": resp.get("Desc", "")}

    if category == "transient":
        await invoice_repo.update(invoice_id, {
            "status": "failed",
            "attempts": attempts,
            "next_retry_at": get_utc_timestamp() + _next_retry_delay(attempts),
            "last_error": last_error,
            "claimed_until": None,
        })
        return

    # 載具自動降級僅限個人戶（B2C）；公司戶（B2B）不可擅自降級成無統編發票（設計 §4.2：
    # 企業要統編抵稅），理論上 B2B 請求不會帶 CarrierType 也就不會撞這幾個碼，這裡仍加保守防線。
    if category == "carrier_bad" and not _degraded and buyer.get("invoice_type") != "company":
        await _degrade_and_reopen(db, invoice_repo, claimed, order, user, last_error)
        return

    # buyer_bad / unknown（含降級後仍載具錯、或 company 買受人的 carrier_bad 保守 fallback）
    # → needs_manual + alert
    await _finalize_needs_manual(invoice_repo, claimed, kind=category, desc=resp.get("Desc", ""),
                                  attempts=attempts, last_error=last_error)


async def _degrade_and_reopen(db, invoice_repo: InvoiceRepository, claimed: Dict[str, Any],
                               order: Dict[str, Any], user: Optional[Dict[str, Any]],
                               last_error: Dict[str, Any]) -> None:
    """載具錯誤自動降級：改 B2C 無載具（Name+Email），沿用同一 document 換新 data_id 重開。

    （成功後應通知使用者載具未生效——PR-A 先以 log 記錄，實際 email 通知留待後續 PR，
    見交付報告「偏差」章節。）
    """
    new_buyer = {
        "invoice_type": "personal", "carrier_type": None, "carrier_num": None,
        "company_tax_id": None, "company_name": None,
    }
    new_data_id = f"{claimed['data_id']}-B2C"
    await invoice_repo.update(claimed["_id"], {
        "status": "pending",
        "data_id": new_data_id,
        "buyer": new_buyer,
        "last_error": last_error,
        "claimed_until": None,
    })
    log.warning("invoice.carrier_degraded", order_no=claimed.get("order_no"),
                user_id=claimed.get("user_id"), reason=last_error)
    refreshed = await invoice_repo.get_by_id(claimed["_id"])
    if refreshed is None:
        return
    await _attempt_issue(db, invoice_repo, refreshed, order, user, _degraded=True)


# ── 對外入口：settle() 白名單觸發 ──────────────────────────────────────────────

async def issue_for_order(db, order: Dict[str, Any]) -> None:
    """settle() 成功（ACTIVATED/RENEWED/GRANTED）觸發的背景開票入口。

    settle 重入防護第一層：該 order 已有 issued 發票 → 跳過。

    重入時沿用既有的「非 voided」doc（無論其現有 data_id 是不是已被 `_degrade_and_reopen`
    改過），只有完全沒有任何 invoice doc 時才用 `upsert_initial` 建新的。★這是修過的 bug：
    舊版每次都用固定的 `data_id=f"SL-{order_no}"` 呼叫 upsert_initial，降級後該 doc 的
    data_id 已經被改成 `..-B2C`，下次 settle 重入（或 sweep 重試觸發二次 issue_for_order）
    會因為找不到 `SL-{order_no}` 而插出第二筆 doc，且該筆之後降級時的 `$set data_id` 還會撞
    第一筆的 unique index → DuplicateKeyError。
    """
    order_no = order.get("merchant_order_no")
    if not order_no:
        log.warning("invoice.issue.missing_order_no")
        return

    invoice_repo = InvoiceRepository(db)
    user = await UserRepository(db).get_by_id(order.get("user_id"))

    existing = await invoice_repo.get_active_by_order_no(order_no)
    if existing:
        if existing.get("status") == "issued":
            log.info("invoice.issue.skip_already_issued", order_no=order_no)
            return
        doc = existing
    else:
        buyer = resolve_buyer_snapshot(order, user)
        now = get_utc_timestamp()
        doc = await invoice_repo.upsert_initial(
            order_no=order_no,
            user_id=order.get("user_id"),
            data_id=f"SL-{order_no}",
            buyer=buyer,
            amount_twd=order.get("amount_twd", 0),
            deadline_at=_deadline_at(order, buyer, now),
        )
    await _attempt_issue(db, invoice_repo, doc, order, user)


# ── 作廢 ──────────────────────────────────────────────────────────────────

async def void_invoice_for(db, invoice: Dict[str, Any], reason: str, admin_id: str) -> Dict[str, Any]:
    """作廢發票（types=Cancel）。-2008（附 Nowstatus）/-2009 原样回給呼叫端（admin router 用）。"""
    invoice_repo = InvoiceRepository(db)
    svc = get_smilepay_service()
    try:
        resp = await svc.void_invoice(
            invoice_number=invoice.get("invoice_number"),
            invoice_date=invoice.get("invoice_date"),
            reason=(reason or "")[:20],
        )
    except httpx.HTTPError as e:
        # transport 失敗回結構化錯誤（不讓例外帶著 _post 的 frame locals 往上竄）
        log.warning("invoice.void.transport_error", order_no=invoice.get("order_no"),
                    error=type(e).__name__)
        return {"success": False, "status_code": "-9999",
                "desc": f"連線失敗（{type(e).__name__}），請稍後重試", "now_status": None}
    status_code = str(resp.get("Status", ""))
    if status_code == "0":
        await invoice_repo.update(invoice["_id"], {
            "status": "voided",
            "voided_at": get_utc_timestamp(),
            "void_reason": (reason or "")[:20],
        })
        log.info("invoice.void.success", order_no=invoice.get("order_no"), admin_id=admin_id)
        return {"success": True, "status_code": status_code}
    log.warning("invoice.void.failed", order_no=invoice.get("order_no"), status_code=status_code,
                desc=resp.get("Desc"), now_status=resp.get("Nowstatus"))
    return {
        "success": False, "status_code": status_code,
        "desc": resp.get("Desc", ""), "now_status": resp.get("Nowstatus"),
    }


# ── 重開（作廢後/needs_manual 後）────────────────────────────────────────────

async def reissue(db, invoice: Dict[str, Any], corrected_buyer: Optional[Dict[str, Any]] = None,
                   admin_id: str = "") -> Dict[str, Any]:
    """允許 status ∈ {voided, needs_manual}。新 data_id = SL-{order_no}-R{n}；
    併發撞號由 data_id unique index 擋，DuplicateKeyError 重算一次。
    """
    if invoice.get("status") not in ("voided", "needs_manual"):
        raise ValueError(f"invoice status {invoice.get('status')!r} 不允許 reissue")

    order_no = invoice["order_no"]
    order = await OrderRepository(db).get_by_order_no(order_no)
    if not order:
        # 不可 `order or {}` 續跑——那會用 amount_twd=0 組出零元發票送 SmilePay。
        raise ValueError(f"reissue 找不到對應訂單，拒絕重開：order_no={order_no}")

    invoice_repo = InvoiceRepository(db)
    buyer = corrected_buyer or invoice.get("buyer") or {}

    if corrected_buyer:
        user_repo = UserRepository(db)
        await user_repo.update_invoice_info(invoice["user_id"], {
            "type": buyer.get("invoice_type"),
            "carrier_type": buyer.get("carrier_type") or "",
            "carrier_num": buyer.get("carrier_num") or "",
            "company_tax_id": buyer.get("company_tax_id") or "",
            "company_name": buyer.get("company_name") or "",
        })

    now = get_utc_timestamp()
    for _ in range(2):  # 撞號重算一次
        seq = await invoice_repo.next_reissue_seq(order_no)
        data_id = f"SL-{order_no}-R{seq}"
        try:
            new_doc = await invoice_repo.create({
                "order_no": order_no,
                "user_id": invoice["user_id"],
                "data_id": data_id,
                "status": "pending",
                "buyer": buyer,
                "amount_twd": invoice.get("amount_twd", 0),
                "first_attempt_at": now,
                "next_retry_at": now,
                "deadline_at": _deadline_at(order, buyer, now),
            })
            break
        except DuplicateKeyError:
            continue
    else:
        raise DuplicateKeyError(f"reissue data_id 撞號重算失敗：order_no={order_no}")

    user = await UserRepository(db).get_by_id(invoice["user_id"])
    await _attempt_issue(db, invoice_repo, new_doc, order, user)
    log.info("invoice.reissue", order_no=order_no, data_id=data_id, admin_id=admin_id)
    return await invoice_repo.get_by_id(new_doc["_id"])


# ── 背景 sweep（比照 renewal_service 形狀）───────────────────────────────────

async def periodic_invoice_retry(db, interval_seconds: int = INVOICE_RETRY_INTERVAL_SECONDS) -> None:
    """啟動立即跑一次，之後每 interval 掃描。受 main.py 的 RUN_BACKGROUND_JOBS 保護。"""
    while True:
        try:
            await run_invoice_retry_sweep(db)
        except Exception as e:
            log.error("invoice.sweep.failed", error=str(e), exc_info=True)
        await asyncio.sleep(interval_seconds)


async def run_invoice_retry_sweep(db) -> Dict[str, int]:
    """一輪掃描：deadline 告警（獨立掃描）+ 到期重試（含跨期 gate）。回傳計數（測試用）。"""
    invoice_repo = InvoiceRepository(db)
    order_repo = OrderRepository(db)
    user_repo = UserRepository(db)
    now = get_utc_timestamp()
    counts = {"retried": 0, "cross_period_blocked": 0, "deadline_warned": 0, "order_missing": 0, "errored": 0}

    # deadline 告警：不依附 retry 條件，超過 deadline 仍照常重試開立（只在此告警記錄稅務日期差異）。
    async for inv in invoice_repo.iter_deadline_warnings(now, DEADLINE_WARNING_SECONDS):
        _capture_invoice_alert(inv, "deadline_approaching",
                                "即將超過開立時效（B2C 48hr / B2B 168hr），InvoiceDate 仍會送當下")
        await invoice_repo.mark_deadline_alerted(inv["_id"])
        counts["deadline_warned"] += 1

    # ★物化成 list：這個迴圈每筆都可能觸發 _attempt_issue → httpx 呼叫（up to 30s timeout），
    # 若沿用 async for 直接吃 motor cursor，長時間掛在迴圈中會撞 Mongo cursor idle timeout。
    # 撈單當下就把資料全拉進記憶體，之後的網路 I/O 不再依賴這顆 cursor 存活。
    due = [inv async for inv in invoice_repo.iter_due_for_retry(now)]

    for inv in due:
        try:
            first_attempt_at = inv.get("first_attempt_at") or now
            if _period_key(now) != _period_key(first_attempt_at):
                # data_id 防重複開票的效力只在同期別內 → 跨期後停止自動重試，轉人工。
                await invoice_repo.update(inv["_id"], {
                    "status": "needs_manual",
                    "last_error": {"status": "cross_period", "desc": "已跨期別，停止自動重試"},
                })
                _capture_invoice_alert(inv, "cross_period", "已跨期別，需人工確認是否已開立")
                counts["cross_period_blocked"] += 1
                continue

            order = await order_repo.get_by_order_no(inv.get("order_no"))
            if not order:
                log.warning("invoice.sweep.order_missing", order_no=inv.get("order_no"))
                counts["order_missing"] += 1
                continue

            user = await user_repo.get_by_id(inv.get("user_id"))
            await _attempt_issue(db, invoice_repo, inv, order, user)
            counts["retried"] += 1
        except Exception as e:
            # 單筆炸掉不可讓整輪 sweep 停擺——iter_due_for_retry 沒有 sort，同一顆 poison doc
            # 若不推進 next_retry_at，會卡在查詢結果最前面，之後每一輪都優先撈到它、其餘全撈不到。
            counts["errored"] += 1
            log.error("invoice.sweep.item_failed", order_no=inv.get("order_no"), error=str(e), exc_info=True)
            try:
                attempts = int(inv.get("attempts", 0)) + 1
                # 只在 doc 仍是 pending/failed 時 recovery——例外若發生在 _attempt_issue
                # 已寫入終局狀態（issued/needs_manual）之後，不可把它打回 failed 重送
                await invoice_repo.update_if_status(inv["_id"], ["pending", "failed"], {
                    "status": "failed",
                    "attempts": attempts,
                    "next_retry_at": now + _next_retry_delay(attempts),
                    "last_error": {"status": "sweep_exception", "desc": str(e)[:200]},
                    "claimed_until": None,
                })
            except Exception:
                log.error("invoice.sweep.item_failed.recovery_failed",
                          order_no=inv.get("order_no"), exc_info=True)

    if any(counts.values()):
        log.info("invoice.sweep.completed", **counts)
    return counts
