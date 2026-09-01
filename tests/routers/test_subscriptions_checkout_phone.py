"""結帳/加購/換卡收手機號碼（91APP cardHolder 專案，PHONE_REQUIRED）單元測試。

風格比照 test_subscriptions_pay.py / test_subscriptions_lifecycle.py：直接呼叫 router
底下的 async function（bypass FastAPI Depends），monkeypatch repo/service，免 TestClient。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "a" * 64)
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import subscriptions as subs  # noqa: E402


def _user_repo(monkeypatch, *, billing_phone=None, subscription=None, invoice_info=None):
    user_repo = MagicMock()
    user_repo.get_by_id = AsyncMock(return_value={
        "_id": "u1", "email": "user@example.com",
        "billing_phone": billing_phone,
        "subscription": subscription or {},
        "invoice_info": invoice_info or {},
    })
    user_repo.update = AsyncMock(return_value=True)
    user_repo.update_invoice_info = AsyncMock(return_value=True)
    monkeypatch.setattr(subs, "UserRepository", lambda db: user_repo)
    return user_repo


def _svc(monkeypatch, *, amount=299):
    svc = MagicMock()
    svc.get_subscription_price = MagicMock(return_value=amount)
    svc.publishable_key = "pk"
    svc.sdk_server_type = "sandbox"
    monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)
    return svc


class TestCheckoutPhoneResolution:
    async def test_checkout_stores_normalized_phone_and_backfills_billing_phone(self, monkeypatch):
        user_repo = _user_repo(monkeypatch, billing_phone=None)
        _svc(monkeypatch)
        settlement = MagicMock()
        settlement.open_pending = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "build_order_settlement", lambda db: settlement)

        request = subs.CheckoutRequest(tier="basic", billing="monthly", phone_number="0912345678")
        await subs.create_checkout(request, current_user={"_id": "u1"}, db=MagicMock())

        order_data = settlement.open_pending.await_args.args[0]
        assert order_data["buyer_phone"] == "+886912345678"
        user_repo.update.assert_awaited_once_with("u1", {"billing_phone": "+886912345678"})

    async def test_checkout_falls_back_to_existing_billing_phone_without_rewriting(self, monkeypatch):
        user_repo = _user_repo(monkeypatch, billing_phone="+886987654321")
        _svc(monkeypatch)
        settlement = MagicMock()
        settlement.open_pending = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "build_order_settlement", lambda db: settlement)

        request = subs.CheckoutRequest(tier="basic", billing="monthly")
        await subs.create_checkout(request, current_user={"_id": "u1"}, db=MagicMock())

        order_data = settlement.open_pending.await_args.args[0]
        assert order_data["buyer_phone"] == "+886987654321"
        user_repo.update.assert_not_awaited()  # 純 fallback 命中，不重複回寫

    async def test_checkout_raises_phone_required_when_no_phone_anywhere(self, monkeypatch):
        _user_repo(monkeypatch, billing_phone=None)
        _svc(monkeypatch)
        settlement = MagicMock()
        settlement.open_pending = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "build_order_settlement", lambda db: settlement)

        request = subs.CheckoutRequest(tier="basic", billing="monthly")
        with pytest.raises(HTTPException) as exc_info:
            await subs.create_checkout(request, current_user={"_id": "u1"}, db=MagicMock())
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "PHONE_REQUIRED"
        settlement.open_pending.assert_not_awaited()

    async def test_checkout_raises_phone_invalid_for_malformed_phone_number(self, monkeypatch):
        _user_repo(monkeypatch, billing_phone=None)
        _svc(monkeypatch)
        settlement = MagicMock()
        settlement.open_pending = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "build_order_settlement", lambda db: settlement)

        request = subs.CheckoutRequest(tier="basic", billing="monthly", phone_number="12345")
        with pytest.raises(HTTPException) as exc_info:
            await subs.create_checkout(request, current_user={"_id": "u1"}, db=MagicMock())
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "PHONE_INVALID"


class TestPurchaseExtraPhoneResolution:
    async def test_purchase_extra_stores_normalized_phone(self, monkeypatch):
        user_repo = _user_repo(monkeypatch, billing_phone=None,
                                subscription={"status": "active"})
        _svc(monkeypatch)

        db = MagicMock()
        pkg = {"_id": "6a96fbe37599f21264010c17", "price_twd": 39, "amount": 60, "type": "duration",
               "sku": "SKU1", "label": "60 min"}
        find_one = AsyncMock(return_value=pkg)
        db.packages.find_one = find_one

        order_repo = MagicMock()
        order_repo.create = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

        request = subs.PurchaseExtraRequest(package_id="6a96fbe37599f21264010c17", quantity=1, phone_number="0912345678")
        await subs.purchase_extra_quota(request, current_user={"_id": "u1"}, db=db)

        order_data = order_repo.create.await_args.args[0]
        assert order_data["buyer_phone"] == "+886912345678"
        user_repo.update.assert_awaited_once_with("u1", {"billing_phone": "+886912345678"})

    async def test_purchase_extra_raises_phone_required_when_missing(self, monkeypatch):
        _user_repo(monkeypatch, billing_phone=None, subscription={"status": "active"})
        _svc(monkeypatch)

        db = MagicMock()
        pkg = {"_id": "6a96fbe37599f21264010c17", "price_twd": 39, "amount": 60, "type": "duration",
               "sku": "SKU1", "label": "60 min"}
        db.packages.find_one = AsyncMock(return_value=pkg)
        order_repo = MagicMock()
        order_repo.create = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

        request = subs.PurchaseExtraRequest(package_id="6a96fbe37599f21264010c17", quantity=1)
        with pytest.raises(HTTPException) as exc_info:
            await subs.purchase_extra_quota(request, current_user={"_id": "u1"}, db=db)
        assert exc_info.value.detail["code"] == "PHONE_REQUIRED"
        order_repo.create.assert_not_awaited()


class TestUpdateCardPhoneResolution:
    async def test_update_card_uses_request_phone_when_given(self, monkeypatch):
        _user_repo(monkeypatch, billing_phone=None,
                   subscription={"status": "past_due", "tier": "basic", "billing_cycle": "monthly"})
        _svc(monkeypatch)
        order_repo = MagicMock()
        order_repo.create = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

        request = subs.UpdateCardRequest(phone_number="0912345678")
        await subs.update_card(request, current_user={"_id": "u1"}, db=MagicMock())

        order_data = order_repo.create.await_args.args[0]
        assert order_data["buyer_phone"] == "+886912345678"

    async def test_update_card_falls_back_to_billing_phone(self, monkeypatch):
        _user_repo(monkeypatch, billing_phone="+886987654321",
                   subscription={"status": "past_due", "tier": "basic", "billing_cycle": "monthly"})
        _svc(monkeypatch)
        order_repo = MagicMock()
        order_repo.create = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

        await subs.update_card(current_user={"_id": "u1"}, db=MagicMock())

        order_data = order_repo.create.await_args.args[0]
        assert order_data["buyer_phone"] == "+886987654321"

    async def test_update_card_raises_phone_required_when_missing(self, monkeypatch):
        _user_repo(monkeypatch, billing_phone=None,
                   subscription={"status": "past_due", "tier": "basic", "billing_cycle": "monthly"})
        _svc(monkeypatch)
        order_repo = MagicMock()
        order_repo.create = AsyncMock(return_value={})
        monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

        with pytest.raises(HTTPException) as exc_info:
            await subs.update_card(current_user={"_id": "u1"}, db=MagicMock())
        assert exc_info.value.detail["code"] == "PHONE_REQUIRED"
        order_repo.create.assert_not_awaited()
