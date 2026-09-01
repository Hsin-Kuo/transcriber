"""訂閱管理路由（91APP Payments）。

首購流程：前端 SDK tokenize → POST /checkout（建 pending 單、回 SDK 參數）→
POST /pay（送 txnToken，後端 request-by-txnToken BindingCard，捕捉 cardToken）→
若回 paymentUrl 走 3D，完成後 91APP 打 POST /callback（不信 payload → 回查交易 → settle）。
續扣（Phase 2）由本地排程器直接呼叫 settle，不經 callback。
"""
import os
import json
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional

from ..utils.api_errors import api_error

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.order_repo import OrderRepository
from ..database.repositories.processed_webhook_repo import ProcessedWebhookRepository
from ..database.repositories.invoice_repo import InvoiceRepository, pick_user_facing_invoice
from ..models.quota import public_tier_plans, is_upgrade, QUOTA_TIERS, QuotaTier
from ..services.invoice_service import (
    build_invoice_snapshot_from_request,
    build_invoice_snapshot_from_user_invoice_info,
)
from ..services.order_settlement import build_order_settlement, PaymentNotification
from ..utils.payments91_service import get_payments91_service, interpret_record_status, TRADE_ID_RE
from ..utils.card_token_cipher import encrypt
from ..utils.billing_period import generate_order_no
from ..utils.time_utils import get_utc_timestamp
from ..utils.sentry_helpers import create_background_task
from ..utils.logger import get_logger

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])
log = get_logger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def _callback_url() -> str:
    return f"{BACKEND_URL}/subscriptions/callback"


def _redirect_url(order_no: str) -> str:
    # 3D 完成後 91APP 把瀏覽器導回此後端端點（91APP 要求 redirectUrl 為 https；由後端自有
    # https 網域掌控最穩），後端再 303 轉回前端 SPA 的 /payment/return。
    return f"{BACKEND_URL}/subscriptions/payment-return?order_no={order_no}"


def _find(obj, key_lower: str):
    """遞迴找第一個名稱等於 key_lower（小寫比較）的值。用於從 91APP 回應挖 cardToken/paymentUrl/tradeId。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == key_lower and v not in (None, ""):
                return v
            found = _find(v, key_lower)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find(item, key_lower)
            if found not in (None, ""):
                return found
    return None


def _encrypt_card_token_safe(plaintext: str, order_no: str, context: str):
    """加密 card_token 供落庫；失敗回 None 而非拋（F2，跨 PR 複檢）。

    encrypt 例外（KEK 未 seed / SSM 暫時性讀取失敗）絕不能阻斷呼叫端流程：在 /pay 會
    連帶擋掉同一批 update 的 trade_id 落庫（→ 對帳 sweep 要求有 trade_id，這張已扣款單
    變結構性不可見、T+1h 被標 expired、使用者扣款卻無訂閱無告警）；在 /callback 這段
    位於 _process_payment_result（settle）之前，拋出會直接讓整筆結算不執行。

    失敗時略過 card_token 儲存，續扣時由 renewal_service 的 NoCardToken →
    needs_card_update dunning 兜底（callback 補救路徑本就依賴這條）。error=str(e) 只含
    KEK/參數的錯誤分類字串（"invalid length"/"... unavailable from SSM"），不含 token 或
    金鑰值本身。
    """
    try:
        return encrypt(plaintext)
    except Exception as e:
        log.error("subscription.card_token.encrypt_failed",
                  order_no=order_no, context=context, error=str(e))
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                sentry_sdk.capture_message("card_token.encrypt_failed", level="error")
        except ImportError:
            pass
        return None


# ── Request Models ───────────────────────────────────────────────────────────

# 統編 8 碼數字；手機條碼載具 `/` + 7 碼（數字/大寫英文/+-.）。後端也要驗（非瀏覽器 client
# 會繞過前端），與 invoice_service 的開票前 sanity check（build_invoice_fields 入口）共用同一組
# pattern，避免兩處定義飄移（設計 §3.3.1/§3.3.3）。
_TAX_ID_PATTERN = r"^\d{8}$"
_CARRIER_PATTERN = r"^/[0-9A-Z+\-.]{7}$"

# 前端 CheckoutView.buildInvoiceData() 對「未選中那組」欄位固定送 `''`（不是 null/省略，
# 見 frontend/src/views/CheckoutView.vue）。Optional[str] + Field(pattern=...) 只在值為
# None 時跳過檢查——空字串仍會進 pattern 比對而 422（string_pattern_mismatch）。
# 必須在 pattern 檢查「之前」（mode="before"）把空白字串正規化成 None。
def _blank_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _require_company_fields_if_company(model):
    """invoice_type=company 時 company_tax_id + company_name 皆必填（設計 §3.3.1）。

    只驗 company_name 不夠：{invoice_type:"company", company_name:"X"}（缺統編）過去會
    通過 request 驗證，直到付款成功後開票層才因統編格式錯炸 buyer_bad——應該在建單當下
    就擋下，不要讓使用者付完錢才發現。
    """
    if model.invoice_type == "company":
        if not (model.company_tax_id or "").strip():
            raise ValueError("company_tax_id is required when invoice_type is 'company'")
        if not (model.company_name or "").strip():
            raise ValueError("company_name is required when invoice_type is 'company'")
    return model


class CheckoutRequest(BaseModel):
    tier: str       # "basic" | "pro"
    billing: str    # "monthly" | "yearly"
    invoice_type: Optional[str] = None   # "personal" | "company"
    carrier_type: Optional[str] = None   # "1"=手機條碼
    carrier_num: Optional[str] = Field(default=None, pattern=_CARRIER_PATTERN)
    company_tax_id: Optional[str] = Field(default=None, pattern=_TAX_ID_PATTERN)
    company_name: Optional[str] = None
    save_invoice: bool = True

    @field_validator("carrier_type", "carrier_num", "company_tax_id", "company_name", mode="before")
    @classmethod
    def _normalize_blank(cls, v):
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _validate_invoice(self) -> "CheckoutRequest":
        return _require_company_fields_if_company(self)


class PayRequest(BaseModel):
    order_no: str
    txn_token: str = Field(..., min_length=1)


class ChangePlanRequest(BaseModel):
    tier: str
    billing: str
    invoice_type: Optional[str] = None
    carrier_type: Optional[str] = None
    carrier_num: Optional[str] = Field(default=None, pattern=_CARRIER_PATTERN)
    company_tax_id: Optional[str] = Field(default=None, pattern=_TAX_ID_PATTERN)
    company_name: Optional[str] = None
    save_invoice: bool = True

    @field_validator("carrier_type", "carrier_num", "company_tax_id", "company_name", mode="before")
    @classmethod
    def _normalize_blank(cls, v):
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _validate_invoice(self) -> "ChangePlanRequest":
        return _require_company_fields_if_company(self)


class PurchaseExtraRequest(BaseModel):
    package_id: str
    quantity: int = Field(default=1, ge=1, le=99)
    invoice_type: Optional[str] = None
    carrier_type: Optional[str] = None
    carrier_num: Optional[str] = Field(default=None, pattern=_CARRIER_PATTERN)
    company_tax_id: Optional[str] = Field(default=None, pattern=_TAX_ID_PATTERN)
    company_name: Optional[str] = None
    save_invoice: bool = True

    @field_validator("carrier_type", "carrier_num", "company_tax_id", "company_name", mode="before")
    @classmethod
    def _normalize_blank(cls, v):
        return _blank_to_none(v)

    @model_validator(mode="after")
    def _validate_invoice(self) -> "PurchaseExtraRequest":
        return _require_company_fields_if_company(self)


# ── 發票資訊處理 ─────────────────────────────────────────────────────────────

async def _handle_invoice_save(request_data, user_id: str, user_repo: UserRepository):
    """若 save_invoice=True，將發票資訊整包覆蓋寫入 user document（設計 §3.3.2）。

    整包覆蓋語意：只要指定了 invoice_type 就整段覆蓋（含清空另一型態的舊值），不論本次
    是否帶 carrier_num/company_tax_id——修正舊版「只在有值時才寫入、切換型態不清舊值」
    的殘留值問題（公司改回個人後仍被開 B2B）。
    """
    if not request_data.save_invoice:
        return
    if request_data.invoice_type == "personal":
        await user_repo.update_invoice_info(user_id, {
            "type": "personal",
            "carrier_type": request_data.carrier_type or "1",
            "carrier_num": request_data.carrier_num or "",
            "company_tax_id": "",
            "company_name": "",
        })
    elif request_data.invoice_type == "company":
        await user_repo.update_invoice_info(user_id, {
            "type": "company",
            "carrier_type": "",
            "carrier_num": "",
            "company_tax_id": request_data.company_tax_id or "",
            "company_name": request_data.company_name or "",
        })


# ── 付款結果收斂（/pay 立即成交 與 /callback 共用）──────────────────────────────

async def _process_payment_result(
    db, *, trade_id: str, record_status: str, order_no: str, success: bool,
) -> str:
    """claim 去重 → settle。回傳 outcome 字串（或 "duplicate"）。失敗會 release + raise。

    is_first_payment 由 order type 推導：type=renewal（換卡挽回/續扣）走續扣分支，其餘為首期。

    natural_id（P0-1 金流體檢）：只用 trade_id（缺 trade_id 時 fallback order_no），
    不再併入 record_status。舊版 `f"{trade_id}:{record_status}"` 會讓同一筆 trade 的
    recordStatus 演進（例如 91APP 4→5）或 /pay 立即成交與 /callback 兩條路徑各自帶不同
    record_status 打進來時，被當成「不同封 webhook」各自 claim 一次成功——去重形同虛設。
    現在同一 trade_id（或同一 order_no）只有一次 claim 會贏，record_status 的演進交給
    order 狀態機（claim_paid 的 status!=paid→paid）判斷，不再靠 natural_id 分岔。
    record_status 仍保留在 claim metadata 供觀測。

    F10（第二意見審查）：失敗通知額外加 ":fail" 後綴分鍵——同一筆 trade 若先收到一封
    失敗通知（先佔走 trade_id 主鍵），之後同一 trade 的成功 callback 用同一把鍵會被
    claim 擋成 duplicate，變成「扣款其實成功但訂閱從未啟用」。分鍵後成功/失敗各自
    claim 一次；mark_failed_unless_paid 本身在 DB 層已是 idempotent 的 `$ne paid` 條件式
    寫入，失敗鍵重複 claim 不會造成覆寫風險，分鍵零成本。
    ✅ 退款 callback（91APP recordStatus 6/7）：P1-5 已實作——interpret_record_status
    現在把 6/7 拆成獨立的 "refunded" 語意（不再併入 "failed"）。payment_callback 在
    outcome=="pending" 早退之後、success/fail 判定之前就把 outcome=="refunded" 分流
    給 `_process_refund`（獨立的 claim 鍵 `f"refund:{record_status}:{trade_id or order_no}"`，
    record_status 入鍵讓部分退款(6)與全額退款(7)各自一封，不會共用一把鍵互相 dedup），
    完全不會走到這個函式、也不會落入下面的 ":fail" 分支。
    ":fail" 鍵現在只服務 recordStatus 2/3（付款失敗/取消）——退款有自己獨立的
    claim namespace，兩者不再混在一起。
    """
    order = await OrderRepository(db).get_by_order_no(order_no)
    is_first_payment = not (order and order.get("type") == "renewal")
    webhook_repo = ProcessedWebhookRepository(db)
    natural_id = (trade_id or order_no) + ("" if success else ":fail")
    if not await webhook_repo.claim(
        provider="91app",
        natural_id=natural_id,
        metadata={"status": record_status, "trade_id": trade_id, "order_no": order_no},
    ):
        log.warning("subscription.webhook.duplicate_skipped", natural_id=natural_id)
        return "duplicate"
    try:
        result = await build_order_settlement(db).settle(PaymentNotification(
            order_no=order_no,
            success=success,
            is_first_payment=is_first_payment,
            trade_id=trade_id or "",
        ))
        log.info("subscription.webhook.settled", natural_id=natural_id, outcome=result.outcome.value)
        return result.outcome.value
    except Exception as e:
        await webhook_repo.release(provider="91app", natural_id=natural_id)
        log.error("subscription.webhook.processing_failed", natural_id=natural_id, error=str(e), exc_info=True)
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("webhook.provider", "91app")
                scope.set_tag("webhook.order_no", order_no)
                sentry_sdk.capture_exception(e)
        except Exception:
            # L10（第二意見審查）：見 _process_refund 同款註解——push_scope 本身拋出
            # 非 ImportError 例外時不能取代掉正在外拋的原始例外。
            pass
        raise


async def _process_refund(db, *, trade_id: str, record_status: str, order_no: str) -> str:
    """91APP 退款/爭議款 callback 收斂（recordStatus 6 部分退款／7 全額退款，P1-5）。

    形狀比照 `_process_payment_result`：claim 去重 → 呼叫對應的 OrderSettlement 方法。
    唯一差異是 claim 鍵——`natural_id` 把 `record_status` 打進去
    （`f"refund:{record_status}:{trade_id or order_no}"`）：部分退款(6)與全額退款(7)
    是完全不同的處置語意（人工 vs 自動降級），不能像 `_process_payment_result` 的
    `":fail"` 鍵那樣共用一把鍵，否則同一筆 trade 若先後收到 6 又收到 7（或反過來）
    會有一封被 dedup 掉、該做的動作沒做到。

    settle 例外時 release claim + re-raise，行為對齊 `_process_payment_result`——
    讓 91APP 重送有機會重新處理，不留下「claim 已佔用但動作沒做完」的坑。
    """
    webhook_repo = ProcessedWebhookRepository(db)
    natural_id = f"refund:{record_status}:{trade_id or order_no}"
    if not await webhook_repo.claim(
        provider="91app",
        natural_id=natural_id,
        metadata={"status": record_status, "trade_id": trade_id, "order_no": order_no},
    ):
        log.warning("subscription.webhook.refund_duplicate_skipped", natural_id=natural_id)
        return "duplicate"
    settlement = build_order_settlement(db)
    try:
        rs = int(record_status)
        if rs == 7:
            outcome = await settlement.handle_full_refund(order_no, trade_id=trade_id)
        else:
            outcome = await settlement.flag_partial_refund(order_no, record_status=rs)
        log.info("subscription.webhook.refund_settled", natural_id=natural_id, outcome=outcome)
        return outcome
    except Exception as e:
        await webhook_repo.release(provider="91app", natural_id=natural_id)
        log.error("subscription.webhook.refund_processing_failed", natural_id=natural_id, error=str(e), exc_info=True)
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("webhook.provider", "91app")
                scope.set_tag("webhook.order_no", order_no)
                sentry_sdk.capture_exception(e)
        except Exception:
            # L10（第二意見審查）：原本只接 ImportError（未裝 sentry_sdk），但
            # push_scope()/capture_exception() 本身也可能拋非 ImportError 的例外
            # （例如 SDK 內部狀態問題）——那種例外會取代掉正在往外拋的原始例外 e，
            # 讓呼叫端看到的變成 Sentry 自己的錯誤，掩蓋真正的失敗原因。
            pass
        raise


# ── 訂閱端點 ─────────────────────────────────────────────────────────────────

@router.get("/payment-config")
async def payment_config(current_user: dict = Depends(get_current_user)):
    """前端 SDK 初始化參數（publishableKey 非機密）。不建單——供結帳頁 onMounted 先 setupSDK。

    分離自 /checkout：建單有 30 秒冷卻（重複建單會 429），故取 SDK 參數不可綁建單。
    """
    svc = get_payments91_service()
    return {
        "publishable_key": svc.publishable_key,
        "sdk_server_type": svc.sdk_server_type,
    }


@router.post("/checkout")
async def create_checkout(
    request: CheckoutRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """建立新訂閱：建 pending 單，回傳付款所需參數（含 SDK 參數，供不分離取用時使用）。"""
    if request.tier not in ("basic", "pro"):
        raise api_error("SUBSCRIPTION_INVALID_TIER", "Invalid subscription plan", 400)
    if request.billing not in ("monthly", "yearly"):
        raise api_error("SUBSCRIPTION_INVALID_BILLING_CYCLE", "Invalid billing cycle", 400)

    user_repo = UserRepository(db)
    user_id = str(current_user["_id"])
    full_user = await user_repo.get_by_id(user_id)
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") in ("active", "trialing"):
        raise api_error("SUBSCRIPTION_ALREADY_ACTIVE",
                        "You already have an active subscription, please use the change plan feature", 400)

    svc = get_payments91_service()
    amount = svc.get_subscription_price(request.tier, request.billing)
    if not amount:
        raise api_error("SUBSCRIPTION_PRICE_NOT_CONFIGURED", "Price is not configured", 500)

    order_no = generate_order_no("SLSUB")
    await build_order_settlement(db).open_pending({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "subscription",
        "tier": request.tier,
        "billing_cycle": request.billing,
        "amount_twd": amount,
        "status": "pending",
        "trade_id": None,
        "card_token": None,
        "extra_duration_minutes": 0,
        "extra_ai_summaries": 0,
        "invoice_snapshot": build_invoice_snapshot_from_request(request),
    })

    await _handle_invoice_save(request, user_id, user_repo)

    return {
        "order_no": order_no,
        "amount": amount,
        "publishable_key": svc.publishable_key,
        "sdk_server_type": svc.sdk_server_type,
    }


@router.post("/pay")
async def pay(
    request: PayRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """收前端 txnToken，呼叫 91APP request-by-txnToken（BindingCard 首購）。

    回 paymentUrl 表示需 3D（前端導頁，完成後走 /callback）；否則依 statusCode 立即收斂。
    """
    user_id = str(current_user["_id"])
    order_repo = OrderRepository(db)
    order = await order_repo.get_by_order_no(request.order_no)
    if not order or order.get("user_id") != user_id:
        raise api_error("ORDER_NOT_FOUND", "Order not found", 404)
    if order.get("status") != "pending":
        raise api_error("ORDER_NOT_PENDING", "Order is not payable", 400)
    # P3-I（金流體檢 P1-9 第二意見審查）：order_repo.sweep_expired_pending_orders
    # 讓路後，有 trade_id 的 pending 單不再被 1 小時 cleanup 標 expired（歸對帳
    # sweep 管），重付窗口因此變成無限——沒有這個 gate，使用者可能對著一張帶舊
    # 價格/舊 invoice_snapshot 的過期單按下付款。expires_at 本身仍照舊在建單時
    # 寫入（1 小時），只是不再由 cleanup 主動改狀態，這裡在 /pay 當下自己補查。
    expires_at = order.get("expires_at")
    if expires_at is not None and expires_at < get_utc_timestamp():
        raise api_error("ORDER_EXPIRED", "Order has expired, please checkout again", 400)

    svc = get_payments91_service()
    # subscriptionProductInfo（91APP 正式環境必填，sandbox 不驗）：訂閱單帶實際週期、
    # 無限期；加購（extra_quota，一次性）帶 periods=1 表達單期扣款。
    is_one_time = order.get("type") == "extra_quota"
    resp = await svc.create_first_payment(
        txn_token=request.txn_token,
        order_no=order["merchant_order_no"],
        consumer_id=user_id,
        amount=order["amount_twd"],
        redirect_url=_redirect_url(order["merchant_order_no"]),
        callback_url=_callback_url(),
        prod_name=f"SoundLite {str(order.get('tier', '')).capitalize()} 方案",
        billing_cycle=order.get("billing_cycle") or "monthly",
        periods=1 if is_one_time else None,
    )

    # 診斷用：91APP 非成功回應記錄 errorCode/message/statusCode（不含卡號等敏感資料）
    if not resp.get("statusCode") or resp.get("statusCode") != "Success":
        log.warning(
            "subscription.pay.provider_response",
            order_no=order["merchant_order_no"],
            http_status=resp.get("_http_status"),
            status_code=resp.get("statusCode"),
            error_code=resp.get("errorCode"),
            message=resp.get("message"),
        )

    # P1-9（金流體檢）：trade_id 提前到 order_updates 組裝之前落庫。3DS 分支在下面
    # `paymentUrl` 檢查後就直接 return，原本 trade_id 只在「無 3D 立即收斂」分支才
    # 讀取——3DS 單（正是 callback 遺失的高風險族群：使用者導去銀行頁面，回來後靠
    # /callback 完成，中途逾時 500 就沒人重送）身上因此從未落庫過 trade_id，對帳
    # sweep（payment_reconciliation.py）找不到 trade_id 就沒法主動回查。現在無論
    # 是否走 3D，只要回應帶得出 tradeId 就一併寫回 order。
    trade_id = _find(resp, "tradeid") or ""

    # 捕捉 cardToken（僅在 3D 成功後才有效；settle 時才搬進 subscription）+ 卡別/末四碼（收據用）。存於 order。
    card_token = _find(resp, "cardtoken")
    order_updates = {}
    if trade_id:
        order_updates["trade_id"] = str(trade_id)
    if card_token:
        # P2-10（金流體檢）：明文從 91APP 進 DB 的入口，落庫前一律加密（AES-256-GCM）。
        # F2：加密失敗回 None（不阻擋同批 trade_id 落庫），略過 card_token。
        enc = _encrypt_card_token_safe(str(card_token), order["merchant_order_no"], "pay")
        if enc:
            order_updates["card_token"] = enc
    else:
        log.warning("subscription.pay.no_card_token", order_no=order["merchant_order_no"])
    card_brand = _find(resp, "cardbrand")
    card_last4 = _find(resp, "lastfour")
    if card_brand:
        order_updates["card_brand"] = str(card_brand)
    if card_last4:
        order_updates["card_last4"] = str(card_last4)
    if order_updates:
        await order_repo.update_by_order_no(order["merchant_order_no"], order_updates)

    payment_url = _find(resp, "paymenturl")
    if payment_url:
        return {"payment_url": payment_url, "status": "pending_3ds"}

    # 無 3D → 依 statusCode 直接收斂
    status_code = resp.get("statusCode") or "Unknown"
    success = status_code == "Success"
    outcome = await _process_payment_result(
        db, trade_id=trade_id, record_status=status_code,
        order_no=order["merchant_order_no"], success=success,
    )
    return {
        "payment_url": None,
        "status": "success" if success else "failed",
        "outcome": outcome,
        "message": None if success else (resp.get("message") or status_code),
    }


@router.post("/callback")
async def payment_callback(request: Request, db=Depends(get_database)):
    """91APP 交易結果通知（server-to-server）。

    防禦設計：**不信任 payload**，只取 tradeId → 回查 GET /v2/trades/{tradeId} 為準 → settle。

    🔴 成交判定以回查的 **recordStatus**（付款結果）為準，**不是** statusCode——後者在回查回應
    是「查詢是否成功」（trade 存在即 Success），誤用會讓任何 callback 一律判成功。
    綁卡類（BindingCard）的成敗以回查回應（`trade`，我方簽章保護的通道）的 bindingStatus 為準，
    採負向 gate（欄位不存在＝不擋，fail-open）；payload 的 bindingStatus 未認證，僅記 log 不判定。
    order 缺 card_token 時同樣 fail-open（不判失敗）——cardToken 可能在 3D 完成「之後」才產生
    （見 docs/PAYMENT_91APP_ADMIN_BACKEND_REFERENCE.md），/pay 同步 response 拿不到不代表沒綁卡
    成功；改用回查回應補救寫回 order，寫不到則告警，續扣時 renewal_service 的 NoCardToken →
    needs_card_update dunning 是既有兜底（體檢 P1-8/第二意見 F1）。
    """
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        form = await request.form()
        payload = dict(form)

    trade_id = payload.get("tradeId") or payload.get("TradeId") or ""
    if not trade_id:
        log.warning("subscription.callback.no_trade_id", payload_keys=list(payload.keys()))
        return {"status": "ignored"}

    if not isinstance(trade_id, str) or not TRADE_ID_RE.fullmatch(trade_id):
        # 未認證 payload 的 tradeId 會直接嵌入回查 path，型別不符/格式不符一律拒絕（不 log 原值）。
        log.warning("subscription.callback.invalid_trade_id", trade_id_type=type(trade_id).__name__)
        return {"status": "ignored"}

    svc = get_payments91_service()
    try:
        trade = await svc.query_trade(trade_id)
    except Exception as e:
        log.error("subscription.callback.query_failed", trade_id=trade_id, error=str(e), exc_info=True)
        raise  # 回 500 讓 91APP 重送

    order_no = _find(trade, "merchantorderid") or ""
    record_status = _find(trade, "recordstatus")  # 權威付款狀態（整數）；勿用 trade.statusCode
    if not order_no:
        log.warning("subscription.callback.no_order_no", trade_id=trade_id, record_status=record_status)
        return {"status": "ignored"}

    outcome = interpret_record_status(record_status)
    if outcome == "pending":
        # 尚未定案（待付款/處理中）→ 不結算，回 200 待 91APP 下次通知（3D 卡片實務多同步定案）
        log.info("subscription.callback.pending", trade_id=trade_id, order_no=order_no, record_status=record_status)
        return {"status": "pending"}
    if outcome == "refunded":
        # P1-5：部分退款(6)/全額退款(7) 有自己獨立的處置語意，完全不走下面的
        # success/fail 判定與 binding gate（那些是給「付款結果」用的，退款是另一種事件）。
        # L9（第二意見審查）：回應形狀改回 {"status": ...} dict，跟其他分支一致
        # （_process_refund 本身仍回傳裸字串，供內部/測試直接斷言 outcome）。
        refund_outcome = await _process_refund(
            db, trade_id=trade_id, record_status=str(record_status), order_no=order_no,
        )
        return {"status": refund_outcome}
    success = outcome == "success"

    # 綁卡類（首購/升級走 BindingCard）：判定來源一律用回查回應（trade，我方簽章保護的通道），
    # 不用 payload——payload 未認證，其 bindingStatus 僅記 log 供比對，不參與判定。
    # gate 僅限綁卡型訂單：續扣（MIT）/加購交易不綁卡，回查若帶非成功 bindingStatus 不得誤殺。
    order_repo = OrderRepository(db)
    order = await order_repo.get_by_order_no(order_no) if success else None
    qb_binding = _find(trade, "bindingstatus")
    payload_binding_status = payload.get("bindingStatus") or payload.get("BindingStatus")
    is_binding_order = bool(order) and order.get("type") in ("subscription", "upgrade_subscription")
    if success and is_binding_order and qb_binding is not None \
            and str(qb_binding).lower() not in ("succeeded", "success"):
        # 負向 gate：只有回查回應明確帶出非成功值才擋；欄位不存在＝不擋（fail-open）。
        log.warning("subscription.callback.binding_failed", trade_id=trade_id, order_no=order_no,
                    query_binding_status=qb_binding, payload_binding_status=payload_binding_status,
                    record_status=record_status)
        success = False

    # order 缺 card_token 不再判失敗（cardToken 可能在 3D 完成「之後」才產生，/pay 同步 response
    # 拿不到不代表沒綁卡成功）：fail-open，先試著從回查回應（可信）補救寫回，寫不到就告警，
    # 續扣時 renewal_service 的 NoCardToken → needs_card_update dunning 是既有兜底。
    # type 白名單含 "renewal"：/update-card 換卡挽回單建單時 card_token 為空，須由此補上新卡
    # token；排程續扣單建單時已從 subscription 帶 token，不會落入此分支。
    # F4（跨 PR 複檢）：只在單尚未結算（status != paid）時補救。settle 成功後 clear_card_token
    # 會 $unset orders 那份，91APP 重送同一封 callback 時 `not order.get("card_token")` 會再度
    # 成立、把密文副本寫回 orders（settle 已 ALREADY_PAID 短路→不再 $unset）→ P2-10 要消除的
    # 「免 CVV 憑證雙份」對這張單永久回歸。paid 單的 token 已安全在 subscription，無須補救。
    if success and order and order.get("status") != "paid" and not order.get("card_token") \
            and order.get("type") in ("subscription", "upgrade_subscription", "renewal"):
        qb_token = _find(trade, "cardtoken") or _find(trade, "bindingtoken")
        enc = _encrypt_card_token_safe(str(qb_token), order_no, "callback") if qb_token else None
        if enc:
            # P2-10（金流體檢）：同樣是明文從 91APP 進 DB 的入口，落庫前加密。
            # F2：加密失敗回 None，略過寫回（此段在 settle 之前，拋出會阻斷結算）。
            await order_repo.update_by_order_no(order_no, {"card_token": enc})
        else:
            log.warning("subscription.callback.no_card_token_captured", trade_id=trade_id, order_no=order_no)
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("webhook.order_no", order_no)
                    sentry_sdk.capture_message(
                        "subscription.callback.no_card_token_captured", level="warning")
            except ImportError:
                pass

    log.info("subscription.callback.received", trade_id=trade_id, order_no=order_no,
             record_status=record_status, success=success)
    await _process_payment_result(
        db, trade_id=trade_id, record_status=str(record_status),
        order_no=order_no, success=success,
    )
    return {"status": "ok"}


@router.get("/payment-return")
async def payment_return(order_no: str = ""):
    """3D 完成後 91APP 導回的後端端點，303 轉回前端 SPA。實際結算由 /callback 完成。"""
    return RedirectResponse(
        url=f"{FRONTEND_URL}/payment/return?order_no={order_no}", status_code=303
    )


@router.get("/status")
async def get_subscription_status(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """查詢訂閱狀態"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}
    extra_quota = full_user.get("extra_quota", {}) if full_user else {}
    invoice_info = full_user.get("invoice_info", {}) if full_user else {}

    status = sub.get("status", "free")
    # past_due（Dunning 寬限期）仍視為有訂閱、保留服務；附寬限截止供前端橫幅
    grace_deadline = None
    if status == "past_due" and sub.get("dunning_started_at"):
        from ..services.renewal_service import GRACE_SECONDS
        grace_deadline = sub["dunning_started_at"] + GRACE_SECONDS

    return {
        "has_subscription": status in ("active", "past_due"),
        "status": status,
        "tier": sub.get("tier", "free"),
        "billing_cycle": sub.get("billing_cycle"),
        "current_period_end": sub.get("current_period_end"),
        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
        "pending_plan_change": sub.get("pending_plan_change"),
        # Dunning（付款失敗寬限期）狀態，供前端顯示橫幅 + 換卡 CTA
        "past_due": status == "past_due",
        "needs_card_update": sub.get("needs_card_update", False),
        "grace_deadline": grace_deadline,
        "extra_quota": {
            "duration_minutes": extra_quota.get("duration_minutes", 0),
            "ai_summaries": extra_quota.get("ai_summaries", 0),
        },
        "invoice_info": invoice_info,
    }


@router.post("/cancel")
async def cancel_subscription(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """取消訂閱（期末生效）。91APP 商戶自扣：取消 = 停止排程續扣，無 gateway 委託可終止。"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    # past_due（付款失敗寬限期）也允許取消——停止續扣重試，寬限滿 lapse 為 free
    if sub.get("status") not in ("active", "past_due"):
        raise api_error("SUBSCRIPTION_NOT_ACTIVE", "No active subscription", 400)
    if sub.get("cancel_at_period_end"):
        raise api_error("SUBSCRIPTION_ALREADY_SCHEDULED_CANCEL", "Subscription is already scheduled for cancellation", 400)

    # P0-2(b)（第二意見審查 F2）：dotted $set + guard，不再整包覆寫。guard 用
    # next_charge_at 當版本 token——期末 sweep 若剛好續扣成功會推進它，若使用者手上這份
    # 快照已經過期，寧可回 409 讓前端重新整理，也不能把續扣後的新狀態整包蓋掉。
    ok = await user_repo.update_subscription_fields(
        str(current_user["_id"]),
        {"cancel_at_period_end": True, "canceled_at": get_utc_timestamp(),
         "updated_at": get_utc_timestamp()},
        guard={"subscription.next_charge_at": sub.get("next_charge_at")},
    )
    if not ok:
        raise api_error(
            "SUBSCRIPTION_CONCURRENT_UPDATE",
            "Subscription state has changed, please refresh and try again",
            status.HTTP_409_CONFLICT,
        )

    # 取消已排定確認信：只在 guard-ok（真的排定了取消）之後才寄；409 併發衝突分支
    # 不會走到這裡。best-effort、背景觸發，絕不阻塞/影響本端點的成功回應。
    period_end_val = sub.get("current_period_end")
    period_end = (
        datetime.utcfromtimestamp(period_end_val).strftime("%Y-%m-%d")
        if period_end_val else ""
    )
    # 用 full_user（DB doc）而非 current_user：後者由 get_current_user 從 JWT claim 組成,
    # 只有 email/role,沒有 preferences → 語系會永遠 fallback zh-TW,en 使用者收到繁中信。
    # full_user 同時有 email 與 preferences.language。
    _trigger_cancel_scheduled_email(full_user or current_user, sub, period_end)

    return {"message": "訂閱將於目前計費週期結束時取消"}


def _trigger_cancel_scheduled_email(user: dict, sub: dict, period_end: str) -> None:
    """取消已排定確認信背景觸發（比照 order_settlement 的 create_background_task
    模式）。呼叫端零負擔（同步方法，不 await）。"""
    create_background_task(
        _send_cancel_scheduled_email_task(user, sub.get("tier"), period_end),
        name=f"cancel_scheduled_email:{user.get('_id')}",
    )


async def _send_cancel_scheduled_email_task(user: dict, tier: Optional[str], period_end: str) -> None:
    """背景寄送「已排定取消」確認信（best-effort，絕不拋例外）。"""
    try:
        to = user.get("email")
        if not to or user.get("email_bounced"):
            return
        lang = (user.get("preferences") or {}).get("language", "zh-TW")
        try:
            if lang == "en":
                plan = str(QuotaTier(tier).value).capitalize()
            else:
                plan = QUOTA_TIERS[QuotaTier(tier)]["name"]
        except (ValueError, KeyError):
            plan = str(tier).capitalize()

        from ..utils.email_service import get_email_service
        svc = get_email_service()
        await svc.send_subscription_email(
            to_email=to, kind="cancel_scheduled", lang=lang,
            plan=plan, period_end=period_end,
        )
    except Exception as e:
        log.error(
            "subscription.cancel_scheduled_email.failed",
            user_id=str(user.get("_id")), error=str(e), exc_info=True,
        )


@router.post("/update-card")
async def update_card(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """past_due 換卡挽回：建 recovery order（type=renewal）回 SDK 參數。

    前端接著用既有 /pay 送新卡 txnToken（request-by-txnToken 綁新卡）→ 3D → /callback →
    settle 續扣分支（回 active、清 dunning、搬新 card_token）。
    """
    user_repo = UserRepository(db)
    user_id = str(current_user["_id"])
    full_user = await user_repo.get_by_id(user_id)
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "past_due":
        raise api_error("SUBSCRIPTION_NOT_PAST_DUE", "No payment recovery needed", 400)

    svc = get_payments91_service()
    amount = svc.get_subscription_price(sub.get("tier"), sub.get("billing_cycle"))
    if not amount:
        raise api_error("SUBSCRIPTION_PRICE_NOT_CONFIGURED", "Price is not configured", 500)

    # recovery order 用 type=renewal（與續扣同分支），直接建（非 open_pending，免連點冷卻）
    order_no = generate_order_no("SLREC")
    await OrderRepository(db).create({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "renewal",
        "tier": sub.get("tier"),
        "billing_cycle": sub.get("billing_cycle"),
        "amount_twd": amount,
        "status": "pending",
        "card_token": None,
        # 換卡挽回沒有 request model 帶發票欄位，快照當下 user.invoice_info（經 key 對映）。
        "invoice_snapshot": build_invoice_snapshot_from_user_invoice_info(full_user.get("invoice_info")),
    })
    return {
        "order_no": order_no,
        "amount": amount,
        "publishable_key": svc.publishable_key,
        "sdk_server_type": svc.sdk_server_type,
    }


@router.post("/reactivate")
async def reactivate_subscription(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """重新啟用已排定取消的訂閱：清 cancel_at_period_end。

    91APP merchant-initiated：取消只是停止排程續扣、未終止任何 gateway 委託，故重啟
    = 清旗標即可（訂閱仍 active，期末由 renewal_service 續扣），無需重新付款。
    """
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "active":
        raise api_error("SUBSCRIPTION_NOT_ACTIVE", "No active subscription", 400)
    if not sub.get("cancel_at_period_end"):
        raise api_error("SUBSCRIPTION_NOT_SCHEDULED_CANCEL", "Subscription is not scheduled for cancellation", 400)

    # P0-2(b)（F2）：dotted $set + guard，理由同 /cancel。
    ok = await user_repo.update_subscription_fields(
        str(current_user["_id"]),
        {"cancel_at_period_end": False, "canceled_at": None,
         "updated_at": get_utc_timestamp()},
        guard={"subscription.next_charge_at": sub.get("next_charge_at")},
    )
    if not ok:
        raise api_error(
            "SUBSCRIPTION_CONCURRENT_UPDATE",
            "Subscription state has changed, please refresh and try again",
            status.HTTP_409_CONFLICT,
        )
    return {"message": "訂閱已恢復，將於下個計費週期正常續扣"}


@router.post("/change")
async def change_plan(
    request: ChangePlanRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """變更方案。升級：立即付款（SDK），回 SDK 參數。降級：期末生效（寫 pending_plan_change，不扣款）。"""
    if request.tier not in ("basic", "pro"):
        raise api_error("SUBSCRIPTION_INVALID_TIER", "Invalid subscription plan", 400)
    if request.billing not in ("monthly", "yearly"):
        raise api_error("SUBSCRIPTION_INVALID_BILLING_CYCLE", "Invalid billing cycle", 400)

    user_repo = UserRepository(db)
    user_id = str(current_user["_id"])
    full_user = await user_repo.get_by_id(user_id)
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") not in ("active", "past_due"):
        raise api_error("SUBSCRIPTION_NOT_ACTIVE", "No active subscription", 400)
    current_tier = sub.get("tier", "free")
    if request.tier == current_tier and request.billing == sub.get("billing_cycle"):
        raise api_error("SUBSCRIPTION_NO_CHANGE", "Already on this plan", 400)

    svc = get_payments91_service()
    amount = svc.get_subscription_price(request.tier, request.billing)
    if not amount:
        raise api_error("SUBSCRIPTION_PRICE_NOT_CONFIGURED", "Price is not configured", 500)

    if is_upgrade(current_tier, request.tier):
        # 升級：立即付款（SDK）。結轉舊方案剩餘額度進 extra_quota。
        usage = full_user.get("usage", {})
        quota = full_user.get("quota", {})
        old_dur = quota.get("max_duration_minutes", QUOTA_TIERS[QuotaTier(current_tier)]["max_duration_minutes"])
        old_ai = quota.get("max_ai_summaries", QUOTA_TIERS[QuotaTier(current_tier)]["max_ai_summaries"])
        remaining_dur = round(max(0.0, old_dur - usage.get("duration_minutes", 0)), 1)
        remaining_ai = max(0, old_ai - usage.get("ai_summaries", 0))

        order_no = generate_order_no("SLUPG")
        await OrderRepository(db).create({
            "user_id": user_id,
            "merchant_order_no": order_no,
            "type": "upgrade_subscription",
            "tier": request.tier,
            "billing_cycle": request.billing,
            "amount_twd": amount,
            "status": "pending",
            "card_token": None,
            "prev_order_no": sub.get("active_order_no"),
            "extra_duration_minutes": remaining_dur,
            "extra_ai_summaries": remaining_ai,
            "invoice_snapshot": build_invoice_snapshot_from_request(request),
        })
        await _handle_invoice_save(request, user_id, user_repo)
        return {
            "action": "upgrade",
            "order_no": order_no,
            "amount": amount,
            "publishable_key": svc.publishable_key,
            "sdk_server_type": svc.sdk_server_type,
            "extra_duration_minutes": remaining_dur,
            "extra_ai_summaries": remaining_ai,
        }

    # 降級（basic←pro；改 free 請用 /cancel）：期末生效，只寫 pending_plan_change，不扣款
    # P0-2(b)（F2）：dotted $set + guard。失敗場景舉例（F2 審查意見）：使用者在這裡讀到
    # 舊快照，同時期末 sweep 續扣成功把 tier/billing_cycle/next_charge_at 都推進到新一期
    # → 若整包覆寫，會把 tier 退回舊方案、next_charge_at 退回過去，變成「付新方案的錢
    # 卻享舊方案、且永遠不再被排入續扣」。guard 命中 next_charge_at 版本 token 不符時
    # 回 409，讓前端重新整理拿最新狀態再送一次。
    ok = await user_repo.update_subscription_fields(
        user_id,
        {"pending_plan_change": {
            "tier": request.tier,
            "billing_cycle": request.billing,
            "requested_at": get_utc_timestamp(),
        }, "updated_at": get_utc_timestamp()},
        guard={"subscription.next_charge_at": sub.get("next_charge_at")},
    )
    if not ok:
        raise api_error(
            "SUBSCRIPTION_CONCURRENT_UPDATE",
            "Subscription state has changed, please refresh and try again",
            status.HTTP_409_CONFLICT,
        )
    return {
        "action": "downgrade",
        "effective": "end_of_period",
        "scheduled_date": sub.get("current_period_end"),
    }


@router.post("/cancel-plan-change")
async def cancel_plan_change(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """取消已排定的期末方案變更（降級）→ 維持目前方案。

    pending_plan_change 尚未扣款（降級到期才扣），故清除即可維持現狀。
    """
    user_repo = UserRepository(db)
    user_id = str(current_user["_id"])
    full_user = await user_repo.get_by_id(user_id)
    sub = full_user.get("subscription", {}) if full_user else {}

    if not sub.get("pending_plan_change"):
        raise api_error("SUBSCRIPTION_NO_PENDING_CHANGE", "No scheduled plan change", 400)

    # P0-2(b)（F2）：dotted $set + guard，理由同 /change 降級分支。
    ok = await user_repo.update_subscription_fields(
        user_id,
        {"pending_plan_change": None, "updated_at": get_utc_timestamp()},
        guard={"subscription.next_charge_at": sub.get("next_charge_at")},
    )
    if not ok:
        raise api_error(
            "SUBSCRIPTION_CONCURRENT_UPDATE",
            "Subscription state has changed, please refresh and try again",
            status.HTTP_409_CONFLICT,
        )
    return {"message": "已取消排定的方案變更，維持目前方案"}


@router.post("/purchase-extra")
async def purchase_extra_quota(
    request: PurchaseExtraRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """加購額外額度（立即付款，SDK）。需 active 訂閱。回 SDK 參數。"""
    user_repo = UserRepository(db)
    user_id = str(current_user["_id"])
    full_user = await user_repo.get_by_id(user_id)
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") not in ("active", "past_due"):
        raise api_error("SUBSCRIPTION_REQUIRED_FOR_EXTRA",
                        "An active paid subscription is required to purchase extra quota", 403)

    try:
        pkg = await db.packages.find_one({"_id": ObjectId(request.package_id), "active": True})
    except Exception:
        pkg = None
    if not pkg:
        raise api_error("SUBSCRIPTION_PACKAGE_NOT_FOUND", "Package not found", 404)

    qty = request.quantity
    total_amount = pkg["price_twd"] * qty
    unit = pkg.get("amount", 0)
    svc = get_payments91_service()

    order_no = generate_order_no("SLEXT")
    await OrderRepository(db).create({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "extra_quota",
        "tier": None,
        "billing_cycle": None,
        "amount_twd": total_amount,
        "status": "pending",
        "card_token": None,
        "quantity": qty,                      # 收據明細用
        "unit_price_twd": pkg["price_twd"],    # 單價（收據明細用）
        "sku": pkg.get("sku"),                 # 發票 Description 來源（建單時落庫，不反推）
        "label": pkg.get("label"),
        "extra_duration_minutes": unit * qty if pkg["type"] == "duration" else 0,
        "extra_ai_summaries": unit * qty if pkg["type"] == "ai_summaries" else 0,
        "invoice_snapshot": build_invoice_snapshot_from_request(request),
    })
    await _handle_invoice_save(request, user_id, user_repo)
    return {
        "order_no": order_no,
        "amount": total_amount,
        "publishable_key": svc.publishable_key,
        "sdk_server_type": svc.sdk_server_type,
    }


@router.get("/order/{order_no}")
async def get_order_status(
    order_no: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """查單一訂單狀態/類型（付款完成頁輪詢用）。只能查自己的單。"""
    order = await OrderRepository(db).get_by_order_no(order_no)
    if not order or order.get("user_id") != str(current_user["_id"]):
        raise api_error("ORDER_NOT_FOUND", "Order not found", 404)
    return {
        "order_no": order_no,
        "type": order.get("type"),
        "status": order.get("status"),
        "tier": order.get("tier"),
    }


@router.get("/order/{order_no}/receipt")
async def download_receipt(
    order_no: str,
    lang: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """下載付款收據 PDF（付款證明，非統一發票）。僅限本人的已付款訂單。

    lang：'zh-TW' | 'en'；未指定時用使用者語言偏好，預設繁中。
    """
    order = await OrderRepository(db).get_by_order_no(order_no)
    if not order or order.get("user_id") != str(current_user["_id"]):
        raise api_error("ORDER_NOT_FOUND", "Order not found", 404)
    if order.get("status") != "paid":
        raise api_error("ORDER_NOT_PAID", "Receipt available only for paid orders", 400)

    if lang not in ("zh-TW", "en"):
        lang = (current_user.get("preferences") or {}).get("language", "zh-TW")

    from ..utils.pdf.receipt_generator import generate_receipt_pdf
    pdf = generate_receipt_pdf(order=order, user=current_user, lang=lang)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="receipt_{order_no}.pdf"'},
    )


@router.get("/tiers")
async def list_tiers():
    """方案功能與額度（feature flags + limits）的唯一真實來源，供前端方案頁顯示。

    免登入。價格不在此回傳——價格綁金流設定（見前端 pricing.js）。
    """
    return {"tiers": public_tier_plans()}


@router.get("/packages")
async def list_packages(db=Depends(get_database)):
    """列出所有可購買的額外額度套餐"""
    cursor = db.packages.find({"active": True}).sort("sort_order", 1)
    packages = await cursor.to_list(length=50)
    for p in packages:
        p["_id"] = str(p["_id"])
    return {"packages": packages}


@router.get("/orders")
async def list_orders(
    # le=50：發票 join 用 order_no $in 批查（invoice_repo.list_by_order_nos，
    # to_list 上限 1000），limit 無上限會讓超大頁靜默截斷發票欄位
    limit: int = Query(6, ge=1, le=50),
    skip: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """查詢用戶付款紀錄（只回傳 paid / failed，排除 pending）"""
    order_repo = OrderRepository(db)
    orders = await order_repo.list_by_user(
        str(current_user["_id"]),
        limit=limit + 1,
        skip=skip,
        statuses=["paid", "failed"],
    )
    has_more = len(orders) > limit
    orders = orders[:limit]

    # 附掛發票摘要（設計 §4.3）：一次 `$in` 撈這一頁全部訂單的 invoices，記憶體組裝，
    # 避免每筆訂單各查一次的 N+1（使用者的訂單數量少，不需要 aggregation）。
    order_nos = [o["merchant_order_no"] for o in orders if o.get("merchant_order_no")]
    invoices_by_order: dict = {}
    if order_nos:
        invoice_repo = InvoiceRepository(db)
        for inv in await invoice_repo.list_by_order_nos(order_nos):
            invoices_by_order.setdefault(inv["order_no"], []).append(inv)

    # 欄位白名單：不可整包 order doc 下發——內含 card_token（91APP 免 CVV 續扣憑證，
    # 洩進瀏覽器/前端等於擴大可扣款憑證的暴露面）與 trade_id 等內部欄位。
    # 比照 admin 詳情的 _ORDER_DETAIL_FIELDS 手法（PR-B 驗收 finding #1，同因）。
    _USER_ORDER_FIELDS = (
        "merchant_order_no", "type", "tier", "billing_cycle", "amount_twd",
        "status", "created_at", "paid_at", "card_brand", "card_last4",
        "quantity", "unit_price_twd", "extra_duration_minutes", "extra_ai_summaries",
    )
    result = []
    for o in orders:
        row = {k: o.get(k) for k in _USER_ORDER_FIELDS if k in o}
        row["_id"] = str(o["_id"])
        row["invoice"] = pick_user_facing_invoice(invoices_by_order.get(o.get("merchant_order_no"), []))
        result.append(row)
    return {"orders": result, "has_more": has_more}
