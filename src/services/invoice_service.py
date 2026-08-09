"""SmilePay 電子發票業務層。

設計唯一事實來源：docs/INVOICE_SMILEPAY_INTEGRATION_PLAN.md §4.2（+ §5 對映表、
§6 冪等表）；API 細節見 docs/INVOICE_SMILEPAY_API.md。

比照 renewal_service.py 的形狀：module-level 純函數 + 背景 sweep，不用 class。

呼叫鏈：
- OrderSettlement.settle() 白名單 outcome → create_background_task(issue_for_order(...))
- 背景 sweep（periodic_invoice_retry）每 10 分鐘：撈到期重試 + 獨立 deadline 告警 + 跨期 gate
- reissue() / void_invoice_for() / admin_retry()：admin 後台（PR-B）呼叫的服務層入口

🔴 Verify_key 絕不可進 log／Sentry breadcrumb（smilepay_service 已確保不進 URL；本檔一律
只 log 業務欄位如 order_no/data_id/status_code，不觸碰 Verify_key）。動到 payment 相關 diff
走 judgment-rubrics §5。
"""
import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from pymongo.errors import DuplicateKeyError

from ..database.repositories.invoice_repo import InvoiceRepository
from ..database.repositories.job_lease_repo import JobLeaseRepository
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


class RetryInFlightError(Exception):
    """admin_retry 搶不到 processing lease（sweep 或另一請求正在處理同一張發票）——
    admin router 轉 409，不視為失敗、不寫 audit（PR-B 驗收 finding #4）。"""
    pass


def _duplicate_key_hits_order_index(e: DuplicateKeyError) -> bool:
    """P2-14：區分 `reissue()` create 重試迴圈撞到的是哪個 unique index。

    `uniq_active_invoice_per_order`（order_no）代表該 order 已經有其他活躍發票
    （issued/pending/failed）——這不是「data_id 序號算錯，重算一次就好」的情況，
    doc 邏輯本身就衝突（雙開），繼續在迴圈裡重算 seq 只會讓第二方永遠撞牆。
    `data_id` 撞號才是既有的序號競爭，維持原本重算一次的行為。

    優先看結構化的 `keyPattern`；理論上不會缺，但某些 driver/伺服器版本組合下
    `details` 可能不完整，保守 fallback 用 errmsg 是否含 index name 字串判斷。
    """
    details = getattr(e, "details", None) or {}
    key_pattern = details.get("keyPattern") or {}
    if "data_id" in key_pattern:
        return False
    if "order_no" in key_pattern:
        return True
    return "uniq_active_invoice_per_order" in str(e)


class ReissueConflictError(Exception):
    """reissue 搶不到 reissue lease（狀態已變更，或另一個 admin 正在重開同一張發票）——
    admin router 轉 409（PR-B 驗收 finding #2：防雙擊/併發重開出兩張真發票）。"""

    def __init__(self, invoice_id):
        self.invoice_id = invoice_id
        super().__init__(f"invoice {invoice_id} 目前無法重開：狀態已變更或有其他操作正在進行")


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


def _capture_invoice_gap_recovered(order: Dict[str, Any]) -> None:
    """P2-13：每補一筆 gap sweep 都要看得到——每一筆都代表 settle() 的
    `create_background_task(issue_for_order(...))` fire-and-forget 起點曾經掉包
    （process kill 於 upsert_initial 落地之前），不是無害的正常路徑，用 warning 而非
    info，讓它在 Sentry 浮現而不是被 log 洪流蓋掉。形狀比照 `_capture_invoice_alert`。
    """
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("invoice.issue", "gap_recovered")
            scope.set_context("invoice_gap", {
                "order_no": order.get("merchant_order_no"),
                "user_id": order.get("user_id"),
                "paid_at": order.get("paid_at"),
            })
            sentry_sdk.capture_message("invoice.gap_recovered", level="warning")
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
                          order: Dict[str, Any], user: Optional[Dict[str, Any]], *, _degraded: bool = False) -> bool:
    """回傳是否真的搶到 lease 並跑了一次嘗試（False = claim-miss，另一個 process 正在處理）。

    回傳值目前只有 `admin_retry()` 在用（fresh-context 驗收 finding #4：admin 手動重試
    若跟背景 sweep 撞在一起搶不到 lease，要能分辨出來回 409，不能靜默當成功）；其餘呼叫端
    （issue_for_order/sweep/_degrade_and_reopen）沿用舊行為，不看回傳值。
    """
    invoice_id = invoice_doc["_id"]
    claimed = await invoice_repo.claim_for_processing(invoice_id)
    if not claimed:
        log.info("invoice.issue.claim_missed", order_no=invoice_doc.get("order_no"))
        return False

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
            return True
        await _finalize_needs_manual(invoice_repo, claimed, kind=e.kind, desc=e.reason)
        return True

    svc = get_smilepay_service()
    try:
        resp = await svc.issue_invoice(**fields)
    except httpx.ReadTimeout:
        # 結果不明（response 遺失）：data_id 冪等只保證同期別內，跨期重送可能真開兩張——
        # 不賭 -10072，人工核對速買配後台最安全（設計 §4.2/§6）。
        await _finalize_needs_manual(invoice_repo, claimed, kind="response_lost",
                                      desc="read timeout，結果不明，需人工核對速買配後台")
        return True
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
        return True

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
        return True

    if status_code == _DATA_ID_DUPLICATE:
        await _finalize_needs_manual(
            invoice_repo, claimed, kind="duplicate_data_id",
            desc="data_id 重複，前次可能已成功但號碼取不回，需上速買配後台人工回填",
            attempts=attempts, last_error={"status": status_code, "desc": resp.get("Desc", "")},
        )
        return True

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
        return True

    # 載具自動降級僅限個人戶（B2C）；公司戶（B2B）不可擅自降級成無統編發票（設計 §4.2：
    # 企業要統編抵稅），理論上 B2B 請求不會帶 CarrierType 也就不會撞這幾個碼，這裡仍加保守防線。
    if category == "carrier_bad" and not _degraded and buyer.get("invoice_type") != "company":
        await _degrade_and_reopen(db, invoice_repo, claimed, order, user, last_error)
        return True

    # buyer_bad / unknown（含降級後仍載具錯、或 company 買受人的 carrier_bad 保守 fallback）
    # → needs_manual + alert
    await _finalize_needs_manual(invoice_repo, claimed, kind=category, desc=resp.get("Desc", ""),
                                  attempts=attempts, last_error=last_error)
    return True


async def _degrade_and_reopen(db, invoice_repo: InvoiceRepository, claimed: Dict[str, Any],
                               order: Dict[str, Any], user: Optional[Dict[str, Any]],
                               last_error: Dict[str, Any]) -> None:
    """載具錯誤自動降級：改 B2C 無載具（Name+Email），沿用同一 document 換新 data_id 重開。

    （成功後應通知使用者載具未生效——PR-A 先以 log 記錄，實際 email 通知留待後續 PR，
    見交付報告「偏差」章節。）

    P2-14 相容性確認：這裡是 `update(claimed["_id"], {"status": "pending", ...})`——
    改的是同一顆既有 doc（`_id` 不變、`order_no` 不變），不是 insert 新 doc。呼叫路徑
    上，`claimed` 一定是剛被 `claim_for_processing` 搶到 lease 的 doc，而該方法的搶佔
    條件是 `status ∈ {pending, failed}`——也就是說在這次 update 之前，`claimed` 已經是
    `uniq_active_invoice_per_order`（issued/pending/failed）partial index 底下、該
    order_no 唯一一顆佔用中的活躍 doc。這次 update 把 status 從 pending/failed 改成
    pending，仍落在同一個 partial filter 集合內、`_id` 也沒變——對該 order_no 而言，
    「活躍 doc 數」在 update 前後都是 1（同一顆），不會新增第二個成員，因此不可能
    撞上這顆 unique index，不需要額外防護。（真正需要防護的是 insert 新 doc 的路徑，
    即 `reissue()` 的 create 重試迴圈，已在該處理。）
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

async def admin_retry(db, invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Admin 後台手動重試（PR-B）：立即嘗試一次，不等 next_retry_at backoff。

    呼叫端（admin router）負責 status ∈ {pending, failed} 的 409 gate；這裡只信任
    傳入的 invoice doc、查對應 order/user 後直接丟給 `_attempt_issue`（與 sweep 同一條路徑，
    claim_for_processing 仍會擋掉「同時有另一個 process 在處理」的情況）。
    查無 order 比照 reissue() 的做法拋 ValueError，讓 router 轉 4xx 而不是 500。

    `_attempt_issue` 回傳 False 代表搶不到 lease（多半是背景 sweep 正好在處理同一張）——
    這裡轉成 `RetryInFlightError` 而不是靜默當成功回傳，router 才能回 409 且不寫 audit
    （PR-B 驗收 finding #4：先前版本會把「其實什麼都沒做」誤記成一次成功的重試）。
    """
    invoice_repo = InvoiceRepository(db)
    order = await OrderRepository(db).get_by_order_no(invoice.get("order_no"))
    if not order:
        raise ValueError(f"admin_retry 找不到對應訂單：order_no={invoice.get('order_no')}")
    user = await UserRepository(db).get_by_id(invoice.get("user_id"))
    claimed_ok = await _attempt_issue(db, invoice_repo, invoice, order, user)
    if not claimed_ok:
        raise RetryInFlightError(f"invoice {invoice.get('_id')} 目前正被其他流程處理中")
    return await invoice_repo.get_by_id(invoice["_id"])


async def reissue(db, invoice: Dict[str, Any], corrected_buyer: Optional[Dict[str, Any]] = None,
                   admin_id: str = "") -> Dict[str, Any]:
    """允許 status ∈ {voided, needs_manual}。新 data_id = SL-{order_no}-R{n}；
    併發撞號由 data_id unique index 擋，DuplicateKeyError 重算一次。

    併發保護（PR-B 驗收 finding #2）：雙擊或兩個 admin 同時對同一張 voided/needs_manual
    發票按重開，若只憑呼叫端傳入的（可能已過期）status 判斷，會各自算出不同 R{n} 都送出
    成功 → 一張舊發票變出兩張真發票。修法：動作前對來源 invoice 做原子搶佔
    （`claim_for_reissue`，手法同 `claim_for_processing` 但欄位獨立，不影響 sweep 的
    `claimed_until` lease 語意）。搶不到 → `ReissueConflictError`（router 轉 409）。
    無論成功或失敗，都在 `finally` 釋放搶佔，避免卡死之後的重開嘗試。
    """
    if invoice.get("status") not in ("voided", "needs_manual"):
        raise ValueError(f"invoice status {invoice.get('status')!r} 不允許 reissue")

    invoice_repo = InvoiceRepository(db)
    claimed = await invoice_repo.claim_for_reissue(invoice["_id"])
    if not claimed:
        raise ReissueConflictError(invoice.get("_id"))

    try:
        order_no = claimed["order_no"]
        # lease 只擋「同時飛」；重開成功後來源 doc 仍是 voided/needs_manual，
        # 不查既有 issued/進行中的發票，前後兩次按重開會開出兩張真發票（複核 N1）。
        conflict = await invoice_repo.find_reissue_conflict(order_no)
        if conflict:
            raise ReissueConflictError(
                f"order {order_no} 已有 {conflict.get('status')} 狀態的發票"
                f"（{conflict.get('data_id')}），不可重開"
            )
        order = await OrderRepository(db).get_by_order_no(order_no)
        if not order:
            # 不可 `order or {}` 續跑——那會用 amount_twd=0 組出零元發票送 SmilePay。
            raise ValueError(f"reissue 找不到對應訂單，拒絕重開：order_no={order_no}")

        buyer = corrected_buyer or claimed.get("buyer") or {}

        if corrected_buyer:
            user_repo = UserRepository(db)
            await user_repo.update_invoice_info(claimed["user_id"], {
                "type": buyer.get("invoice_type"),
                "carrier_type": buyer.get("carrier_type") or "",
                "carrier_num": buyer.get("carrier_num") or "",
                "company_tax_id": buyer.get("company_tax_id") or "",
                "company_name": buyer.get("company_name") or "",
            })

        now = get_utc_timestamp()
        new_doc = None
        data_id = None
        for _ in range(2):  # 撞號重算一次
            seq = await invoice_repo.next_reissue_seq(order_no)
            data_id = f"SL-{order_no}-R{seq}"
            try:
                new_doc = await invoice_repo.create({
                    "order_no": order_no,
                    "user_id": claimed["user_id"],
                    "data_id": data_id,
                    "status": "pending",
                    "buyer": buyer,
                    "amount_twd": claimed.get("amount_twd", 0),
                    "first_attempt_at": now,
                    "next_retry_at": now,
                    "deadline_at": _deadline_at(order, buyer, now),
                })
                break
            except DuplicateKeyError as e:
                if _duplicate_key_hits_order_index(e):
                    # P2-14：撞到「該 order 已有活躍發票」的原子防線——不是 data_id
                    # 序號競爭，重算 seq 再試也沒用，直接轉 409 讓 router 回應衝突
                    # （router 已有 ReissueConflictError → 409 的既有處理）。
                    raise ReissueConflictError(invoice.get("_id")) from e
                continue
        else:
            raise DuplicateKeyError(f"reissue data_id 撞號重算失敗：order_no={order_no}")

        user = await UserRepository(db).get_by_id(claimed["user_id"])
        await _attempt_issue(db, invoice_repo, new_doc, order, user)
        log.info("invoice.reissue", order_no=order_no, data_id=data_id, admin_id=admin_id)
        return await invoice_repo.get_by_id(new_doc["_id"])
    finally:
        await invoice_repo.release_reissue_claim(invoice["_id"])


# ── 背景 sweep（比照 renewal_service 形狀）───────────────────────────────────

# P2-13：gap sweep 用獨立 window lease，每 1800 秒（30 分鐘）最多一輪——形狀比照
# payment_reconciliation.py 的 refund_audit lane（該檔 REFUND_AUDIT_LEASE_WINDOW_SECONDS
# 的同一個理由）：這是「補洞」的 fallback 掃描，不需要跟主迴圈的 600 秒節奏綁在一起，
# 用獨立鎖讓它照自己的節奏走，也不會被主迴圈搶走每輪的執行權。
INVOICE_GAP_SWEEP_WINDOW_SECONDS = 1800


async def periodic_invoice_retry(db, interval_seconds: int = INVOICE_RETRY_INTERVAL_SECONDS) -> None:
    """啟動嘗試搶當前時間窗執行權，搶到才立即跑一次；搶不到等下一輪。之後每 interval
    掃描。受 main.py 的 RUN_BACKGROUND_JOBS 保護。

    🔴 P0-2(a)：prod 兩個 uvicorn worker 都跑這個背景任務，用 JobLeaseRepository 對本輪
    時間窗搶執行權，避免同一輪重試/告警被跑兩次。lease 檢查失敗（DB 例外）fail-open，
    照跑本輪並記警告——sweep 本身冪等，寧可偶發重跑也不要發票補救 sweep 全停。
    """
    lease_repo = JobLeaseRepository(db)
    while True:
        should_run = True
        try:
            should_run = await lease_repo.claim_window("invoice_retry", interval_seconds)
        except Exception as e:
            log.warning("invoice.sweep.lease_check_failed", error=str(e))
        if should_run:
            try:
                await run_invoice_retry_sweep(db)
            except Exception as e:
                log.error("invoice.sweep.failed", error=str(e), exc_info=True)

        # P2-13：獨立 window lease，跟上面主迴圈的 lease 完全分開判定——即使上面
        # 搶輸了（should_run=False），這段仍照自己 30 分鐘一輪的節奏獨立判斷
        # （比照 payment_reconciliation.periodic_payment_reconciliation 的 refund_audit lane）。
        should_run_gap = True
        try:
            should_run_gap = await lease_repo.claim_window("invoice_gap", INVOICE_GAP_SWEEP_WINDOW_SECONDS)
        except Exception as e:
            log.warning("invoice.gap_sweep.lease_check_failed", error=str(e))
        if should_run_gap:
            try:
                await run_invoice_gap_sweep(db)
            except Exception as e:
                log.error("invoice.gap_sweep.failed", error=str(e), exc_info=True)

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


# ── P2-13：開票補洞 sweep ──────────────────────────────────────────────────

async def run_invoice_gap_sweep(db) -> Dict[str, int]:
    """一輪掃描：撈「已付款但可能從未觸發開票」的訂單，補呼叫 issue_for_order。

    動機（見本檔頂部 docstring 呼叫鏈）：`OrderSettlement.settle()` 的
    `create_background_task(issue_for_order(...))` 是唯一的開票起點，若這個
    asyncio task 在 `upsert_initial` 落地前就被 process kill（部署重啟、OOM、
    uvicorn worker 被 supervisor 殺掉），這筆訂單永遠不會有任何 invoice doc，
    且完全不留痕跡（沒有例外、沒有 log、`run_invoice_retry_sweep` 也查無此 doc）。
    `run_invoice_retry_sweep` 只能掃「已存在」的 invoices doc，對這種「doc 從未
    落地」的洞結構性補不到——這支 sweep 反過來從 orders 找，用
    `invoice_repo.exists_any_by_order_no`（**任何**狀態都算數，不只 issued）判斷
    是否真的是洞：有 doc（不論 issued/pending/failed/voided/needs_manual）代表
    開票流程有跑過，後續狀態演進歸 retry sweep / reissue 管，這支不重複介入。

    `issue_for_order` 本身冪等（upsert_initial 用 data_id 當唯一鍵 + `_attempt_issue`
    走 claim lease），補呼叫它不會與正常路徑或 retry sweep 衝突。
    """
    # M2（第二意見審查）：retro 補開票必須明確 opt-in。未設 INVOICE_GAP_EPOCH 時整支
    # sweep 是 no-op——稅務文件不可逆，寧可不補也不能在首次部署一次性 retro 補開過去
    # 7 天的單（可能已在速買配後台人工開過票 → 重複開真發票）。上線流程：確認發票整合
    # 全量生效後，把 epoch 設成當下時間戳，此後只補 epoch 之後的付款漏單。
    epoch_raw = os.getenv("INVOICE_GAP_EPOCH")
    if not epoch_raw:
        log.warning("invoice.gap_sweep.disabled_no_epoch")
        return {"gap_issued": 0, "has_doc": 0, "errored": 0, "skipped_no_epoch": 1}
    try:
        epoch = float(epoch_raw)
    except ValueError:
        log.error("invoice.gap_sweep.bad_epoch", value_len=len(epoch_raw))
        return {"gap_issued": 0, "has_doc": 0, "errored": 0, "skipped_bad_epoch": 1}

    order_repo = OrderRepository(db)
    invoice_repo = InvoiceRepository(db)
    now = get_utc_timestamp()
    counts = {"gap_issued": 0, "has_doc": 0, "errored": 0}

    # 撈單當下物化成 list（比照 run_invoice_retry_sweep 的既有理由）：每筆都可能
    # 觸發 issue_for_order → httpx 呼叫，長時間掛在迴圈中不宜依賴 motor cursor 存活。
    candidates = [o async for o in order_repo.iter_paid_invoice_gap_candidates(now, epoch)]

    for order in candidates:
        order_no = order.get("merchant_order_no")
        try:
            if await invoice_repo.exists_any_by_order_no(order_no):
                counts["has_doc"] += 1
            else:
                log.info("invoice.gap_sweep.recovering", order_no=order_no)
                await issue_for_order(db, order)
                _capture_invoice_gap_recovered(order)
                counts["gap_issued"] += 1
            # 檢查過就 stamp 推進輪替游標（M1）——不論補開或已有 doc，都讓這筆排到隊尾，
            # 積壓 > batch 上限時下一輪換最久沒查的一批。stamp 失敗不影響本筆結果。
            await order_repo.stamp_invoice_gap_checked(order_no, now)
        except Exception as e:
            # 單筆炸掉不可讓整輪 sweep 停擺。stamp 也在 try 內：poison order 若 stamp 前就
            # 炸，下一輪（invoice_gap_checked_at 仍為舊值/缺）會再被撈到重試，不會卡佇列頭。
            counts["errored"] += 1
            log.error("invoice.gap_sweep.item_failed", order_no=order_no, error=str(e), exc_info=True)

    if any(counts.values()):
        log.info("invoice.gap_sweep.completed", **counts)
    return counts
