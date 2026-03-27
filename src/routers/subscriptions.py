"""訂閱管理路由"""
import os
import stripe

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..models.quota import QuotaTier, QUOTA_TIERS, is_upgrade
from ..utils.stripe_service import get_stripe_service
from ..utils.time_utils import get_utc_timestamp

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


# ========== Request Models ==========

class CreateCheckoutRequest(BaseModel):
    tier: str       # "basic" | "pro"
    billing: str    # "monthly" | "yearly"


class ChangePlanRequest(BaseModel):
    tier: str       # "basic" | "pro"
    billing: str    # "monthly" | "yearly"


# ========== Helper ==========

def _build_quota_from_tier(tier: str) -> dict:
    """從 tier 名稱建立完整的 quota dict"""
    tier_enum = QuotaTier(tier)
    tier_config = QUOTA_TIERS[tier_enum]
    return {
        "tier": tier,
        **{k: v for k, v in tier_config.items() if k not in ("name", "price")},
    }


# ========== 需認證的端點 ==========

@router.post("/checkout")
async def create_checkout_session(
    request: CreateCheckoutRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """建立 Stripe Checkout Session（首次訂閱用）"""
    if request.tier not in ("basic", "pro"):
        raise HTTPException(status_code=400, detail="無效的方案")
    if request.billing not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="無效的計費週期")

    stripe_svc = get_stripe_service()
    price_id = stripe_svc.get_price_id(request.tier, request.billing)
    if not price_id:
        raise HTTPException(status_code=500, detail="價格尚未設定")

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}
    stripe_customer_id = sub.get("stripe_customer_id")

    # 已有有效訂閱時應使用 change 端點
    if sub.get("status") in ("active", "trialing"):
        raise HTTPException(status_code=400, detail="已有有效訂閱，請使用變更方案功能")

    session = stripe_svc.create_checkout_session(
        user_id=str(current_user["_id"]),
        user_email=current_user["email"],
        price_id=price_id,
        success_url=f"{FRONTEND_URL}/settings?checkout=success",
        cancel_url=f"{FRONTEND_URL}/settings?checkout=canceled",
        stripe_customer_id=stripe_customer_id,
    )

    return {"checkout_url": session.url, "session_id": session.id}


@router.get("/status")
async def get_subscription_status(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """查詢訂閱狀態"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    return {
        "has_subscription": bool(sub.get("stripe_subscription_id")),
        "status": sub.get("status"),
        "tier": sub.get("tier", "free"),
        "billing_cycle": sub.get("billing_cycle"),
        "current_period_end": sub.get("current_period_end"),
        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
        "pending_plan_change": sub.get("pending_plan_change"),
    }


@router.post("/cancel")
async def cancel_subscription(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """取消訂閱（期末生效）"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if not sub.get("stripe_subscription_id"):
        raise HTTPException(status_code=400, detail="沒有有效的訂閱")

    stripe_svc = get_stripe_service()
    stripe_svc.cancel_subscription(sub["stripe_subscription_id"])

    # 即時更新本地記錄（webhook 也會更新，但先做 eager update）
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
    """重新啟用已排定取消的訂閱"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if not sub.get("stripe_subscription_id"):
        raise HTTPException(status_code=400, detail="沒有有效的訂閱")
    if not sub.get("cancel_at_period_end"):
        raise HTTPException(status_code=400, detail="訂閱未排定取消")

    stripe_svc = get_stripe_service()
    stripe_svc.reactivate_subscription(sub["stripe_subscription_id"])

    sub["cancel_at_period_end"] = False
    sub["canceled_at"] = None
    sub["updated_at"] = get_utc_timestamp()
    await user_repo.update_subscription(str(current_user["_id"]), sub)

    return {"message": "訂閱已重新啟用"}


@router.post("/change")
async def change_plan(
    request: ChangePlanRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """變更訂閱方案（升級立即生效 / 降級期末生效）"""
    if request.tier not in ("basic", "pro"):
        raise HTTPException(status_code=400, detail="無效的方案")
    if request.billing not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="無效的計費週期")

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if not sub.get("stripe_subscription_id"):
        raise HTTPException(status_code=400, detail="沒有有效的訂閱")
    if sub.get("status") != "active":
        raise HTTPException(status_code=400, detail="訂閱不是有效狀態")

    stripe_svc = get_stripe_service()
    new_price_id = stripe_svc.get_price_id(request.tier, request.billing)
    if not new_price_id:
        raise HTTPException(status_code=500, detail="價格尚未設定")

    current_tier = sub.get("tier", "free")
    upgrading = is_upgrade(current_tier, request.tier)

    if upgrading:
        # 升級：立即生效 + proration
        stripe_svc.upgrade_subscription(sub["stripe_subscription_id"], new_price_id)
        # Webhook (customer.subscription.updated) 會處理 quota 更新
        return {"message": "方案已立即升級", "effective": "now"}
    else:
        # 降級：儲存 pending，期末由 invoice.paid webhook 套用
        sub["pending_plan_change"] = {
            "tier": request.tier,
            "price_id": new_price_id,
            "billing_cycle": request.billing,
            "requested_at": get_utc_timestamp(),
        }
        sub["updated_at"] = get_utc_timestamp()
        await user_repo.update_subscription(str(current_user["_id"]), sub)

        return {
            "message": "方案將於目前計費週期結束時降級",
            "effective": "end_of_period",
            "current_period_end": sub.get("current_period_end"),
        }


@router.get("/portal")
async def get_portal_url(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """取得 Stripe Customer Portal URL"""
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    sub = full_user.get("subscription", {}) if full_user else {}

    if not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="沒有 Stripe 客戶記錄")

    stripe_svc = get_stripe_service()
    session = stripe_svc.create_portal_session(
        sub["stripe_customer_id"],
        return_url=f"{FRONTEND_URL}/settings",
    )

    return {"portal_url": session.url}


# ========== Webhook（不需認證，用 Stripe 簽名驗證）==========

@router.post("/webhook")
async def stripe_webhook(request: Request, db=Depends(get_database)):
    """處理 Stripe Webhook 事件"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="缺少 stripe-signature header")

    stripe_svc = get_stripe_service()
    try:
        event = stripe_svc.construct_webhook_event(payload, sig_header)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    user_repo = UserRepository(db)
    event_type = event["type"]
    data = event["data"]["object"]

    print(f"📩 Stripe webhook: {event_type}", flush=True)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data, user_repo, stripe_svc)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data, user_repo, stripe_svc, db)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data, user_repo)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(data, user_repo, stripe_svc)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data, user_repo)

    return {"received": True}


# ========== Webhook Event Handlers ==========

async def _handle_checkout_completed(session: dict, user_repo: UserRepository, stripe_svc):
    """首次訂閱完成：綁定 Stripe Customer，更新 quota"""
    user_id = session.get("client_reference_id") or session.get("metadata", {}).get("user_id")
    if not user_id:
        print("⚠️ checkout.session.completed: 缺少 user_id", flush=True)
        return

    stripe_customer_id = session["customer"]
    stripe_subscription_id = session["subscription"]

    # 從 Stripe 取得訂閱詳情
    sub = stripe.Subscription.retrieve(stripe_subscription_id)
    price_id = sub["items"]["data"][0]["price"]["id"]
    tier, billing_cycle = stripe_svc.resolve_tier_from_price(price_id)

    subscription_data = {
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "stripe_price_id": price_id,
        "status": sub["status"],
        "tier": tier,
        "billing_cycle": billing_cycle,
        "current_period_start": sub["current_period_start"],
        "current_period_end": sub["current_period_end"],
        "cancel_at_period_end": sub.get("cancel_at_period_end", False),
        "canceled_at": None,
        "pending_plan_change": None,
        "created_at": get_utc_timestamp(),
        "updated_at": get_utc_timestamp(),
    }

    await user_repo.update(user_id, {"subscription": subscription_data})

    # 套用新方案的 quota
    if tier != "unknown":
        quota = _build_quota_from_tier(tier)
        await user_repo.update_quota(user_id, quota)
        print(f"✅ 用戶 {user_id} 訂閱成功：{tier} ({billing_cycle})", flush=True)


async def _handle_subscription_updated(sub_obj: dict, user_repo: UserRepository, stripe_svc, db):
    """訂閱變更（方案變更、續約、取消切換等）"""
    customer_id = sub_obj["customer"]
    user = await user_repo.get_by_stripe_customer_id(customer_id)
    if not user:
        print(f"⚠️ subscription.updated: 找不到 customer {customer_id}", flush=True)
        return

    user_id = str(user["_id"])
    price_id = sub_obj["items"]["data"][0]["price"]["id"]
    tier, billing_cycle = stripe_svc.resolve_tier_from_price(price_id)

    existing_sub = user.get("subscription", {})
    old_period_start = existing_sub.get("current_period_start")
    new_period_start = sub_obj["current_period_start"]

    existing_sub.update({
        "stripe_price_id": price_id,
        "status": sub_obj["status"],
        "tier": tier,
        "billing_cycle": billing_cycle,
        "current_period_start": new_period_start,
        "current_period_end": sub_obj["current_period_end"],
        "cancel_at_period_end": sub_obj.get("cancel_at_period_end", False),
        "updated_at": get_utc_timestamp(),
    })

    await user_repo.update(user_id, {"subscription": existing_sub})

    # 同步 quota
    if tier != "unknown":
        quota = _build_quota_from_tier(tier)
        await user_repo.update_quota(user_id, quota)
        print(f"🔄 用戶 {user_id} 訂閱已更新：{tier} ({billing_cycle})", flush=True)

    # 新計費週期開始 → 立即重置用量（eager reset）
    if old_period_start and new_period_start != old_period_start:
        from ..auth.quota import QuotaManager
        await QuotaManager.reset_user_monthly_quota(db, user_id)
        print(f"🔄 用戶 {user_id} 用量已重置（新計費週期）", flush=True)


async def _handle_subscription_deleted(sub_obj: dict, user_repo: UserRepository):
    """訂閱結束（取消到期 or 立即取消）→ 降級為 free"""
    customer_id = sub_obj["customer"]
    user = await user_repo.get_by_stripe_customer_id(customer_id)
    if not user:
        return

    user_id = str(user["_id"])
    existing_sub = user.get("subscription", {})
    existing_sub.update({
        "status": "canceled",
        "cancel_at_period_end": False,
        "pending_plan_change": None,
        "updated_at": get_utc_timestamp(),
    })

    await user_repo.update(user_id, {"subscription": existing_sub})

    # 降級為 free
    free_quota = _build_quota_from_tier("free")
    await user_repo.update_quota(user_id, free_quota)
    print(f"🔻 用戶 {user_id} 訂閱已結束，降級為 free", flush=True)


async def _handle_invoice_paid(invoice: dict, user_repo: UserRepository, stripe_svc):
    """續約付款成功：如有 pending 降級，此時套用"""
    customer_id = invoice["customer"]
    user = await user_repo.get_by_stripe_customer_id(customer_id)
    if not user:
        return

    user_id = str(user["_id"])
    sub = user.get("subscription", {})
    pending = sub.get("pending_plan_change")

    if pending:
        # 套用降級：修改 Stripe subscription 的 price
        subscription = stripe.Subscription.retrieve(sub["stripe_subscription_id"])
        item_id = subscription["items"]["data"][0]["id"]

        stripe.Subscription.modify(
            sub["stripe_subscription_id"],
            items=[{"id": item_id, "price": pending["price_id"]}],
            proration_behavior="none",
        )

        sub["pending_plan_change"] = None
        sub["updated_at"] = get_utc_timestamp()
        await user_repo.update(user_id, {"subscription": sub})
        print(f"🔄 用戶 {user_id} 降級已套用：{pending['tier']}", flush=True)
        # customer.subscription.updated webhook 會接著處理 quota 更新


async def _handle_payment_failed(invoice: dict, user_repo: UserRepository):
    """付款失敗"""
    customer_id = invoice["customer"]
    user = await user_repo.get_by_stripe_customer_id(customer_id)
    if not user:
        return

    user_id = str(user["_id"])
    sub = user.get("subscription", {})
    sub["status"] = "past_due"
    sub["updated_at"] = get_utc_timestamp()
    await user_repo.update(user_id, {"subscription": sub})
    print(f"⚠️ 用戶 {user_id} 付款失敗", flush=True)
