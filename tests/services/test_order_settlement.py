"""OrderSettlement 單元測試（91APP）。

付款狀態機的每一條 transition 都能用 typed PaymentNotification + fake repos 覆蓋，
不需要真金流 provider / webhook_repo / Mongo / FastAPI。
"""
import asyncio
import os
import sys
from pathlib import Path
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


def _make(order=None, user=None, invoice_issuer=None):
    """建一個 OrderSettlement，兩個 repo 全 fake（不再依賴金流 provider）。

    invoice_issuer 預設是 no-op AsyncMock：settle() 白名單 outcome 會透過
    create_background_task 觸發它，不 inject 的話會 fire 到真正的
    invoice_service.issue_for_order（打真 InvoiceRepository/UserRepository，在這裡的
    fake db 上會噴 TypeError），污染測試 stderr。開票 hook 本身的行為見 TestInvoiceTrigger。
    """
    order_repo = MagicMock()
    order_repo.get_by_order_no = AsyncMock(return_value=order)
    order_repo.update_by_order_no = AsyncMock(return_value=True)
    order_repo.has_recent_pending_order = AsyncMock(return_value=False)
    order_repo.supersede_pending_orders = AsyncMock(return_value=0)
    order_repo.create = AsyncMock(side_effect=lambda d: {**d, "_id": "oid"})
    # P0-1/P0-3：settle 的權威閘門，預設「一定搶得到 / 一定寫得進去」，讓既有測試
    # 聚焦在其他行為上；併發重入專屬測試會覆寫成 False 來驗證短路。
    order_repo.claim_paid = AsyncMock(return_value=True)
    order_repo.mark_failed_unless_paid = AsyncMock(return_value=True)

    user_repo = MagicMock()
    user_repo.db = MagicMock()
    user_repo.get_by_id = AsyncMock(return_value=user or {"subscription": {}})
    user_repo.update_subscription = AsyncMock(return_value=True)
    user_repo.update_subscription_fields = AsyncMock(return_value=True)
    user_repo.update_quota = AsyncMock(return_value=True)
    user_repo.reset_monthly_usage = AsyncMock(return_value=True)
    user_repo.add_extra_quota = AsyncMock(return_value=True)

    s = OrderSettlement(
        order_repo=order_repo, user_repo=user_repo,
        invoice_issuer=invoice_issuer or AsyncMock(),
    )
    return s, order_repo, user_repo


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
        s, order_repo, user_repo = _make(order=_order(card_token="CT1"))
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T1",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        sub = user_repo.update_subscription.await_args.args[1]
        assert sub["status"] == "active" and sub["tier"] == "basic"
        assert sub["active_order_no"] == "SLSUB1"
        assert sub["payment_provider"] == "91app"
        # cardToken 從 order 搬進 subscription；consumer_id = user_id；next_charge_at 有值
        assert sub["card_token"] == "CT1"
        assert sub["merchant_consumer_id"] == "u1"
        assert isinstance(sub["next_charge_at"], (int, float)) and sub["next_charge_at"] > 0
        user_repo.update_quota.assert_awaited_once_with("u1", build_quota_from_tier("basic"))
        user_repo.reset_monthly_usage.assert_awaited_once()
        # order 標 paid + 記 trade_id 由 settle() 的 claim_paid 權威閘門完成（P0-1/P0-3）
        order_repo.claim_paid.assert_awaited_once_with("SLSUB1", extra_updates={"trade_id": "T1"})

    async def test_monthly_renewal_reapplies_latest_quota(self):
        # status="pending"：settle 的 order-already-paid 快路徑現在不分首購/續扣，
        # 短路改成全類型（P0-1），fixture 必須是未結清的單才能走到 RENEWED 分支。
        user = {"subscription": {"status": "active", "tier": "basic", "created_at": 111, "card_token": "CT1"}}
        s, order_repo, user_repo = _make(order=_order(billing_cycle="monthly", status="pending"), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=False, trade_id="T2",
        ))
        assert r.outcome == SettleOutcome.RENEWED
        sub = user_repo.update_subscription_fields.await_args.args[1]
        assert sub["next_charge_at"] > 0  # 續扣滾動下次扣款時間
        user_repo.reset_monthly_usage.assert_awaited_once()
        user_repo.update_quota.assert_awaited_once_with("u1", build_quota_from_tier("basic"))
        # renewal order 標 paid（+ trade_id）由 claim_paid 權威閘門完成
        order_repo.claim_paid.assert_awaited_once_with("SLSUB1", extra_updates={"trade_id": "T2"})

    async def test_renewal_from_past_due_clears_dunning_and_swaps_card(self):
        # 重試/換卡成功：past_due→active、清 dunning、recovery order 帶新 token → 更新綁定
        user = {"subscription": {"status": "past_due", "tier": "basic", "created_at": 111,
                                 "card_token": "OLD", "dunning_attempts": 2, "needs_card_update": True}}
        order = _order(type="renewal", billing_cycle="monthly", card_token="NEWTOKEN")
        s, order_repo, user_repo = _make(order=order, user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=False, trade_id="T3",
        ))
        assert r.outcome == SettleOutcome.RENEWED
        sub = user_repo.update_subscription_fields.await_args.args[1]
        assert sub["status"] == "active"
        assert sub["dunning_attempts"] == 0 and sub["needs_card_update"] is False
        assert sub["next_retry_at"] is None and sub["dunning_started_at"] is None
        assert sub["card_token"] == "NEWTOKEN"  # 換卡搬新 token

    async def test_renewal_applies_pending_downgrade(self):
        # 期末降級生效：續扣單帶目標 tier(basic) → 套用 basic + 清 pending_plan_change + reconcile
        user = {"subscription": {"status": "active", "tier": "pro", "billing_cycle": "monthly",
                                 "created_at": 1, "card_token": "CT",
                                 "pending_plan_change": {"tier": "basic", "billing_cycle": "monthly"}}}
        order = _order(type="renewal", tier="basic", billing_cycle="monthly")
        s, order_repo, user_repo = _make(order=order, user=user)
        from unittest.mock import AsyncMock as _AM
        s._reconcile_pinned_audio = _AM()  # 攔截以斷言降級有觸發釘選核對
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=False, trade_id="T",
        ))
        assert r.outcome == SettleOutcome.RENEWED
        sub = user_repo.update_subscription_fields.await_args.args[1]
        assert sub["tier"] == "basic"                    # 降級生效
        assert sub["pending_plan_change"] is None         # 已套用 → 清空
        # 方案有變更 → 一律 reapply 目標 tier 額度（不論月/年）
        user_repo.update_quota.assert_awaited_once_with("u1", build_quota_from_tier("basic"))
        # 降級生效 → 釋放超額釘選音檔
        s._reconcile_pinned_audio.assert_awaited_once_with("u1", "basic")

    async def test_yearly_renewal_keeps_quota_frozen(self):
        # status="pending"：見 test_monthly_renewal_reapplies_latest_quota 的註解（P0-1 短路改全類型）
        user = {"subscription": {"status": "active", "tier": "pro", "created_at": 111}}
        s, order_repo, user_repo = _make(order=_order(tier="pro", billing_cycle="yearly", status="pending"), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=False, trade_id="T2",
        ))
        assert r.outcome == SettleOutcome.RENEWED
        user_repo.reset_monthly_usage.assert_awaited_once()
        user_repo.update_quota.assert_not_awaited()

    async def test_renewal_failure_only_marks_failed(self):
        # Phase 2：續扣失敗不在 settle 即時降 free（改由 renewal_service 的 Dunning 接手）。
        # settle 僅標記 order failed，不動 subscription/quota。
        # status="pending"：見上方註解（成功/失敗都共用同一條「已 paid 短路」快路徑，
        # 若用 status="paid" 會在走到失敗分支前就被短路成 ALREADY_PAID）。
        user = {"subscription": {"status": "active", "tier": "pro"}}
        s, order_repo, user_repo = _make(order=_order(tier="pro", status="pending"), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=False, is_first_payment=False,
        ))
        assert r.outcome == SettleOutcome.FAILED
        order_repo.mark_failed_unless_paid.assert_awaited_once_with("SLSUB1", {"status": "failed"})
        user_repo.update_quota.assert_not_awaited()
        user_repo.update_subscription.assert_not_awaited()

    async def test_first_payment_failure_does_not_expire(self):
        s, order_repo, user_repo = _make(order=_order())
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=False, is_first_payment=True,
        ))
        assert r.outcome == SettleOutcome.FAILED
        user_repo.update_subscription.assert_not_awaited()


# ── settle: 升級 / 降級 ──────────────────────────────────────────────────────

class TestUpgradeDowngrade:
    async def test_upgrade_carries_extra_quota(self):
        order = _order(
            merchant_order_no="SLUPG1", type="upgrade_subscription", tier="pro",
            prev_order_no="SLSUB0",
            extra_duration_minutes=42.5, extra_ai_summaries=3,
        )
        s, order_repo, user_repo = _make(order=order)
        r = await s.settle(PaymentNotification(
            order_no="SLUPG1", success=True, is_first_payment=True, trade_id="T9",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        user_repo.add_extra_quota.assert_awaited_once_with("u1", 42.5, 3)

    async def test_downgrade_no_carry(self):
        order = _order(
            merchant_order_no="SLDWN1", type="downgrade_subscription", tier="basic",
            prev_order_no="SLSUB0",
        )
        s, order_repo, user_repo = _make(order=order)
        r = await s.settle(PaymentNotification(
            order_no="SLDWN1", success=True, is_first_payment=True, trade_id="T9",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        user_repo.add_extra_quota.assert_not_awaited()


# ── settle: 重複完成防護 ─────────────────────────────────────────────────────

class TestDuplicateCompletion:
    async def test_sibling_already_active_is_rejected(self):
        # 既有 active 訂閱，active_order_no 指向別張 → 這張是重複完成
        user = {"subscription": {"status": "active", "active_order_no": "OTHER", "cancel_at_period_end": False}}
        s, order_repo, user_repo = _make(order=_order(), user=user)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T9",
        ))
        assert r.outcome == SettleOutcome.REJECTED_DUPLICATE
        # 不重複啟用 / 不加值；標 needs_refund（91APP 無委託可終止）
        user_repo.update_subscription.assert_not_awaited()
        user_repo.add_extra_quota.assert_not_awaited()
        marked = order_repo.update_by_order_no.await_args.args[1]
        assert marked["needs_refund"] is True and marked["is_duplicate"] is True


# ── settle: 額外額度 ─────────────────────────────────────────────────────────

class TestExtraQuota:
    async def test_extra_quota_success_grants_quota(self):
        order = _order(
            merchant_order_no="SLEXT1", type="extra_quota", tier=None, billing_cycle=None,
            extra_duration_minutes=120, extra_ai_summaries=0,
        )
        s, order_repo, user_repo = _make(order=order)
        r = await s.settle(PaymentNotification(
            order_no="SLEXT1", success=True, is_first_payment=True, trade_id="T1",
        ))
        assert r.outcome == SettleOutcome.GRANTED
        user_repo.add_extra_quota.assert_awaited_once_with("u1", 120, 0)
        # order 標 paid（+ trade_id）由 claim_paid 權威閘門完成（P0-1/P0-3）
        order_repo.claim_paid.assert_awaited_once_with("SLEXT1", extra_updates={"trade_id": "T1"})


# ── settle: order 生命週期 idempotency ───────────────────────────────────────

class TestIdempotency:
    async def test_order_not_found(self):
        s, *_ = _make(order=None)
        r = await s.settle(PaymentNotification(order_no="NOPE", success=True, is_first_payment=True))
        assert r.outcome == SettleOutcome.ORDER_NOT_FOUND

    async def test_first_payment_already_paid_short_circuits(self):
        s, order_repo, user_repo = _make(order=_order(status="paid"))
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=True))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        user_repo.update_subscription.assert_not_awaited()

    async def test_renewal_already_paid_also_short_circuits(self):
        """P0-1 補測（第二意見審查 補測(a)）：舊版短路只擋 is_first_payment=True，續扣
        重放沒有防線。這裡直接驗證 is_first_payment=False + order 已 paid 一樣要短路，
        不能碰任何 handler 副作用（claim_paid 都不該被呼叫到，因為快路徑更早就擋下）。
        """
        s, order_repo, user_repo = _make(order=_order(status="paid"))
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=False))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        order_repo.claim_paid.assert_not_awaited()
        user_repo.update_subscription.assert_not_awaited()
        user_repo.update_subscription_fields.assert_not_awaited()
        user_repo.update_quota.assert_not_awaited()


# ── open_pending: 付款防重 ───────────────────────────────────────────────────

class TestOpenPending:
    async def test_creates_pending_order(self):
        s, order_repo, _ = _make()
        out = await s.open_pending({"user_id": "u1", "type": "subscription", "status": "pending"})
        assert out["_id"] == "oid"
        order_repo.supersede_pending_orders.assert_awaited_once_with("u1", "subscription")
        order_repo.create.assert_awaited_once()

    async def test_cooldown_blocks_with_429(self):
        s, order_repo, _ = _make()
        order_repo.has_recent_pending_order.return_value = True
        with pytest.raises(HTTPException) as ei:
            await s.open_pending({"user_id": "u1", "type": "subscription", "status": "pending"})
        assert ei.value.status_code == 429
        order_repo.create.assert_not_awaited()

    async def test_concurrent_duplicate_becomes_429(self):
        from src.database.repositories.order_repo import DuplicatePendingOrderError
        s, order_repo, _ = _make()
        order_repo.create.side_effect = DuplicatePendingOrderError("u1", "subscription")
        with pytest.raises(HTTPException) as ei:
            await s.open_pending({"user_id": "u1", "type": "subscription", "status": "pending"})
        assert ei.value.status_code == 429


# ── settle: 開票 hook（91APP 付款成功 → 自動開立電子發票，設計 §4.2）─────────────

class TestInvoiceTrigger:
    """settle() 尾端白名單 outcome 觸發背景開票；create_background_task 是 fire-and-forget，
    故每個測試在 settle() 後 `await asyncio.sleep(0)` 讓 event loop 跑到那顆背景 task。
    """

    async def test_activated_triggers_invoice_issuer(self):
        issuer = AsyncMock()
        s, order_repo, _ = _make(order=_order(card_token="CT1"), invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T1",
        ))
        assert r.outcome == SettleOutcome.ACTIVATED
        await asyncio.sleep(0)
        issuer.assert_awaited_once()
        db_arg, order_arg = issuer.await_args.args
        assert order_arg["merchant_order_no"] == "SLSUB1"

    async def test_renewed_triggers_invoice_issuer(self):
        # status="pending"：見 TestSubscriptionSettle 續扣測試群組的註解（P0-1 短路改全類型）
        issuer = AsyncMock()
        user = {"subscription": {"status": "active", "tier": "basic", "created_at": 111, "card_token": "CT1"}}
        s, order_repo, _ = _make(order=_order(billing_cycle="monthly", status="pending"), user=user,
                                  invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=False, trade_id="T2"))
        assert r.outcome == SettleOutcome.RENEWED
        await asyncio.sleep(0)
        issuer.assert_awaited_once()

    async def test_granted_triggers_invoice_issuer(self):
        issuer = AsyncMock()
        order = _order(merchant_order_no="SLEXT1", type="extra_quota", tier=None, billing_cycle=None,
                       extra_duration_minutes=120, extra_ai_summaries=0)
        s, order_repo, _ = _make(order=order, invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(order_no="SLEXT1", success=True, is_first_payment=True, trade_id="T1"))
        assert r.outcome == SettleOutcome.GRANTED
        await asyncio.sleep(0)
        issuer.assert_awaited_once()

    async def test_failed_does_not_trigger_invoice(self):
        issuer = AsyncMock()
        s, order_repo, _ = _make(order=_order(), invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=False, is_first_payment=True))
        assert r.outcome == SettleOutcome.FAILED
        await asyncio.sleep(0)
        issuer.assert_not_awaited()

    async def test_already_paid_does_not_trigger_invoice(self):
        issuer = AsyncMock()
        s, order_repo, _ = _make(order=_order(status="paid"), invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=True))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        await asyncio.sleep(0)
        issuer.assert_not_awaited()

    async def test_rejected_duplicate_does_not_trigger_invoice(self):
        issuer = AsyncMock()
        user = {"subscription": {"status": "active", "active_order_no": "OTHER", "cancel_at_period_end": False}}
        s, order_repo, _ = _make(order=_order(), user=user, invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=True))
        assert r.outcome == SettleOutcome.REJECTED_DUPLICATE
        await asyncio.sleep(0)
        issuer.assert_not_awaited()

    async def test_issuer_exception_is_swallowed_settle_still_returns(self):
        """create_background_task 本身已把例外導去 Sentry/log；settle() 的回傳不受影響。"""
        issuer = AsyncMock(side_effect=RuntimeError("smilepay down"))
        s, order_repo, _ = _make(order=_order(card_token="CT1"), invoice_issuer=issuer)
        r = await s.settle(PaymentNotification(order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T1"))
        assert r.outcome == SettleOutcome.ACTIVATED  # settle 本身完全不受開票失敗影響
        await asyncio.sleep(0)
        issuer.assert_awaited_once()

    async def test_default_issuer_lazy_imports_invoice_service(self):
        """不注入 invoice_issuer 時（build_order_settlement/OrderSettlement 建構皆同），
        預設走真正的 invoice_service.issue_for_order（lazy import）——驗證『有真的接上』，
        實際開票邏輯由 test_invoice_service.py 覆蓋。`_make()` 測試 helper 為避免其他測試
        噴噪音一律注入 fake issuer，這裡改直接建構 OrderSettlement 驗證真正的預設值。
        """
        from src.services.order_settlement import OrderSettlement, _default_invoice_issuer, build_order_settlement
        s = OrderSettlement(order_repo=MagicMock(), user_repo=MagicMock())
        assert s._invoice_issuer is _default_invoice_issuer
        s2 = build_order_settlement(MagicMock())
        assert s2._invoice_issuer is _default_invoice_issuer


# ── settle: 併發重入（P0-1/P0-3 金流體檢核心）───────────────────────────────────

class TestConcurrentReentry:
    """claim_paid 是 settle() 唯一的權威閘門：搶不到就一定不能施加任何權益副作用。

    模擬「兩個 settle() 幾乎同時通過 order.status=='paid' 快路徑」的場景——快路徑本身
    只看 get_by_order_no 當下讀到的（可能過期的）status，claim_paid 的 DB 層原子
    status!=paid→paid 才是真正的仲裁點。這裡直接把 claim_paid mock 成 False 來模擬
    「輸掉這場競賽」的那個 settle()。
    """

    async def test_renewal_loses_race_grants_nothing(self):
        user = {"subscription": {"status": "active", "tier": "basic", "card_token": "CT1"}}
        s, order_repo, user_repo = _make(order=_order(billing_cycle="monthly", status="pending"), user=user)
        order_repo.claim_paid = AsyncMock(return_value=False)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=False, trade_id="T2",
        ))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        user_repo.update_subscription.assert_not_awaited()
        user_repo.update_subscription_fields.assert_not_awaited()
        user_repo.update_quota.assert_not_awaited()
        user_repo.reset_monthly_usage.assert_not_awaited()

    async def test_extra_quota_loses_race_grants_nothing(self):
        order = _order(
            merchant_order_no="SLEXT1", type="extra_quota", tier=None, billing_cycle=None,
            extra_duration_minutes=120, extra_ai_summaries=0,
        )
        s, order_repo, user_repo = _make(order=order)
        order_repo.claim_paid = AsyncMock(return_value=False)
        r = await s.settle(PaymentNotification(
            order_no="SLEXT1", success=True, is_first_payment=True, trade_id="T1",
        ))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        user_repo.add_extra_quota.assert_not_awaited()

    async def test_first_payment_loses_race_grants_nothing(self):
        s, order_repo, user_repo = _make(order=_order(card_token="CT1"))
        order_repo.claim_paid = AsyncMock(return_value=False)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T1",
        ))
        assert r.outcome == SettleOutcome.ALREADY_PAID
        user_repo.update_subscription.assert_not_awaited()
        user_repo.update_quota.assert_not_awaited()


# ── settle: 失敗通知不得覆寫已 paid 單（P0-3）────────────────────────────────────

class TestMarkFailedUnlessPaid:
    async def test_late_failure_notify_on_already_paid_order_is_a_noop(self):
        """order 已被別的 trade 結算成功後，一封遲到的舊 trade 失敗通知抵達：
        mark_failed_unless_paid 回 False（DB 層擋下覆寫），settle 不炸、仍回 FAILED
        （outcome 本身只反映『這封通知宣稱失敗』，不代表 order 真的被改成 failed）。
        """
        s, order_repo, user_repo = _make(order=_order(status="pending"))
        order_repo.mark_failed_unless_paid = AsyncMock(return_value=False)
        r = await s.settle(PaymentNotification(
            order_no="SLSUB1", success=False, is_first_payment=False,
        ))
        assert r.outcome == SettleOutcome.FAILED
        order_repo.mark_failed_unless_paid.assert_awaited_once_with("SLSUB1", {"status": "failed"})
        user_repo.update_subscription.assert_not_awaited()


# ── _expire_to_free：P0-2(b) 樂觀併發 guard ──────────────────────────────────────

class TestExpireToFreeGuard:
    async def test_guard_failure_returns_false_and_skips_quota_and_reconcile(self):
        s, order_repo, user_repo = _make()
        user_repo.update_subscription_fields = AsyncMock(return_value=False)
        from unittest.mock import AsyncMock as _AM
        s._reconcile_pinned_audio = _AM()

        ok = await s._expire_to_free("u1", guard={"subscription.next_charge_at": 999})

        assert ok is False
        user_repo.update_quota.assert_not_awaited()
        s._reconcile_pinned_audio.assert_not_awaited()

    async def test_guard_none_always_writes(self):
        from src.models.quota import build_quota_from_tier as _bqft
        s, order_repo, user_repo = _make()
        from unittest.mock import AsyncMock as _AM
        s._reconcile_pinned_audio = _AM()

        ok = await s._expire_to_free("u1")

        assert ok is True
        user_repo.update_subscription_fields.assert_awaited_once()
        assert user_repo.update_subscription_fields.await_args.kwargs.get("guard") is None
        user_repo.update_quota.assert_awaited_once_with("u1", _bqft("free"))
        s._reconcile_pinned_audio.assert_awaited_once_with("u1", "free")


# ── settle: handler crash 留下 entitlement_pending 旗標（F5，第二意見審查）────────

class TestEntitlementPendingOnCrash:
    async def test_subscription_handler_exception_marks_entitlement_pending_and_reraises(self):
        s, order_repo, user_repo = _make(order=_order(card_token="CT1"))
        s._settle_subscription = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await s.settle(PaymentNotification(
                order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T1",
            ))
        assert any(
            c.args[1].get("entitlement_pending") is True
            for c in order_repo.update_by_order_no.await_args_list
        )

    async def test_extra_quota_handler_exception_marks_entitlement_pending(self):
        order = _order(
            merchant_order_no="SLEXT1", type="extra_quota", tier=None, billing_cycle=None,
            extra_duration_minutes=120, extra_ai_summaries=0,
        )
        s, order_repo, user_repo = _make(order=order)
        s._settle_extra_quota = AsyncMock(side_effect=ValueError("boom"))
        with pytest.raises(ValueError, match="boom"):
            await s.settle(PaymentNotification(
                order_no="SLEXT1", success=True, is_first_payment=True, trade_id="T1",
            ))
        assert any(
            c.args[1].get("entitlement_pending") is True
            for c in order_repo.update_by_order_no.await_args_list
        )

    async def test_flag_write_failure_does_not_mask_original_exception(self):
        """_mark_entitlement_pending 本身失敗（例如連 DB 都掛了）不能蓋掉原始例外——
        呼叫端需要看到真正的錯誤原因，而不是旗標寫入失敗的次要錯誤。"""
        s, order_repo, user_repo = _make(order=_order(card_token="CT1"))
        s._settle_subscription = AsyncMock(side_effect=RuntimeError("original"))
        order_repo.update_by_order_no = AsyncMock(side_effect=ConnectionError("db down"))
        with pytest.raises(RuntimeError, match="original"):
            await s.settle(PaymentNotification(
                order_no="SLSUB1", success=True, is_first_payment=True, trade_id="T1",
            ))
