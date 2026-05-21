"""訂閱管理路由（藍新金流）"""
import os
from datetime import datetime, date, timedelta

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.order_repo import OrderRepository
from ..database.repositories.processed_webhook_repo import ProcessedWebhookRepository
from ..models.quota import QuotaTier, QUOTA_TIERS, is_upgrade
from ..utils.newebpay_service import get_newebpay_service, NewebpayService
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])
log = get_logger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


# ── 輔助函式 ────────────────────────────────────────────────────────────────

def _build_quota_from_tier(tier: str) -> dict:
    tier_enum = QuotaTier(tier)
    tier_config = QUOTA_TIERS[tier_enum]
    return {
        "tier": tier,
        **{k: v for k, v in tier_config.items() if k not in ("name", "price")},
    }


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
        raise HTTPException(status_code=400, detail="無效的方案")
    if request.billing not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="無效的計費週期")

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") in ("active", "trialing"):
        raise HTTPException(status_code=400, detail="已有有效訂閱，請使用變更方案功能")

    svc = get_newebpay_service()
    amount = svc.get_subscription_price(request.tier, request.billing)
    if not amount:
        raise HTTPException(status_code=500, detail="價格尚未設定")

    user_id = str(current_user["_id"])
    order_repo = OrderRepository(db)

    if await order_repo.has_pending_order(user_id, "subscription"):
        raise HTTPException(status_code=429, detail="已有進行中的訂閱付款，請稍後再試")

    order_no = svc.generate_order_no("SLSUB")
    await order_repo.create({
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
        raise HTTPException(status_code=400, detail="沒有有效的訂閱")
    if sub.get("cancel_at_period_end"):
        raise HTTPException(status_code=400, detail="訂閱已排定取消")

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
        raise HTTPException(status_code=400, detail="沒有有效的訂閱")
    if not sub.get("cancel_at_period_end"):
        raise HTTPException(status_code=400, detail="訂閱未排定取消")

    # 由於藍新定期定額已終止，重新啟用需要用戶重新付款
    # 回傳 checkout 資料讓前端帶用戶重新訂閱
    tier = sub.get("tier", "basic")
    billing = sub.get("billing_cycle", "monthly")
    svc = get_newebpay_service()
    amount = svc.get_subscription_price(tier, billing)
    if not amount:
        raise HTTPException(status_code=500, detail="價格尚未設定")

    user_id = str(current_user["_id"])
    order_no = svc.generate_order_no("SLSUB")
    order_repo = OrderRepository(db)
    await order_repo.create({
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
        raise HTTPException(status_code=400, detail="無效的方案")
    if request.billing not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="無效的計費週期")

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if sub.get("status") != "active":
        raise HTTPException(status_code=400, detail="沒有有效的訂閱")

    current_tier = sub.get("tier", "free")
    upgrading = is_upgrade(current_tier, request.tier)

    svc = get_newebpay_service()
    amount = svc.get_subscription_price(request.tier, request.billing)
    if not amount:
        raise HTTPException(status_code=500, detail="價格尚未設定")

    user_id = str(current_user["_id"])
    await _handle_invoice_save(request, user_id, user_repo)
    order_repo = OrderRepository(db)

    upgrade_type = "upgrade_subscription" if upgrading else "downgrade_subscription"
    if await order_repo.has_pending_order(user_id, upgrade_type):
        raise HTTPException(status_code=429, detail="已有進行中的方案變更付款，請稍後再試")

    if upgrading:
        # ── 升級：立即付款，Notify 成功後舊合約取消、剩餘額度→extra_quota ──
        usage = full_user.get("usage", {})
        quota = full_user.get("quota", {})
        QT, QTE = QUOTA_TIERS, QuotaTier
        old_limit_dur = quota.get("max_duration_minutes", QT[QTE(current_tier)]["max_duration_minutes"])
        old_limit_ai = quota.get("max_ai_summaries", QT[QTE(current_tier)]["max_ai_summaries"])
        remaining_dur = max(0.0, old_limit_dur - usage.get("duration_minutes", 0))
        remaining_ai = max(0, old_limit_ai - usage.get("ai_summaries", 0))

        order_no = svc.generate_order_no("SLUPG")
        await order_repo.create({
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
            await order_repo.create({
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
            await order_repo.create({
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
        raise HTTPException(status_code=403, detail="需要有效的付費訂閱才能購買額外額度")

    # 從 packages collection 取得套餐資訊
    package = await db.packages.find_one({"_id": ObjectId(request.package_id), "active": True})
    if not package:
        raise HTTPException(status_code=404, detail="套餐不存在")

    user_id = str(current_user["_id"])
    await _handle_invoice_save(request, user_id, user_repo)

    svc = get_newebpay_service()
    order_repo = OrderRepository(db)

    if await order_repo.has_pending_order(user_id, "extra_quota"):
        raise HTTPException(status_code=429, detail="已有進行中的額外額度購買，請稍後再試")

    order_no = svc.generate_order_no("SLEXT")
    await order_repo.create({
        "user_id": user_id,
        "merchant_order_no": order_no,
        "type": "extra_quota",
        "tier": None,
        "billing_cycle": None,
        "amount_twd": package["price_twd"],
        "status": "pending",
        "period_no": None,
        "auth_times": 0,
        "newebpay_trade_no": None,
        "extra_duration_minutes": package.get("amount", 0) if package["type"] == "duration" else 0,
        "extra_ai_summaries": package.get("amount", 0) if package["type"] == "ai_summaries" else 0,
    })

    invoice_params = {
        "carrier_type": request.carrier_type or "",
        "carrier_num": request.carrier_num or "",
        "buyer_uni_num": request.company_tax_id or "",
        "buyer_name": request.company_name or "",
    }

    form = svc.create_mpg_form(
        order_no=order_no,
        amount_twd=package["price_twd"],
        item_desc=package["label"],
        email=current_user["email"],
        return_url=_return_url(),
        notify_url=_notify_url("mpg"),
        **invoice_params,
    )
    return {"form": form, "order_no": order_no}


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

    # 冪等性：每期授權的 natural_id = order + already_times，重複到達直接略過
    # 避免重發 Notify 造成重複授信、period_end 多滾一期等問題
    webhook_repo = ProcessedWebhookRepository(db)
    natural_id = f"{merchant_order_no}:{already_times if already_times is not None else 'init'}"
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

    # 已 claim → 進入處理。若中途失敗：釋放 claim + 送 Sentry，讓藍新重發能重做
    try:
        order_repo = OrderRepository(db)
        order = await order_repo.get_by_order_no(merchant_order_no)
        if not order:
            log.warning("subscription.webhook.order_not_found", merchant_order_no=merchant_order_no)
            return {"status": "ok"}

        # 冪等性保護：首次付款若 order 已是 paid，直接跳過避免重複處理
        if is_first_payment and order.get("status") == "paid":
            log.warning("subscription.webhook.order_already_paid", merchant_order_no=merchant_order_no)
            return {"status": "ok"}

        user_repo = UserRepository(db)
        user_id = order["user_id"]

        if notify_status == "SUCCESS":
            await order_repo.update_by_order_no(merchant_order_no, {
                "period_no": period_no,
                "auth_times": already_times or 1,
                "newebpay_trade_no": trade_no,
            })

            order_type = order.get("type", "subscription")

            if order_type in ("subscription", "upgrade_subscription"):
                await _handle_subscription_paid(
                    db, user_repo, order_repo, order, user_id,
                    period_no, is_first_payment, trade_no
                )
            elif order_type == "downgrade_subscription":
                await _handle_downgrade_paid(
                    db, user_repo, order_repo, order, user_id,
                    period_no, is_first_payment
                )

        else:
            await order_repo.update_by_order_no(merchant_order_no, {"status": "failed"})
            if not is_first_payment:
                # 續扣失敗（非首次付款）→ 立即降為 free
                await _handle_payment_failed(db, user_repo, user_id)

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


async def _handle_subscription_paid(
    db, user_repo, order_repo, order, user_id,
    period_no, is_first_payment: bool, trade_no
):
    """首次授權成功 or 續扣成功"""
    now = datetime.utcnow()
    tier = order["tier"]
    billing_cycle = order["billing_cycle"]
    order_type = order.get("type", "subscription")
    period_end = NewebpayService.calc_period_end(billing_cycle, now)

    if is_first_payment:
        # ── 首次付款：啟動訂閱 ──────────────────────────────────────────
        if order_type == "upgrade_subscription":
            prev_order_no = order.get("prev_order_no")
            prev_period_no = order.get("prev_period_no")
            if prev_order_no and prev_period_no:
                svc = get_newebpay_service()
                ok, msg = await svc.terminate_period_contract(prev_order_no, prev_period_no)
                if not ok:
                    log.warning("subscription.upgrade.old_contract_terminate_failed", message=msg)

            extra_dur = order.get("extra_duration_minutes", 0)
            extra_ai = order.get("extra_ai_summaries", 0)
            if extra_dur or extra_ai:
                await user_repo.add_extra_quota(user_id, extra_dur, extra_ai)

        subscription = {
            "status": "active",
            "tier": tier,
            "billing_cycle": billing_cycle,
            "current_period_start": now.timestamp(),
            "current_period_end": period_end.timestamp(),
            "cancel_at_period_end": False,
            "canceled_at": None,
            "pending_plan_change": None,
            "payment_provider": "newebpay",
            "active_order_no": order["merchant_order_no"],
            "period_no": period_no,
            "created_at": now.timestamp(),
            "updated_at": now.timestamp(),
        }
        await user_repo.update_subscription(user_id, subscription)
        await user_repo.update_quota(user_id, _build_quota_from_tier(tier))
        await _reset_monthly_usage(db, user_id, now)
        await order_repo.update_by_order_no(
            order["merchant_order_no"], {"status": "paid", "paid_at": now.timestamp()}
        )
        log.info("subscription.activated", user_id=user_id, tier=tier, billing_cycle=billing_cycle)

    else:
        # ── 續扣成功：更新計費週期 ──────────────────────────────────────
        full_user = await user_repo.get_by_id(user_id)
        sub = full_user.get("subscription", {}) if full_user else {}
        sub.update({
            "current_period_start": now.timestamp(),
            "current_period_end": period_end.timestamp(),
            "updated_at": now.timestamp(),
        })
        await user_repo.update_subscription(user_id, sub)
        await _reset_monthly_usage(db, user_id, now)
        log.info("subscription.renewed", user_id=user_id)


async def _handle_downgrade_paid(
    db, user_repo, order_repo, order, user_id, period_no, is_first_payment: bool
):
    """降級定期定額扣款成功"""
    now = datetime.utcnow()
    tier = order["tier"]
    billing_cycle = order["billing_cycle"]
    period_end = NewebpayService.calc_period_end(billing_cycle, now)

    if is_first_payment:
        # ── 首次扣款：正式切換為新方案（保底重試終止舊 Pro）────────────────
        prev_order_no = order.get("prev_order_no")
        prev_period_no = order.get("prev_period_no")
        if prev_period_no and prev_order_no:
            svc = get_newebpay_service()
            ok, msg = await svc.terminate_period_contract(prev_order_no, prev_period_no)
            if not ok:
                log.warning("subscription.downgrade.old_pro_contract_terminate_failed", message=msg)

        subscription = {
            "status": "active",
            "tier": tier,
            "billing_cycle": billing_cycle,
            "current_period_start": now.timestamp(),
            "current_period_end": period_end.timestamp(),
            "cancel_at_period_end": False,
            "canceled_at": None,
            "pending_plan_change": None,
            "payment_provider": "newebpay",
            "active_order_no": order["merchant_order_no"],
            "period_no": period_no,
            "updated_at": now.timestamp(),
        }
        await user_repo.update_subscription(user_id, subscription)
        await user_repo.update_quota(user_id, _build_quota_from_tier(tier))
        await _reset_monthly_usage(db, user_id, now)
        await order_repo.update_by_order_no(
            order["merchant_order_no"], {"status": "paid", "paid_at": now.timestamp()}
        )
        log.info("subscription.downgrade.activated", user_id=user_id, tier=tier)

    else:
        # ── 後續續扣：更新計費週期 ──────────────────────────────────────
        full_user = await user_repo.get_by_id(user_id)
        sub = full_user.get("subscription", {}) if full_user else {}
        sub.update({
            "current_period_start": now.timestamp(),
            "current_period_end": period_end.timestamp(),
            "updated_at": now.timestamp(),
        })
        await user_repo.update_subscription(user_id, sub)
        await _reset_monthly_usage(db, user_id, now)
        log.info("subscription.downgrade.renewed", user_id=user_id)


async def _handle_payment_failed(db, user_repo: UserRepository, user_id: str):
    """續扣失敗：立即降為 free"""
    now = datetime.utcnow()

    full_user = await user_repo.get_by_id(user_id)
    sub = full_user.get("subscription", {}) if full_user else {}
    sub.update({
        "status": "expired",
        "cancel_at_period_end": False,
        "updated_at": now.timestamp(),
    })
    await user_repo.update_subscription(user_id, sub)

    free_quota = _build_quota_from_tier("free")
    await user_repo.update_quota(user_id, free_quota)
    log.warning("subscription.renewal.payment_failed", user_id=user_id)


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
        order_repo = OrderRepository(db)
        order = await order_repo.get_by_order_no(merchant_order_no)
        if not order:
            log.warning("payment.webhook.order_not_found", merchant_order_no=merchant_order_no)
            return {"status": "ok"}

        # 冪等性保護
        if order.get("status") == "paid":
            log.warning("payment.webhook.order_already_paid", merchant_order_no=merchant_order_no)
            return {"status": "ok"}

        user_repo = UserRepository(db)
        user_id = order["user_id"]

        if result == "SUCCESS":
            extra_dur = order.get("extra_duration_minutes", 0)
            extra_ai = order.get("extra_ai_summaries", 0)
            await user_repo.add_extra_quota(user_id, extra_dur, extra_ai)
            await order_repo.update_by_order_no(merchant_order_no, {
                "status": "paid",
                "newebpay_trade_no": trade_no,
                "paid_at": datetime.utcnow().timestamp(),
            })
            log.info("payment.extra_quota.purchased", user_id=user_id, extra_duration_minutes=extra_dur, extra_ai_summaries=extra_ai)
        else:
            await order_repo.update_by_order_no(merchant_order_no, {"status": "failed"})
            log.warning("payment.extra_quota.purchase_failed", user_id=user_id)

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


# ── 輔助 ─────────────────────────────────────────────────────────────────────

async def _reset_monthly_usage(db, user_id: str, now: datetime):
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "usage.transcriptions": 0,
                "usage.duration_minutes": 0,
                "usage.ai_summaries": 0,
                "usage.last_reset": now,
                "updated_at": get_utc_timestamp(),
            }
        }
    )
