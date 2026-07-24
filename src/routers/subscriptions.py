"""訂閱管理路由（91APP Payments）。

首購流程：前端 SDK tokenize → POST /checkout（建 pending 單、回 SDK 參數）→
POST /pay（送 txnToken，後端 request-by-txnToken BindingCard，捕捉 cardToken）→
若回 paymentUrl 走 3D，完成後 91APP 打 POST /callback（不信 payload → 回查交易 → settle）。
續扣（Phase 2）由本地排程器直接呼叫 settle，不經 callback。
"""
import os
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import Optional

from ..utils.api_errors import api_error

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.order_repo import OrderRepository
from ..database.repositories.processed_webhook_repo import ProcessedWebhookRepository
from ..models.quota import public_tier_plans
from ..services.order_settlement import build_order_settlement, PaymentNotification
from ..utils.payments91_service import get_payments91_service
from ..utils.billing_period import generate_order_no
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])
log = get_logger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Phase 1 暫停用的端點統一訊息（升降級/加購/reactivate 在 Phase 3 重做）
_PHASE1_DISABLED = "此功能正在遷移至新金流，暫未開放；如需變更方案請聯繫客服"


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


# ── Request Models ───────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier: str       # "basic" | "pro"
    billing: str    # "monthly" | "yearly"
    invoice_type: Optional[str] = None   # "personal" | "company"
    carrier_type: Optional[str] = None   # "1"=手機條碼
    carrier_num: Optional[str] = None
    company_tax_id: Optional[str] = None
    company_name: Optional[str] = None
    save_invoice: bool = True


class PayRequest(BaseModel):
    order_no: str
    txn_token: str = Field(..., min_length=1)


# ── 發票資訊處理 ─────────────────────────────────────────────────────────────

async def _handle_invoice_save(request_data, user_id: str, user_repo: UserRepository):
    """若 save_invoice=True，將發票資訊存入 user document"""
    if not request_data.save_invoice:
        return
    if request_data.invoice_type == "personal" and request_data.carrier_num:
        await user_repo.update_invoice_info(user_id, {
            "type": "personal",
            "carrier_type": request_data.carrier_type or "1",
            "carrier_num": request_data.carrier_num,
            "company_tax_id": "",
            "company_name": "",
        })
    elif request_data.invoice_type == "company" and request_data.company_tax_id:
        await user_repo.update_invoice_info(user_id, {
            "type": "company",
            "carrier_type": "",
            "carrier_num": "",
            "company_tax_id": request_data.company_tax_id,
            "company_name": request_data.company_name or "",
        })


# ── 付款結果收斂（/pay 立即成交 與 /callback 共用）──────────────────────────────

async def _process_payment_result(
    db, *, trade_id: str, record_status: str, order_no: str, success: bool,
) -> str:
    """claim 去重 → settle。回傳 outcome 字串（或 "duplicate"）。失敗會 release + raise。

    is_first_payment 由 order type 推導：type=renewal（換卡挽回/續扣）走續扣分支，其餘為首期。
    """
    order = await OrderRepository(db).get_by_order_no(order_no)
    is_first_payment = not (order and order.get("type") == "renewal")
    webhook_repo = ProcessedWebhookRepository(db)
    natural_id = f"{trade_id or order_no}:{record_status}"
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
        except ImportError:
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

    svc = get_payments91_service()
    resp = await svc.create_first_payment(
        txn_token=request.txn_token,
        order_no=order["merchant_order_no"],
        consumer_id=user_id,
        amount=order["amount_twd"],
        redirect_url=_redirect_url(order["merchant_order_no"]),
        callback_url=_callback_url(),
        prod_name=f"SoundLite {str(order.get('tier', '')).capitalize()} 方案",
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

    # 捕捉 cardToken（僅在 3D 成功後才有效；settle 時才搬進 subscription）。存於 order。
    card_token = _find(resp, "cardtoken")
    if card_token:
        await order_repo.update_by_order_no(order["merchant_order_no"], {"card_token": card_token})
    else:
        log.warning("subscription.pay.no_card_token", order_no=order["merchant_order_no"])

    payment_url = _find(resp, "paymenturl")
    if payment_url:
        return {"payment_url": payment_url, "status": "pending_3ds"}

    # 無 3D → 依 statusCode 直接收斂
    status_code = resp.get("statusCode") or "Unknown"
    trade_id = _find(resp, "tradeid") or ""
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
    """
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        form = await request.form()
        payload = dict(form)

    trade_id = payload.get("tradeId") or payload.get("TradeId") or ""
    record_status = payload.get("recordStatus") or payload.get("RecordStatus") or ""
    if not trade_id:
        log.warning("subscription.callback.no_trade_id", payload_keys=list(payload.keys()))
        return {"status": "ignored"}

    svc = get_payments91_service()
    try:
        trade = await svc.query_trade(trade_id)
    except Exception as e:
        log.error("subscription.callback.query_failed", trade_id=trade_id, error=str(e), exc_info=True)
        raise  # 回 500 讓 91APP 重送

    order_no = _find(trade, "merchantorderid") or ""
    status_code = trade.get("statusCode") or ""
    if not order_no:
        log.warning("subscription.callback.no_order_no", trade_id=trade_id, status=status_code)
        return {"status": "ignored"}

    success = status_code == "Success"
    log.info("subscription.callback.received", trade_id=trade_id, order_no=order_no, status=status_code)
    await _process_payment_result(
        db, trade_id=trade_id, record_status=record_status or status_code,
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

    sub["cancel_at_period_end"] = True
    sub["canceled_at"] = get_utc_timestamp()
    sub["updated_at"] = get_utc_timestamp()
    await user_repo.update_subscription(str(current_user["_id"]), sub)

    return {"message": "訂閱將於目前計費週期結束時取消"}


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
    })
    return {
        "order_no": order_no,
        "amount": amount,
        "publishable_key": svc.publishable_key,
        "sdk_server_type": svc.sdk_server_type,
    }


@router.post("/reactivate")
async def reactivate_subscription(current_user: dict = Depends(get_current_user)):
    """Phase 1 暫停用（Phase 3 依 91APP 續訂模型重做）。"""
    raise api_error("FEATURE_MIGRATING", _PHASE1_DISABLED, 501)


@router.post("/change")
async def change_plan(current_user: dict = Depends(get_current_user)):
    """Phase 1 暫停用（升降級 Phase 3 重做，含期末降級改本地排程）。"""
    raise api_error("FEATURE_MIGRATING", _PHASE1_DISABLED, 501)


@router.post("/purchase-extra")
async def purchase_extra_quota(current_user: dict = Depends(get_current_user)):
    """Phase 1 暫停用（加購 Phase 3 重做）。"""
    raise api_error("FEATURE_MIGRATING", _PHASE1_DISABLED, 501)


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
    limit: int = 6,
    skip: int = 0,
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
    for o in orders:
        o["_id"] = str(o["_id"])
    return {"orders": orders, "has_more": has_more}
