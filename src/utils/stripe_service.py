"""Stripe 訂閱服務"""
import os
import stripe
from typing import Optional, Dict, Tuple

from .config_loader import get_parameter


class StripeService:
    """Stripe 訂閱管理服務（Singleton）"""

    def __init__(self):
        self.secret_key = get_parameter(
            "/transcriber/stripe-secret-key",
            fallback_env="STRIPE_SECRET_KEY"
        )
        self.webhook_secret = get_parameter(
            "/transcriber/stripe-webhook-secret",
            fallback_env="STRIPE_WEBHOOK_SECRET"
        )
        self.publishable_key = get_parameter(
            "/transcriber/stripe-publishable-key",
            fallback_env="STRIPE_PUBLISHABLE_KEY"
        )
        stripe.api_key = self.secret_key
        self._price_map: Optional[Dict[str, str]] = None

    def get_price_map(self) -> Dict[str, str]:
        """tier_billing -> Stripe Price ID 對照表"""
        if self._price_map is None:
            self._price_map = {
                "basic_monthly": os.getenv("STRIPE_PRICE_BASIC_MONTHLY", ""),
                "basic_yearly": os.getenv("STRIPE_PRICE_BASIC_YEARLY", ""),
                "pro_monthly": os.getenv("STRIPE_PRICE_PRO_MONTHLY", ""),
                "pro_yearly": os.getenv("STRIPE_PRICE_PRO_YEARLY", ""),
            }
        return self._price_map

    def get_price_id(self, tier: str, billing: str) -> Optional[str]:
        """取得 Stripe Price ID"""
        key = f"{tier}_{billing}"
        price_id = self.get_price_map().get(key)
        return price_id if price_id else None

    def resolve_tier_from_price(self, price_id: str) -> Tuple[str, str]:
        """從 Price ID 反查 (tier, billing_cycle)"""
        for key, pid in self.get_price_map().items():
            if pid == price_id:
                parts = key.split("_", 1)
                return parts[0], parts[1]
        return "unknown", "unknown"

    def create_checkout_session(
        self,
        user_id: str,
        user_email: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        stripe_customer_id: Optional[str] = None,
    ) -> stripe.checkout.Session:
        """建立 Stripe Checkout Session"""
        params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": user_id,
            "metadata": {"user_id": user_id},
        }
        if stripe_customer_id:
            params["customer"] = stripe_customer_id
        else:
            params["customer_email"] = user_email

        return stripe.checkout.Session.create(**params)

    def create_portal_session(
        self,
        stripe_customer_id: str,
        return_url: str,
    ) -> stripe.billing_portal.Session:
        """建立 Stripe Customer Portal Session"""
        return stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )

    def cancel_subscription(self, subscription_id: str) -> stripe.Subscription:
        """取消訂閱（期末生效）"""
        return stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True,
        )

    def reactivate_subscription(self, subscription_id: str) -> stripe.Subscription:
        """重新啟用已排定取消的訂閱"""
        return stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=False,
        )

    def upgrade_subscription(
        self,
        subscription_id: str,
        new_price_id: str,
    ) -> stripe.Subscription:
        """升級方案：立即生效 + proration"""
        sub = stripe.Subscription.retrieve(subscription_id)
        item_id = sub["items"]["data"][0]["id"]
        return stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            proration_behavior="create_prorations",
        )

    def construct_webhook_event(
        self,
        payload: bytes,
        sig_header: str,
    ) -> stripe.Event:
        """驗證並建構 Webhook Event"""
        return stripe.Webhook.construct_event(
            payload, sig_header, self.webhook_secret
        )


# Singleton
_stripe_service: Optional[StripeService] = None


def get_stripe_service() -> StripeService:
    global _stripe_service
    if _stripe_service is None:
        _stripe_service = StripeService()
    return _stripe_service
