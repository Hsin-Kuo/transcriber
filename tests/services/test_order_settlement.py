"""OrderSettlement 單元測試。

驗證 deepening 的價值——付款狀態機的每一條 transition 都能用 typed
PaymentNotification + fake repos 覆蓋，不需要 AES / webhook_repo / Mongo / FastAPI。
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from src.models.quota import build_quota_from_tier  # noqa: E402
from src.services.order_settlement import (  # noqa: E402
    OrderSettlement,
    PaymentNotification,
    SettleOutcome,
)


def _make(order=None, user=None, orphans=None):
    """建一個 OrderSettlement，三個依賴全 fake。"""
    order_repo = MagicMock()
    order_repo.get_by_order_no = AsyncMock(return_value=order)
    order_repo.update_by_order_no = AsyncMock(return_value=True)
    order_repo.find_orphan_contracts = AsyncMock(return_value=orphans or [])
    order_repo.has_recent_pending_order = AsyncMock(return_value=False)
    order_repo.supersede_pending_orders = AsyncMock(return_value=0)
    order_repo.create = AsyncMock(side_effect=lambda d: {**d, "_id": "oid"})

    user_repo = MagicMock()
    user_repo.get_by_id = AsyncMock(return_value=user or {"subscription": {}})
    user_repo.update_subscription = AsyncMock(return_value=True)
    user_repo.update_quota = AsyncMock(return_value=True)
    user_repo.reset_monthly_usage = AsyncMock(return_value=True)
    user_repo.add_extra_quota = AsyncMock(return_value=True)

    newebpay = MagicMock()
    newebpay.calc_period_end.return_value = datetime(2026, 7, 1)
    newebpay.terminate_period_contract = AsyncMock(return_value=(True, "OK"))

    s = OrderSettlement(order_repo=order_repo, user_repo=user_repo, newebpay=newebpay)
    return s, order_repo, user_repo, newebpay


def _order(**over):
    base = {
        "merchant_order_no": "SLSUB1",
        "user_id": "u1",
        "type": "subscription",
        "tier": "basic",
        "billing_cycle": "monthly",
        "status": "pending",
    }
    base.update(over)
    return base


# ── settle: 訂閱啟用 / 續扣 / 失敗 ───────────────────────────────────────────

class TestSubscriptionSettle:
    async def test_first_subscription_activates(self):
        s, order_repo, user_repo, _ = _make(order=_order())
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, period_no="P1", trade_no="T1",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        sub = user_repo.update_subscription.await_args.args[1]
        assert sub["status"] == "active" and sub["tier"] == "basic"
        assert sub["active_order_no"] == "SLSUB1" and sub["period_no"] == "P1"
        user_repo.update_quota.assert_awaited_once_with("u1", build_quota_from_tier("basic"))
        user_repo.reset_monthly_usage.assert_awaited_once()
        # order 最終標 paid
        assert any(
            c.args[1].get("status") == "paid"
            for c in order_repo.update_by_order_no.await_args_list
        )

    async def test_renewal_rolls_period_without_quota_reset_to_tier(self):
        user = {"subscription": {"status": "active", "tier": "basic", "created_at": 111}}
        s, order_repo, user_repo, _ = _make(order=_order(status="paid"), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=False, period_no="P2", auth_times=2,
        ))
        assert r.outcome == SettleOutcome.RENEWED
        user_repo.update_subscription.assert_awaited_once()
        user_repo.reset_monthly_usage.assert_awaited_once()
        # 續扣不重設 tier quota（避免覆蓋升級後的 quota）
        user_repo.update_quota.assert_not_awaited()

    async def test_renewal_failure_expires_to_free(self):
        user = {"subscription": {"status": "active", "tier": "pro"}}
        s, order_repo, user_repo, _ = _make(order=_order(tier="pro", status="paid"), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=False, is_first_payment=False,
        ))
        assert r.outcome == SettleOutcome.EXPIRED
        assert any(
            c.args[1].get("status") == "failed"
            for c in order_repo.update_by_order_no.await_args_list
        )
        user_repo.update_quota.assert_awaited_once_with("u1", build_quota_from_tier("free"))
        assert user_repo.update_subscription.await_args.args[1]["status"] == "expired"

    async def test_first_payment_failure_does_not_expire(self):
        s, order_repo, user_repo, _ = _make(order=_order())
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=False, is_first_payment=True,
        ))
        assert r.outcome == SettleOutcome.FAILED
        user_repo.update_subscription.assert_not_awaited()


# ── settle: 升級 / 降級的差異 ────────────────────────────────────────────────

class TestUpgradeDowngrade:
    async def test_upgrade_carries_extra_quota_and_terminates_prev(self):
        order = _order(
            merchant_order_no="SLUPG1", type="upgrade_subscription", tier="pro",
            prev_order_no="SLSUB0", prev_period_no="P0",
            extra_duration_minutes=42.5, extra_ai_summaries=3,
        )
        s, order_repo, user_repo, newebpay = _make(order=order)
        r = await s.settle(PaymentNotification(
            order_no="SLUPG1", success=True, is_first_payment=True, period_no="P9",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        user_repo.add_extra_quota.assert_awaited_once_with("u1", 42.5, 3)
        newebpay.terminate_period_contract.assert_any_await("SLSUB0", "P0")

    async def test_downgrade_terminates_prev_but_no_carry(self):
        order = _order(
            merchant_order_no="SLDWN1", type="downgrade_subscription", tier="basic",
            prev_order_no="SLSUB0", prev_period_no="P0",
        )
        s, order_repo, user_repo, newebpay = _make(order=order)
        r = await s.settle(PaymentNotification(
            order_no="SLDWN1", success=True, is_first_payment=True, period_no="P9",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        user_repo.add_extra_quota.assert_not_awaited()
        newebpay.terminate_period_contract.assert_any_await("SLSUB0", "P0")


# ── settle: 重複完成防護 ─────────────────────────────────────────────────────

class TestDuplicateCompletion:
    async def test_sibling_already_active_is_rejected(self):
        # 既有 active 訂閱，active_order_no 指向別張 → 這張是重複完成
        user = {"subscription": {"status": "active", "active_order_no": "OTHER", "cancel_at_period_end": False}}
        s, order_repo, user_repo, newebpay = _make(order=_order(), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, period_no="P9",
        ))
        assert r.outcome == SettleOutcome.REJECTED_DUPLICATE
        # 不重複啟用 / 不加值；標 needs_refund + 終止多出來的委託
        user_repo.update_subscription.assert_not_awaited()
        user_repo.add_extra_quota.assert_not_awaited()
        newebpay.terminate_period_contract.assert_awaited_once_with("SLSUB1", "P9")
        marked = order_repo.update_by_order_no.await_args.args[1]
        assert marked["needs_refund"] is True and marked["is_duplicate"] is True


# ── settle: 額外額度 MPG ─────────────────────────────────────────────────────

class TestExtraQuota:
    async def test_mpg_success_grants_quota(self):
        order = _order(
            merchant_order_no="SLEXT1", type="extra_quota", tier=None, billing_cycle=None,
            extra_duration_minutes=120, extra_ai_summaries=0,
        )
        s, order_repo, user_repo, _ = _make(order=order)
        r = await s.settle(PaymentNotification(
            order_no="SLEXT1", success=True, is_first_payment=True, trade_no="T1",
        ))
        assert r.outcome == SettleOutcome.GRANTED
        user_repo.add_extra_quota.assert_awaited_once_with("u1", 120, 0)
        assert order_repo.update_by_order_no.await_args.args[1]["status"] == "paid"


# ── settle: order 生命週期 idempotency ───────────────────────────────────────

class TestIdempotency:
    async def test_order_not_found(self):
        s, *_ = _make(order=None)
        r = await s.settle(PaymentNotification(order_no="NOPE", success=True, is_first_payment=True))
        assert r.outcome == SettleOutcome.ORDER_NOT_FOUND

    async def test_first_payment_already_paid_short_circuits(self):
        s, order_repo, user_repo, _ = _make(order=_order(status="paid"))
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=True))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        user_repo.update_subscription.assert_not_awaited()


# ── settle: 孤兒委託對帳收斂 ─────────────────────────────────────────────────

class TestOrphanReconciliation:
    async def test_activation_terminates_orphan_contracts(self):
        orphans = [{"merchant_order_no": "OLD1", "period_no": "POLD"}]
        s, order_repo, user_repo, newebpay = _make(order=_order(), orphans=orphans)
        await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, period_no="P9",
        ))
        newebpay.terminate_period_contract.assert_any_await("OLD1", "POLD")
        # 終止成功 → 標記 contract_terminated_at（避免每次啟動重打）
        assert any(
            "contract_terminated_at" in c.args[1]
            for c in order_repo.update_by_order_no.await_args_list
        )

    async def test_orphan_scan_failure_does_not_break_activation(self):
        s, order_repo, user_repo, newebpay = _make(order=_order())
        order_repo.find_orphan_contracts.side_effect = RuntimeError("mongo down")
        # 啟用已成功，孤兒掃描炸掉不可拖垮整筆 settle
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, period_no="P9",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED


# ── open_pending: 付款防重 ───────────────────────────────────────────────────

class TestOpenPending:
    async def test_creates_pending_order(self):
        s, order_repo, *_ = _make()
        out = await s.open_pending({"user_id": "u1", "type": "subscription", "status": "pending"})
        assert out["_id"] == "oid"
        order_repo.supersede_pending_orders.assert_awaited_once_with("u1", "subscription")
        order_repo.create.assert_awaited_once()

    async def test_cooldown_blocks_with_429(self):
        s, order_repo, *_ = _make()
        order_repo.has_recent_pending_order.return_value = True
        with pytest.raises(HTTPException) as ei:
            await s.open_pending({"user_id": "u1", "type": "subscription", "status": "pending"})
        assert ei.value.status_code == 429
        order_repo.create.assert_not_awaited()

    async def test_concurrent_duplicate_becomes_429(self):
        from src.database.repositories.order_repo import DuplicatePendingOrderError
        s, order_repo, *_ = _make()
        order_repo.create.side_effect = DuplicatePendingOrderError("u1", "subscription")
        with pytest.raises(HTTPException) as ei:
            await s.open_pending({"user_id": "u1", "type": "subscription", "status": "pending"})
        assert ei.value.status_code == 429
