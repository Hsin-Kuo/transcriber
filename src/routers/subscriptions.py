"""訂閱管理路由（藍新金流）"""
import os
from datetime import datetime, date, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import Optional

from ..utils.api_errors import api_error

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.order_repo import OrderRepository
from ..database.repositories.processed_webhook_repo import ProcessedWebhookRepository
from ..models.quota import QuotaTier, QUOTA_TIERS, is_upgrade, public_tier_plans
from ..services.order_settlement import build_order_settlement, PaymentNotification
from ..utils.newebpay_service import get_newebpay_service
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])
log = get_logger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


# ── 輔助函式 ────────────────────────────────────────────────────────────────
# 付款狀態機（建單防重、settlement、孤兒收斂、重複完成、tier→quota）已抽到
# src/services/order_settlement.py 的 OrderSettlement。詳見 CONTEXT.md「金流與訂單」。


def _notify_url(path: str) -> str:
    return f"{BACKEND_URL}/subscriptions/notify/{path}"


def _return_url() -> str:
    # 藍新以 Form POST 導回商店，必須先經過後端解密再 redirect 到前端
    return f"{BACKEND_URL}/subscriptions/return"


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


class ChangePlanRequest(BaseModel):
    tier: str
    billing: str
    invoice_type: Optional[str] = None
    carrier_type: Optional[str] = None
    carrier_num: Optional[str] = None
    company_tax_id: Optional[str] = None
    company_name: Optional[str] = None
    save_invoice: bool = True


class PurchaseExtraRequest(BaseModel):
    package_id: str
    quantity: int = Field(default=1, ge=1, le=99)  # 購買份數（1–99）
    invoice_type: Optional[str] = None
    carrier_type: Optional[str] = None
    carrier_num: Optional[str] = None
    company_tax_id: Optional[str] = None
    company_name: Optional[str] = None
    save_invoice: bool = True


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


# ── 訂閱端點 ─────────────────────────────────────────────────────────────────

@router.post("/checkout")
async def create_checkout(
    request: CheckoutRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """建立新訂閱（定期定額表單）"""
    if request.tier not in ("basic", "pro"):
        raise api_error("SUBSCRIPTION_INVALID_TIER", "Invalid subscription plan", 400)
    if request.billing not in ("monthly", "yearly"):
        raise api_error("SUBSCRIPTION_INVALID_BILLING_CYCLE", "Invalid billing cycle", 400)

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") in ("active", "trialing"):
        raise api_error("SUBSCRIPTION_ALREADY_ACTIVE",
                        "You already have an active subscription, please use the change plan feature", 400)

    svc = get_newebpay_service()
    amount = svc.get_subscription_price(request.tier, request.billing)
    if not amount:
        raise api_error("SUBSCRIPTION_PRICE_NOT_CONFIGURED", "Price is not configured", 500)

    user_id = str(current_user["_id"])

    order_no = svc.generate_order_no("SLSUB")
    await build_order_settlement(db).open_pending({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "subscription",
        "tier": request.tier,
        "billing_cycle": request.billing,
        "amount_twd": amount,
        "status": "pending",
        "period_no": None,
        "auth_times": 0,
        "newebpay_trade_no": None,
        "extra_duration_minutes": 0,
        "extra_ai_summaries": 0,
    })

    await _handle_invoice_save(request, user_id, user_repo)

    form = svc.create_period_form(
        order_no=order_no,
        amount_twd=amount,
        billing_cycle=request.billing,
        prod_desc=f"SoundLite {request.tier.capitalize()} 方案",
        payer_email=current_user["email"],
        return_url=_return_url(),
        notify_url=_notify_url("period"),
        start_date=date.today(),
    )
    return {"form": form, "order_no": order_no}


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

    return {
        "has_subscription": sub.get("status") == "active",
        "status": sub.get("status", "free"),
        "tier": sub.get("tier", "free"),
        "billing_cycle": sub.get("billing_cycle"),
        "current_period_end": sub.get("current_period_end"),
        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
        "pending_plan_change": sub.get("pending_plan_change"),
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
    """取消訂閱（期末生效）：終止藍新定期定額合約"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "active":
        raise api_error("SUBSCRIPTION_NOT_ACTIVE", "No active subscription", 400)
    if sub.get("cancel_at_period_end"):
        raise api_error("SUBSCRIPTION_ALREADY_SCHEDULED_CANCEL", "Subscription is already scheduled for cancellation", 400)

    period_no = sub.get("period_no")
    active_order_no = sub.get("active_order_no")
    if period_no and active_order_no:
        svc = get_newebpay_service()
        ok, msg = await svc.terminate_period_contract(active_order_no, period_no)
        if not ok:
            log.warning("subscription.cancel.contract_terminate_failed", message=msg)

    sub["cancel_at_period_end"] = True
    sub["canceled_at"] = get_utc_timestamp()
    sub["updated_at"] = get_utc_timestamp()
    await user_repo.update_subscription(str(current_user["_id"]), sub)

    return {"message": "訂閱將於目前計費週期結束時取消"}


@router.post("/reactivate")
async def reactivate_subscription(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """重新啟用已排定取消的訂閱（重建定期定額）"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "active":
        raise api_error("SUBSCRIPTION_NOT_ACTIVE", "No active subscription", 400)
    if not sub.get("cancel_at_period_end"):
        raise api_error("SUBSCRIPTION_NOT_SCHEDULED_CANCEL", "Subscription is not scheduled for cancellation", 400)

    # 由於藍新定期定額已終止，重新啟用需要用戶重新付款
    # 回傳 checkout 資料讓前端帶用戶重新訂閱
    tier = sub.get("tier", "basic")
    billing = sub.get("billing_cycle", "monthly")
    svc = get_newebpay_service()
    amount = svc.get_subscription_price(tier, billing)
    if not amount:
        raise api_error("SUBSCRIPTION_PRICE_NOT_CONFIGURED", "Price is not configured", 500)

    user_id = str(current_user["_id"])

    order_no = svc.generate_order_no("SLSUB")
    await build_order_settlement(db).open_pending({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "subscription",
        "tier": tier,
        "billing_cycle": billing,
        "amount_twd": amount,
        "status": "pending",
        "period_no": None,
        "auth_times": 0,
        "newebpay_trade_no": None,
        "extra_duration_minutes": 0,
        "extra_ai_summaries": 0,
    })

    form = svc.create_period_form(
        order_no=order_no,
        amount_twd=amount,
        billing_cycle=billing,
        prod_desc=f"SoundLite {tier.capitalize()} 方案（重新啟用）",
        payer_email=current_user["email"],
        return_url=_return_url(),
        notify_url=_notify_url("period"),
        start_date=date.today(),
    )
    return {"form": form, "order_no": order_no, "requires_payment": True}


@router.post("/change")
async def change_plan(
    request: ChangePlanRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """
    變更訂閱方案。
    升級：立即生效，建立新 Pro 定期定額，舊合約於 Notify 確認後取消。
    降級：期末生效，建立 PeriodStartType=2 的 Basic 定期定額（首扣日=Pro到期日）。
    """
    if request.tier not in ("basic", "pro"):
        raise api_error("SUBSCRIPTION_INVALID_TIER", "Invalid subscription plan", 400)
    if request.billing not in ("monthly", "yearly"):
        raise api_error("SUBSCRIPTION_INVALID_BILLING_CYCLE", "Invalid billing cycle", 400)

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "active":
        raise api_error("SUBSCRIPTION_NOT_ACTIVE", "No active subscription", 400)

    current_tier = sub.get("tier", "free")
    upgrading = is_upgrade(current_tier, request.tier)

    svc = get_newebpay_service()
    amount = svc.get_subscription_price(request.tier, request.billing)
    if not amount:
        raise api_error("SUBSCRIPTION_PRICE_NOT_CONFIGURED", "Price is not configured", 500)

    user_id = str(current_user["_id"])
    await _handle_invoice_save(request, user_id, user_repo)
    settlement = build_order_settlement(db)

    if upgrading:
        # ── 升級：立即付款，Notify 成功後舊合約取消、剩餘額度→extra_quota ──
        usage = full_user.get("usage", {})
        quota = full_user.get("quota", {})
        QT, QTE = QUOTA_TIERS, QuotaTier
        old_limit_dur = quota.get("max_duration_minutes", QT[QTE(current_tier)]["max_duration_minutes"])
        old_limit_ai = quota.get("max_ai_summaries", QT[QTE(current_tier)]["max_ai_summaries"])
        # usage.duration_minutes 是累積浮點數，相減會出現長尾小數；
        # 轉為額外額度時四捨五入到小數點後一位（存入 extra_quota 與回傳前端皆用此值）
        remaining_dur = round(max(0.0, old_limit_dur - usage.get("duration_minutes", 0)), 1)
        remaining_ai = max(0, old_limit_ai - usage.get("ai_summaries", 0))

        order_no = svc.generate_order_no("SLUPG")
        await settlement.open_pending({
            "user_id": user_id,
            "merchant_order_no": order_no,
            "type": "upgrade_subscription",
            "tier": request.tier,
            "billing_cycle": request.billing,
            "amount_twd": amount,
            "status": "pending",
            "period_no": None,
            "auth_times": 0,
            "newebpay_trade_no": None,
            "prev_order_no": sub.get("active_order_no"),
            "prev_period_no": sub.get("period_no"),
            "extra_duration_minutes": remaining_dur,
            "extra_ai_summaries": remaining_ai,
        })

        form = svc.create_period_form(
            order_no=order_no,
            amount_twd=amount,
            billing_cycle=request.billing,
            prod_desc=f"SoundLite {request.tier.capitalize()} 方案（升級）",
            payer_email=current_user["email"],
            return_url=_return_url(),
            notify_url=_notify_url("period"),
            start_date=date.today(),
        )
        return {"form": form, "order_no": order_no, "action": "upgrade", "extra_duration_minutes": remaining_dur, "extra_ai_summaries": remaining_ai}

    else:
        # ── 降級：PeriodType=D + PeriodStartType=3（指定首扣日）────────────
        # 注意：PeriodFirstdate 僅在 PeriodType=D + PeriodStartType=3 時有效
        period_end_ts = sub.get("current_period_end")
        if period_end_ts:
            period_end_dt = datetime.utcfromtimestamp(period_end_ts)
            days_until_end = (period_end_dt.date() - date.today()).days
        else:
            days_until_end = 30

        prev_order_no = sub.get("active_order_no")
        prev_period_no = sub.get("period_no")

        if days_until_end < 2:
            # 剩餘 < 2 天，改為立即訂閱新方案
            order_no = svc.generate_order_no("SLDWN")
            await settlement.open_pending({
                "user_id": user_id,
                "merchant_order_no": order_no,
                "type": "downgrade_subscription",
                "tier": request.tier,
                "billing_cycle": request.billing,
                "amount_twd": amount,
                "status": "pending",
                "period_no": None,
                "auth_times": 0,
                "newebpay_trade_no": None,
                "prev_order_no": prev_order_no,
                "prev_period_no": prev_period_no,
                "extra_duration_minutes": 0,
                "extra_ai_summaries": 0,
                "scheduled_date": None,
            })
            form = svc.create_period_form(
                order_no=order_no,
                amount_twd=amount,
                billing_cycle=request.billing,
                prod_desc=f"SoundLite {request.tier.capitalize()} 方案",
                payer_email=current_user["email"],
                return_url=_return_url(),
                notify_url=_notify_url("period"),
                start_date=date.today(),
            )
            effective = "now"
            scheduled_date = None
        else:
            # 排程降級：用 PeriodType=D 搭配 PeriodFirstdate 指定首扣日
            first_date_obj = date.today() + timedelta(days=days_until_end)
            period_first_date = first_date_obj.strftime("%Y/%m/%d")

            order_no = svc.generate_order_no("SLDWN")
            await settlement.open_pending({
                "user_id": user_id,
                "merchant_order_no": order_no,
                "type": "downgrade_subscription",
                "tier": request.tier,
                "billing_cycle": request.billing,
                "amount_twd": amount,
                "status": "pending",
                "period_no": None,
                "auth_times": 0,
                "newebpay_trade_no": None,
                "prev_order_no": prev_order_no,
                "prev_period_no": prev_period_no,
                "extra_duration_minutes": 0,
                "extra_ai_summaries": 0,
                "scheduled_date": period_first_date,
                # 排程降級的 pending 單要存活到首扣日才由期末首扣 Notify 收斂，
                # 不能沿用預設 1 小時 expires_at（否則會被 periodic_order_cleanup 掃成
                # expired）。設到首扣日 +3 天緩衝：期末順利收斂前不被掃、真沒收到才過期。
                "expires_at": get_utc_timestamp() + (days_until_end + 3) * 86400,
            })
            form = svc.create_period_form_scheduled(
                order_no=order_no,
                amount_twd=amount,
                billing_cycle=request.billing,
                prod_desc=f"SoundLite {request.tier.capitalize()} 方案（降級）",
                payer_email=current_user["email"],
                return_url=_return_url(),
                notify_url=_notify_url("period"),
                first_date=period_first_date,
            )
            effective = "end_of_period"
            scheduled_date = period_first_date

        # 立即終止舊 Pro 定期定額，防止到期前再次扣款
        if prev_order_no and prev_period_no:
            ok, msg = await svc.terminate_period_contract(prev_order_no, prev_period_no)
            if ok:
                log.info("subscription.downgrade.old_contract_terminated", prev_period_no=prev_period_no)
            else:
                log.warning("subscription.downgrade.old_contract_terminate_failed", prev_period_no=prev_period_no, message=msg)

        sub["pending_plan_change"] = {
            "tier": request.tier,
            "billing_cycle": request.billing,
            "order_no": order_no,
            "scheduled_date": scheduled_date,
            "requested_at": get_utc_timestamp(),
        }
        sub["updated_at"] = get_utc_timestamp()
        await user_repo.update_subscription(user_id, sub)

        return {
            "form": form,
            "order_no": order_no,
            "action": "downgrade",
            "effective": effective,
            "scheduled_date": scheduled_date,
            "current_period_end": sub.get("current_period_end"),
        }


@router.post("/purchase-extra")
async def purchase_extra_quota(
    request: PurchaseExtraRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """購買額外額度（一次性 MPG）"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "active":
        raise api_error("SUBSCRIPTION_REQUIRED_FOR_EXTRA",
                        "An active paid subscription is required to purchase extra quota", 403)

    # 從 packages collection 取得套餐資訊
    package = await db.packages.find_one({"_id": ObjectId(request.package_id), "active": True})
    if not package:
        raise api_error("SUBSCRIPTION_PACKAGE_NOT_FOUND", "Package not found", 404)

    user_id = str(current_user["_id"])
    await _handle_invoice_save(request, user_id, user_repo)

    svc = get_newebpay_service()

    # 份數：總金額與加購額度皆 × quantity
    qty = request.quantity
    total_amount = package["price_twd"] * qty
    unit_amount = package.get("amount", 0)
    item_desc = package["label"] if qty == 1 else f'{package["label"]} ×{qty}'

    order_no = svc.generate_order_no("SLEXT")
    await build_order_settlement(db).open_pending({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "extra_quota",
        "tier": None,
        "billing_cycle": None,
        "amount_twd": total_amount,
        "status": "pending",
        "period_no": None,
        "auth_times": 0,
        "newebpay_trade_no": None,
        "extra_duration_minutes": unit_amount * qty if package["type"] == "duration" else 0,
        "extra_ai_summaries": unit_amount * qty if package["type"] == "ai_summaries" else 0,
    })

    invoice_params = {
        "carrier_type": request.carrier_type or "",
        "carrier_num": request.carrier_num or "",
        "buyer_uni_num": request.company_tax_id or "",
        "buyer_name": request.company_name or "",
    }

    form = svc.create_mpg_form(
        order_no=order_no,
        amount_twd=total_amount,
        item_desc=item_desc,
        email=current_user["email"],
        return_url=_return_url(),
        notify_url=_notify_url("mpg"),
        **invoice_params,
    )
    return {"form": form, "order_no": order_no}


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


# ── Notify Handler（定期定額） ────────────────────────────────────────────────

@router.post("/notify/period")
async def period_notify(request: Request, db=Depends(get_database)):
    """
    藍新定期定額 Notify（server-to-server）。

    Notify 以 AES 加密的 Period 欄位回傳。
    初次建立（建立完成）與每期授權（NPA-N050）使用相同端點，
    以 Result 中是否存在 AlreadyTimes 欄位來區分。
    """
    form = await request.form()
    raw = dict(form)

    svc = get_newebpay_service()
    payload = svc.decrypt_period_notify(raw)
    if payload is None:
        log.warning("newebpay.period_notify.decrypt_failed")
        return {"status": "error"}

    notify_status = payload.get("Status", "")
    result = payload.get("Result", {})

    merchant_order_no = result.get("MerchantOrderNo") or result.get("MerOrderNo", "")
    period_no = result.get("PeriodNo", "")
    trade_no = result.get("TradeNo", "")

    # 區分初次建立 vs 每期授權：
    # - 建立完成（4.3.2）：Result 包含 AuthTimes（總期數）
    # - 每期授權（4.3.3 NPA-N050）：Result 包含 AlreadyTimes（已完成期數）
    already_times = result.get("AlreadyTimes")
    if already_times is not None:
        try:
            already_times = int(already_times)
        except (ValueError, TypeError):
            already_times = 1
        is_first_payment = (already_times == 1)
    else:
        # 初次建立 Notify → 第一次付款
        is_first_payment = True

    log.info("subscription.webhook.received", merchant_order_no=merchant_order_no, status=notify_status, is_first_payment=is_first_payment)

    # 冪等性 natural_id：
    # - 每期授權（有 AlreadyTimes）：order + already_times，per-period 唯一——絕不併入
    #   TradeNo，否則藍新重送若換號會重複滾 period_end / 重置用量。
    # - 建立完成類（無 AlreadyTimes）：同一 order 的「建約當下」與 type-3「期末首扣」
    #   可能都是這格式，只用 :init 會撞在一起、後到那封被冪等擋掉 → 排程降級卡住不生效。
    #   併入 TradeNo（各次授權唯一）區分不同授權事件；藍新重送同一封仍帶同 TradeNo →
    #   照樣去重。settle() 另有 order 生命週期短路（已 paid），重複套用仍安全。
    webhook_repo = ProcessedWebhookRepository(db)
    if already_times is not None:
        natural_id = f"{merchant_order_no}:{already_times}"
    else:
        natural_id = f"{merchant_order_no}:init:{trade_no}"
    if not await webhook_repo.claim(
        provider="newebpay-period",
        natural_id=natural_id,
        metadata={
            "status": notify_status,
            "period_no": period_no,
            "trade_no": trade_no,
        },
    ):
        log.warning("subscription.webhook.duplicate_skipped", natural_id=natural_id)
        return {"status": "ok"}

    # 已 claim → 進入處理。若中途失敗：釋放 claim + 送 Sentry，讓藍新重發能重做。
    # settle() 負責 order 生命週期 idempotency（order_not_found / 已 paid 短路）
    # 與所有帳號狀態變更——router 只做解密 + claim + 結果記錄。
    try:
        settle_result = await build_order_settlement(db).settle(PaymentNotification(
            order_no=merchant_order_no,
            success=(notify_status == "SUCCESS"),
            is_first_payment=is_first_payment,
            period_no=period_no,
            trade_no=trade_no,
            auth_times=already_times,
        ))
        log.info("subscription.webhook.settled", natural_id=natural_id, outcome=settle_result.outcome.value)
        return {"status": "ok"}
    except Exception as e:
        # 處理失敗：釋放 claim 讓藍新下次重發能重做；送 Sentry 警示需人工檢查
        await webhook_repo.release(provider="newebpay-period", natural_id=natural_id)
        log.error("subscription.webhook.processing_failed", natural_id=natural_id, error=str(e), exc_info=True)
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("webhook.provider", "newebpay-period")
                scope.set_tag("webhook.order_no", merchant_order_no)
                scope.set_context("webhook", {
                    "natural_id": natural_id,
                    "status": notify_status,
                    "is_first_payment": is_first_payment,
                })
                sentry_sdk.capture_exception(e)
        except ImportError:
            pass
        # 回 500 讓藍新重試
        raise


# ── Notify Handler（MPG 一次性） ─────────────────────────────────────────────

@router.post("/notify/mpg")
async def mpg_notify(request: Request, db=Depends(get_database)):
    """藍新 MPG Notify（額外額度購買）"""
    form = await request.form()
    trade_info = form.get("TradeInfo", "")
    trade_sha = form.get("TradeSha", "")

    svc = get_newebpay_service()
    data = svc.verify_and_decrypt_mpg_notify(trade_info, trade_sha)
    if data is None:
        log.warning("newebpay.mpg_notify.verify_failed")
        return {"status": "error"}

    merchant_order_no = data.get("MerchantOrderNo", "")
    result = data.get("Status", "")
    trade_no = data.get("TradeNo", "")

    log.info("payment.webhook.received", merchant_order_no=merchant_order_no, status=result)

    # 冪等性：一次性付款 natural_id 就是訂單號
    webhook_repo = ProcessedWebhookRepository(db)
    if not await webhook_repo.claim(
        provider="newebpay-mpg",
        natural_id=merchant_order_no,
        metadata={"status": result, "trade_no": trade_no},
    ):
        log.warning("payment.webhook.duplicate_skipped", merchant_order_no=merchant_order_no)
        return {"status": "ok"}

    try:
        # MPG 一次性付款一律視為 first；settle() 處理 order_not_found / 已 paid 短路與加值
        settle_result = await build_order_settlement(db).settle(PaymentNotification(
            order_no=merchant_order_no,
            success=(result == "SUCCESS"),
            is_first_payment=True,
            trade_no=trade_no,
        ))
        log.info("payment.webhook.settled", merchant_order_no=merchant_order_no, outcome=settle_result.outcome.value)
        return {"status": "ok"}
    except Exception as e:
        await webhook_repo.release(provider="newebpay-mpg", natural_id=merchant_order_no)
        log.error("payment.webhook.processing_failed", merchant_order_no=merchant_order_no, error=str(e), exc_info=True)
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("webhook.provider", "newebpay-mpg")
                scope.set_tag("webhook.order_no", merchant_order_no)
                sentry_sdk.capture_exception(e)
        except ImportError:
            pass
        raise


# ── Return URL ────────────────────────────────────────────────────────────────

@router.post("/return")
async def payment_return(request: Request):
    """
    藍新付款後以 Form POST 導回此端點。
    解密 Period 欄位，提取 Status 和 MerchantOrderNo，
    再以 GET redirect 帶 query params 導向前端。
    """
    form = await request.form()
    raw = dict(form)

    # 別用 `status` 當變數名：會 shadow 從 fastapi import 的 status enum
    notify_status = "UNKNOWN"
    merchant_order_no = ""

    period_enc = raw.get("Period", "")
    if period_enc:
        svc = get_newebpay_service()
        payload = svc.decrypt_period_notify(raw)
        if payload:
            notify_status = payload.get("Status", "UNKNOWN")
            result = payload.get("Result", {})
            merchant_order_no = (
                result.get("MerchantOrderNo") or result.get("MerOrderNo", "")
            )
    else:
        # MPG ReturnURL 也可能走這裡（TradeInfo + TradeSha）
        trade_info = raw.get("TradeInfo", "")
        trade_sha = raw.get("TradeSha", "")
        if trade_info and trade_sha:
            svc = get_newebpay_service()
            data = svc.verify_and_decrypt_mpg_notify(trade_info, trade_sha)
            if data:
                notify_status = data.get("Status", "UNKNOWN")
                merchant_order_no = data.get("MerchantOrderNo", "")

    query = f"Status={notify_status}&MerchantOrderNo={merchant_order_no}"
    return RedirectResponse(
        url=f"{FRONTEND_URL}/payment/return?{query}",
        status_code=303  # 303 See Other：POST → GET redirect
    )
