"""renewal_service（續扣排程器 + Dunning）單元測試。

用 monkeypatch 換掉 repo/service/settlement，聚焦 Dunning 狀態機與 claim 去重，
免 Mongo / 91APP / email。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "a" * 64)
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services import renewal_service as rs  # noqa: E402
from src.services.order_settlement import SettleResult, SettleOutcome  # noqa: E402


def _sub(**over):
    base = {
        "status": "active", "tier": "basic", "billing_cycle": "monthly",
        "card_token": "CT1", "merchant_consumer_id": "u1",
        "next_charge_at": 1000, "dunning_attempts": 0,
    }
    base.update(over)
    return base


def _patch(monkeypatch, *, claim_ok=True, charge_resp=None, existing_order=None):
    webhook = MagicMock()
    webhook.claim = AsyncMock(return_value=claim_ok)
    webhook.release = AsyncMock()
    monkeypatch.setattr(rs, "ProcessedWebhookRepository", lambda db: webhook)

    order_repo = MagicMock()
    order_repo.get_by_order_no = AsyncMock(return_value=existing_order)
    order_repo.create = AsyncMock()
    order_repo.update_by_order_no = AsyncMock()
    monkeypatch.setattr(rs, "OrderRepository", lambda db: order_repo)

    user_repo = MagicMock()
    user_repo.update_subscription = AsyncMock()
    user_repo.get_by_id = AsyncMock(return_value={"email": None})  # _send_email 早退
    monkeypatch.setattr(rs, "UserRepository", lambda db: user_repo)

    svc = MagicMock()
    svc.get_subscription_price = MagicMock(return_value=299)
    svc.charge_renewal = AsyncMock(return_value=charge_resp or {"statusCode": "Success", "tradeId": "T1"})
    monkeypatch.setattr(rs, "get_payments91_service", lambda: svc)

    settlement = MagicMock()
    settlement.settle = AsyncMock(return_value=SettleResult(SettleOutcome.RENEWED, "o"))
    settlement._expire_to_free = AsyncMock()
    monkeypatch.setattr(rs, "build_order_settlement", lambda db: settlement)

    return {"webhook": webhook, "order_repo": order_repo, "user_repo": user_repo,
            "svc": svc, "settlement": settlement}


class TestClassify:
    def test_retryable_default(self):
        assert rs.classify_failure("RefuseTrade") == "retryable"
        assert rs.classify_failure("BankError") == "retryable"
        assert rs.classify_failure(None) == "retryable"

    def test_card_fix(self):
        assert rs.classify_failure("CardExpired") == "card_fix"
        assert rs.classify_failure("cardExpired") == "card_fix"
        assert rs.classify_failure("CardNumberWrong") == "card_fix"

    def test_hard_stop(self):
        assert rs.classify_failure("CreditCardBlacklist") == "hard_stop"


class TestAttemptCharge:
    async def test_success_settles_renewal(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "Success", "tradeId": "T9"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["webhook"].claim.assert_awaited_once()  # claim before charge
        m["svc"].charge_renewal.assert_awaited_once()
        n = m["settlement"].settle.await_args.args[0]
        assert n.is_first_payment is False and n.success is True and n.trade_id == "T9"

    async def test_already_claimed_skips_charge(self, monkeypatch):
        m = _patch(monkeypatch, claim_ok=False)
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["svc"].charge_renewal.assert_not_awaited()  # 其他 worker 已處理

    async def test_paid_order_not_recharged(self, monkeypatch):
        m = _patch(monkeypatch, existing_order={"status": "paid"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["svc"].charge_renewal.assert_not_awaited()  # deterministic order 已成功 → 不重扣

    async def test_retryable_failure_sets_past_due(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "RefuseTrade", "message": "decline"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(dunning_attempts=0)})
        saved = m["user_repo"].update_subscription.await_args.args[1]
        assert saved["status"] == "past_due"
        assert saved["dunning_attempts"] == 1
        assert saved["next_retry_at"] is not None
        assert saved["dunning_started_at"] is not None
        m["settlement"]._expire_to_free.assert_not_awaited()  # 寬限期不降 free

    async def test_retries_exhausted_downgrades(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "RefuseTrade"})
        # 已重試 3 次 → 本次為第 4 次(RETRY_MAX) → 降 free
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(status="past_due", dunning_attempts=3, dunning_started_at=100)})
        m["settlement"]._expire_to_free.assert_awaited_once_with("u1")

    async def test_card_fix_flags_needs_update_no_retry(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "CardExpired"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        saved = m["user_repo"].update_subscription.await_args.args[1]
        assert saved["status"] == "past_due"
        assert saved["needs_card_update"] is True
        assert saved["next_retry_at"] is None  # 換卡類不自動重試
        m["settlement"]._expire_to_free.assert_not_awaited()

    async def test_hard_stop_downgrades_immediately(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "CreditCardBlacklist"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["settlement"]._expire_to_free.assert_awaited_once_with("u1")

    async def test_no_card_token_needs_update(self, monkeypatch):
        m = _patch(monkeypatch)
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(card_token=None)})
        m["svc"].charge_renewal.assert_not_awaited()
        saved = m["user_repo"].update_subscription.await_args.args[1]
        assert saved["status"] == "past_due" and saved["needs_card_update"] is True

    async def test_charge_exception_releases_claim(self, monkeypatch):
        m = _patch(monkeypatch)
        m["svc"].charge_renewal = AsyncMock(side_effect=RuntimeError("network"))
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["webhook"].release.assert_awaited_once()  # 結果未知 → release 供重試(idempotency key 保護)

    async def test_yearly_success_settles(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "Success", "tradeId": "TY"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(billing_cycle="yearly")})
        m["settlement"].settle.assert_awaited_once()


class TestDeterministicOrderNo:
    def test_stable_per_attempt(self):
        a = rs._renewal_order_no("6a631c4ec1ad174ecb0a716d", 1787446766, 2)
        b = rs._renewal_order_no("6a631c4ec1ad174ecb0a716d", 1787446766, 2)
        c = rs._renewal_order_no("6a631c4ec1ad174ecb0a716d", 1787446766, 3)
        assert a == b and a != c and len(a) <= 50
