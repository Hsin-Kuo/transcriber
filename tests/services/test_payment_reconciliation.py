"""payment_reconciliation（P1-9 對帳補償 sweep）單元測試。

比照 test_invoice_service.py / test_renewal_service.py 的形狀：monkeypatch
OrderRepository/get_payments91_service/build_order_settlement，聚焦排程邏輯本身
（recordStatus 判讀分流 / 72h 放棄 / sweep 隔離 / lease gate），不重複測
OrderSettlement.settle() 內部行為（見 test_order_settlement.py）。
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
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services import payment_reconciliation as pr  # noqa: E402
from src.services.order_settlement import SettleOutcome, SettleResult  # noqa: E402
from src.utils.time_utils import get_utc_timestamp  # noqa: E402


async def _aiter(items):
    for i in items:
        yield i


def _order(**over):
    base = {
        "merchant_order_no": "SLSUB1",
        "user_id": "u1",
        "type": "subscription",
        "status": "pending",
        "trade_id": "T1",
        "created_at": get_utc_timestamp() - 1000,
        # 預設「這一輪才第一次遇到」（欄位不存在）——第二意見審查 P1-D：72h 放棄
        # 時鐘的起點是 `reconciliation_first_seen_at`，不是 `created_at`。給 gave-up
        # 系列測試明確覆寫這個欄位，才能控制「已經懸而不決多久」。
    }
    base.update(over)
    return base


def _patch(monkeypatch, *, orders=None, settle_result=None, query_trade=None):
    order_repo = MagicMock()
    order_repo.iter_for_reconciliation = MagicMock(side_effect=lambda age: _aiter(list(orders or [])))
    order_repo.iter_entitlement_pending = MagicMock(side_effect=lambda max_retry: _aiter([]))
    order_repo.update_by_order_no = AsyncMock(return_value=True)
    order_repo.stamp_reconciliation_first_seen = AsyncMock(return_value=None)
    monkeypatch.setattr(pr, "OrderRepository", lambda db: order_repo)

    svc = MagicMock()
    svc.query_trade = AsyncMock(side_effect=query_trade) if callable(query_trade) else \
        AsyncMock(return_value=query_trade if query_trade is not None else {"_http_status": 200, "recordStatus": 4})
    monkeypatch.setattr(pr, "get_payments91_service", lambda: svc)

    settlement = MagicMock()
    settlement.settle = AsyncMock(return_value=settle_result or SettleResult(SettleOutcome.ACTIVATED, "SLSUB1"))
    settlement.resettle_entitlement = AsyncMock()
    monkeypatch.setattr(pr, "build_order_settlement", lambda db: settlement)

    reconciled_alert = MagicMock()
    monkeypatch.setattr(pr, "_capture_reconciled_alert", reconciled_alert)
    gave_up_alert = MagicMock()
    monkeypatch.setattr(pr, "_capture_gave_up_alert", gave_up_alert)
    refund_seen_alert = MagicMock()
    monkeypatch.setattr(pr, "_capture_refund_seen_alert", refund_seen_alert)

    return order_repo, svc, settlement, reconciled_alert, gave_up_alert, refund_seen_alert


# ── run_reconciliation_sweep: recordStatus 判讀分流 ──────────────────────────

class TestReconciliationDispatch:
    async def test_record_status_success_settles_and_alerts(self, monkeypatch):
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": 4},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_awaited_once()
        n = settlement.settle.await_args.args[0]
        assert n.order_no == "SLSUB1" and n.success is True and n.trade_id == "T1"
        assert counts["resolved_success"] == 1
        assert counts["activated"] == 1
        alert.assert_called_once_with("SLSUB1", "activated")

    async def test_record_status_failed_settles_failure(self, monkeypatch):
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": 2},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_awaited_once()
        n = settlement.settle.await_args.args[0]
        assert n.success is False
        assert counts["resolved_failed"] == 1
        alert.assert_not_called()

    @pytest.mark.parametrize("rs", [1, 8])
    async def test_pending_record_status_does_not_settle(self, monkeypatch, rs):
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": rs},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["still_pending"] == 1

    @pytest.mark.parametrize("rs", [6, 7])
    async def test_refund_record_status_flags_and_alerts_once(self, monkeypatch, rs):
        """P1-C（第二意見審查）：退款不再是『刻意不動、每輪重查』的殭屍單——改寫
        refund_seen 旗標 + Sentry 一次，settle() 完全不被喚起。"""
        order_repo, svc, settlement, alert, _, refund_alert = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": rs},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["refund_seen"] == 1
        order_repo.update_by_order_no.assert_any_await("SLSUB1", {"refund_seen": True})
        refund_alert.assert_called_once_with("SLSUB1", rs)

    async def test_non_200_http_status_is_unresolved_not_failed(self, monkeypatch):
        """地雷回歸測試：_parse 對非 200 不拋錯，只回 body + _http_status；91APP 的
        404/5xx body 常缺 recordStatus。若直接丟給 interpret_record_status 會被
        fail-closed 誤判成 failed，錯殺一筆其實只是查詢失敗的單。"""
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 404, "errorCode": "NotFound"},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["unresolved"] == 1
        assert counts["resolved_failed"] == 0

    async def test_missing_record_status_with_200_is_unresolved(self, monkeypatch):
        """地雷回歸測試：即使 http_status 是 200，缺 recordStatus 欄位一樣要 unresolved。"""
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "statusCode": "Success"},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_non_numeric_record_status_is_unresolved(self, monkeypatch):
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": "not-a-number"},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_settle_outcome_already_paid_is_counted_and_alerted(self, monkeypatch):
        """對帳查到成功，但真 callback 剛好也到了（settle 回 ALREADY_PAID）——仍算
        『callback 鏈路曾經掉過一封』，值得記錄+告警，不是錯誤。"""
        order_repo, svc, settlement, alert, _, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": 4},
            settle_result=SettleResult(SettleOutcome.ALREADY_PAID, "SLSUB1"),
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["already_paid"] == 1
        alert.assert_called_once_with("SLSUB1", "already_paid")


# ── 首次遭遇時間戳（P1-D）───────────────────────────────────────────────────

class TestFirstSeenStamping:
    async def test_stamps_on_first_encounter(self, monkeypatch):
        order_repo, svc, settlement, *_ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": 1},
        )
        await pr.run_reconciliation_sweep(MagicMock())
        order_repo.stamp_reconciliation_first_seen.assert_awaited_once()
        args = order_repo.stamp_reconciliation_first_seen.await_args.args
        assert args[0] == "SLSUB1"
        assert isinstance(args[1], (int, float))

    async def test_does_not_restamp_when_already_present(self, monkeypatch):
        order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 5000)
        order_repo, svc, settlement, *_ = _patch(
            monkeypatch, orders=[order], query_trade={"_http_status": 200, "recordStatus": 1},
        )
        await pr.run_reconciliation_sweep(MagicMock())
        order_repo.stamp_reconciliation_first_seen.assert_not_awaited()


# ── 72h 放棄 ─────────────────────────────────────────────────────────────────

class TestGiveUp:
    """P1-D（第二意見審查）：時鐘用 `reconciliation_first_seen_at`，不是
    `created_at`——避免 backfill 到歷史舊單時，第一輪就把它們全部判定放棄。
    """

    async def test_old_first_seen_unresolved_order_gives_up_without_touching_status(self, monkeypatch):
        old_order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 72 * 3600 - 10)
        order_repo, svc, settlement, _, gave_up_alert, _ = _patch(
            monkeypatch, orders=[old_order], query_trade={"_http_status": 500},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 1
        order_repo.update_by_order_no.assert_any_await("SLSUB1", {"reconciliation_gave_up": True})
        gave_up_alert.assert_called_once_with("SLSUB1")
        # 已經有 first_seen 了，不該再重新 stamp
        order_repo.stamp_reconciliation_first_seen.assert_not_awaited()

    async def test_new_order_without_first_seen_does_not_give_up_on_first_encounter(self, monkeypatch):
        """關鍵回歸（P1-D）：即使 `created_at` 很舊（例如上線當下 backfill 到的歷史
        pending 單），只要是這一輪才第一次被 sweep 遇到，也不該立刻放棄——時鐘應該
        從『現在』開始起算，而不是沿用舊的 created_at。"""
        old_by_created_at = _order(created_at=get_utc_timestamp() - 72 * 3600 - 10)
        order_repo, svc, settlement, _, gave_up_alert, _ = _patch(
            monkeypatch, orders=[old_by_created_at], query_trade={"_http_status": 500},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 0
        gave_up_alert.assert_not_called()
        order_repo.stamp_reconciliation_first_seen.assert_awaited_once()

    async def test_recent_first_seen_order_does_not_give_up_yet(self, monkeypatch):
        recent_order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 1000)
        order_repo, svc, settlement, _, gave_up_alert, _ = _patch(
            monkeypatch, orders=[recent_order], query_trade={"_http_status": 500},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 0
        # 輪替 stamp（last_reconciled_at）每筆必寫，所以不能斷言零呼叫——斷言
        # 「沒有任何一次呼叫寫過 gave_up 旗標」。
        for call in order_repo.update_by_order_no.await_args_list:
            assert "reconciliation_gave_up" not in call.args[1]
        gave_up_alert.assert_not_called()

    async def test_old_still_pending_also_gives_up(self, monkeypatch):
        old_order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 72 * 3600 - 10)
        order_repo, svc, settlement, _, gave_up_alert, _ = _patch(
            monkeypatch, orders=[old_order], query_trade={"_http_status": 200, "recordStatus": 1},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["still_pending"] == 1
        assert counts["gave_up"] == 1

    async def test_refund_seen_does_not_give_up(self, monkeypatch):
        """退款分支已經有明確結果（P1-5 範圍前的暫定收斂），不算『懸而不決』，
        不該被放棄邏輯觸碰——它走自己的 refund_seen 旗標，不是 gave_up。"""
        old_order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 72 * 3600 - 10)
        order_repo, svc, settlement, _, gave_up_alert, refund_alert = _patch(
            monkeypatch, orders=[old_order], query_trade={"_http_status": 200, "recordStatus": 7},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 0
        gave_up_alert.assert_not_called()
        refund_alert.assert_called_once_with("SLSUB1", 7)


# ── sweep 隔離：poison item 不癱瘓整輪 ────────────────────────────────────────

class TestSweepIsolation:
    async def test_poison_item_does_not_stall_the_whole_sweep(self, monkeypatch):
        good = _order(merchant_order_no="O2")
        poison = _order(merchant_order_no="O1")
        order_repo, svc, settlement, alert, _, _ = _patch(monkeypatch, orders=[poison, good])
        svc.query_trade = AsyncMock(side_effect=[RuntimeError("91APP down"), {"_http_status": 200, "recordStatus": 4}])
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["errored"] == 1
        assert counts["resolved_success"] == 1  # 第二筆仍正常處理


# ── P2-F：格式不符的 trade_id 是永久性髒資料，不是暫時性錯誤 ─────────────────────

class TestPoisonTradeId:
    async def test_value_error_from_query_trade_gives_up_instead_of_erroring(self, monkeypatch):
        """query_trade 對格式不符的 trade_id 直接 raise ValueError——這不是『這次
        剛好查詢失敗，下一輪可能會不一樣』的暫時性錯誤，重試 100 次結果都一樣。
        必須落 gave_up（立刻轉人工），不能落 errored（會被下一輪繼續白白重試）。
        """
        order_repo, svc, settlement, alert, gave_up_alert, _ = _patch(
            monkeypatch, orders=[_order()],
        )
        svc.query_trade = AsyncMock(side_effect=ValueError("invalid trade_id format"))
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 1
        assert counts["errored"] == 0
        settlement.settle.assert_not_awaited()
        order_repo.update_by_order_no.assert_any_await("SLSUB1", {"reconciliation_gave_up": True})
        gave_up_alert.assert_called_once_with("SLSUB1")

    async def test_value_error_does_not_stall_the_rest_of_the_sweep(self, monkeypatch):
        good = _order(merchant_order_no="O2")
        poison = _order(merchant_order_no="O1")
        order_repo, svc, settlement, alert, _, _ = _patch(monkeypatch, orders=[poison, good])
        svc.query_trade = AsyncMock(
            side_effect=[ValueError("bad trade_id"), {"_http_status": 200, "recordStatus": 4}]
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 1
        assert counts["resolved_success"] == 1


# ── periodic_payment_reconciliation: lease gate ──────────────────────────────

class TestLeaseGate:
    async def _run_one_round(self, monkeypatch, *, claim_ok=True, claim_raises=None):
        lease_repo = MagicMock()
        if claim_raises:
            lease_repo.claim_window = AsyncMock(side_effect=claim_raises)
        else:
            lease_repo.claim_window = AsyncMock(return_value=claim_ok)
        monkeypatch.setattr(pr, "JobLeaseRepository", lambda db: lease_repo)

        sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_reconciliation_sweep", sweep)
        resettle_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_entitlement_resettle_sweep", resettle_sweep)
        monkeypatch.setattr(pr.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await pr.periodic_payment_reconciliation(MagicMock(), interval_seconds=600)
        return lease_repo, sweep, resettle_sweep

    async def test_lease_lost_skips_both_sweeps(self, monkeypatch):
        lease_repo, sweep, resettle_sweep = await self._run_one_round(monkeypatch, claim_ok=False)
        lease_repo.claim_window.assert_awaited_once_with("payment_reconciliation", 600)
        sweep.assert_not_awaited()
        resettle_sweep.assert_not_awaited()

    async def test_lease_won_runs_both_sweeps(self, monkeypatch):
        _, sweep, resettle_sweep = await self._run_one_round(monkeypatch, claim_ok=True)
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()

    async def test_lease_check_exception_fails_open_and_runs_sweeps(self, monkeypatch):
        _, sweep, resettle_sweep = await self._run_one_round(monkeypatch, claim_raises=RuntimeError("mongo down"))
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()

    async def test_reconciliation_sweep_exception_does_not_block_resettle_sweep(self, monkeypatch):
        lease_repo = MagicMock()
        lease_repo.claim_window = AsyncMock(return_value=True)
        monkeypatch.setattr(pr, "JobLeaseRepository", lambda db: lease_repo)
        sweep = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(pr, "run_reconciliation_sweep", sweep)
        resettle_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_entitlement_resettle_sweep", resettle_sweep)
        monkeypatch.setattr(pr.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await pr.periodic_payment_reconciliation(MagicMock(), interval_seconds=600)
        resettle_sweep.assert_awaited_once()


# ── run_entitlement_resettle_sweep ───────────────────────────────────────────

class TestEntitlementResettleSweep:
    def _patch_resettle(self, monkeypatch, *, orders=None, resettle_side_effect=None):
        order_repo = MagicMock()
        order_repo.iter_entitlement_pending = MagicMock(side_effect=lambda max_retry: _aiter(list(orders or [])))
        monkeypatch.setattr(pr, "OrderRepository", lambda db: order_repo)

        settlement = MagicMock()
        if resettle_side_effect is not None:
            settlement.resettle_entitlement = AsyncMock(side_effect=resettle_side_effect)
        else:
            settlement.resettle_entitlement = AsyncMock()
        monkeypatch.setattr(pr, "build_order_settlement", lambda db: settlement)
        return order_repo, settlement

    async def test_resettles_each_pending_order(self, monkeypatch):
        orders = [_order(merchant_order_no="O1"), _order(merchant_order_no="O2")]
        order_repo, settlement = self._patch_resettle(monkeypatch, orders=orders)
        counts = await pr.run_entitlement_resettle_sweep(MagicMock())
        assert settlement.resettle_entitlement.await_count == 2
        assert counts["resettled"] == 2
        assert counts["errored"] == 0

    async def test_poison_item_does_not_stall_sweep(self, monkeypatch):
        orders = [_order(merchant_order_no="O1"), _order(merchant_order_no="O2")]
        order_repo, settlement = self._patch_resettle(
            monkeypatch, orders=orders, resettle_side_effect=[RuntimeError("boom"), None],
        )
        counts = await pr.run_entitlement_resettle_sweep(MagicMock())
        assert counts["errored"] == 1
        assert counts["resettled"] == 1
