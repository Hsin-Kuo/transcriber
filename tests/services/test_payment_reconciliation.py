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
    # P1-5：退款分流呼叫這兩個方法（不再是 sweep 自己改寫 refund_seen 旗標）；
    # 預設回傳值只是佔位，聚焦分流測試的斷言是「有沒有被喚起、參數對不對」。
    settlement.handle_full_refund = AsyncMock(return_value="revoked")
    settlement.flag_partial_refund = AsyncMock(return_value="needs_manual")
    monkeypatch.setattr(pr, "build_order_settlement", lambda db: settlement)

    reconciled_alert = MagicMock()
    monkeypatch.setattr(pr, "_capture_reconciled_alert", reconciled_alert)
    gave_up_alert = MagicMock()
    monkeypatch.setattr(pr, "_capture_gave_up_alert", gave_up_alert)

    return order_repo, svc, settlement, reconciled_alert, gave_up_alert


# ── run_reconciliation_sweep: recordStatus 判讀分流 ──────────────────────────

class TestReconciliationDispatch:
    async def test_record_status_success_settles_and_alerts(self, monkeypatch):
        order_repo, svc, settlement, alert, _ = _patch(
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
        order_repo, svc, settlement, alert, _ = _patch(
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
        order_repo, svc, settlement, alert, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": rs},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["still_pending"] == 1

    async def test_full_refund_record_status_dispatches_to_handle_full_refund(self, monkeypatch):
        """P1-5：對帳側掉的全額退款(7) 走跟 /callback 側完全同一套處置。"""
        order_repo, svc, settlement, alert, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": 7},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        settlement.handle_full_refund.assert_awaited_once_with("SLSUB1", trade_id="T1")
        settlement.flag_partial_refund.assert_not_awaited()
        assert counts["refund_full"] == 1
        assert counts.get("refund_partial", 0) == 0

    async def test_partial_refund_record_status_dispatches_to_flag_partial_refund(self, monkeypatch):
        """P1-5：對帳側掉的部分退款(6) 一樣轉人工，不動訂閱/額度。"""
        order_repo, svc, settlement, alert, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": 6},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        settlement.flag_partial_refund.assert_awaited_once_with("SLSUB1", record_status=6)
        settlement.handle_full_refund.assert_not_awaited()
        assert counts["refund_partial"] == 1
        assert counts.get("refund_full", 0) == 0

    async def test_non_200_http_status_is_unresolved_not_failed(self, monkeypatch):
        """地雷回歸測試：_parse 對非 200 不拋錯，只回 body + _http_status；91APP 的
        404/5xx body 常缺 recordStatus。若直接丟給 interpret_record_status 會被
        fail-closed 誤判成 failed，錯殺一筆其實只是查詢失敗的單。"""
        order_repo, svc, settlement, alert, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 404, "errorCode": "NotFound"},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["unresolved"] == 1
        assert counts["resolved_failed"] == 0

    async def test_missing_record_status_with_200_is_unresolved(self, monkeypatch):
        """地雷回歸測試：即使 http_status 是 200，缺 recordStatus 欄位一樣要 unresolved。"""
        order_repo, svc, settlement, alert, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "statusCode": "Success"},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_non_numeric_record_status_is_unresolved(self, monkeypatch):
        order_repo, svc, settlement, alert, _ = _patch(
            monkeypatch, orders=[_order()], query_trade={"_http_status": 200, "recordStatus": "not-a-number"},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        settlement.settle.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_settle_outcome_already_paid_is_counted_and_alerted(self, monkeypatch):
        """對帳查到成功，但真 callback 剛好也到了（settle 回 ALREADY_PAID）——仍算
        『callback 鏈路曾經掉過一封』，值得記錄+告警，不是錯誤。"""
        order_repo, svc, settlement, alert, _ = _patch(
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
        order_repo, svc, settlement, _, gave_up_alert = _patch(
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
        order_repo, svc, settlement, _, gave_up_alert = _patch(
            monkeypatch, orders=[old_by_created_at], query_trade={"_http_status": 500},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 0
        gave_up_alert.assert_not_called()
        order_repo.stamp_reconciliation_first_seen.assert_awaited_once()

    async def test_recent_first_seen_order_does_not_give_up_yet(self, monkeypatch):
        recent_order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 1000)
        order_repo, svc, settlement, _, gave_up_alert = _patch(
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
        order_repo, svc, settlement, _, gave_up_alert = _patch(
            monkeypatch, orders=[old_order], query_trade={"_http_status": 200, "recordStatus": 1},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["still_pending"] == 1
        assert counts["gave_up"] == 1

    async def test_refund_does_not_give_up(self, monkeypatch):
        """退款分支已經有明確結果（P1-5 已實作：自動降級或轉人工），不算『懸而
        不決』，不該被放棄邏輯觸碰。"""
        old_order = _order(reconciliation_first_seen_at=get_utc_timestamp() - 72 * 3600 - 10)
        order_repo, svc, settlement, _, gave_up_alert = _patch(
            monkeypatch, orders=[old_order], query_trade={"_http_status": 200, "recordStatus": 7},
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 0
        gave_up_alert.assert_not_called()
        settlement.handle_full_refund.assert_awaited_once_with("SLSUB1", trade_id="T1")


# ── sweep 隔離：poison item 不癱瘓整輪 ────────────────────────────────────────

class TestSweepIsolation:
    async def test_poison_item_does_not_stall_the_whole_sweep(self, monkeypatch):
        good = _order(merchant_order_no="O2")
        poison = _order(merchant_order_no="O1")
        order_repo, svc, settlement, alert, _ = _patch(monkeypatch, orders=[poison, good])
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
        order_repo, svc, settlement, alert, gave_up_alert = _patch(
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
        order_repo, svc, settlement, alert, _ = _patch(monkeypatch, orders=[poison, good])
        svc.query_trade = AsyncMock(
            side_effect=[ValueError("bad trade_id"), {"_http_status": 200, "recordStatus": 4}]
        )
        counts = await pr.run_reconciliation_sweep(MagicMock())
        assert counts["gave_up"] == 1
        assert counts["resolved_success"] == 1


# ── periodic_payment_reconciliation: lease gate ──────────────────────────────

class TestLeaseGate:
    """M3（第二意見審查）：`run_refund_audit_sweep` 用**獨立**的 window lease
    （job="refund_audit"），跟主迴圈的 "payment_reconciliation" 鎖分開判定——
    兩者互不影響對方搶不搶得到執行權。"""

    async def _run_one_round(
        self, monkeypatch, *,
        claim_ok=True, claim_raises=None,
        refund_audit_claim_ok=True, refund_audit_claim_raises=None,
    ):
        lease_repo = MagicMock()

        async def _claim_window(job, window):
            if job == "refund_audit":
                if refund_audit_claim_raises:
                    raise refund_audit_claim_raises
                return refund_audit_claim_ok
            if claim_raises:
                raise claim_raises
            return claim_ok

        lease_repo.claim_window = AsyncMock(side_effect=_claim_window)
        monkeypatch.setattr(pr, "JobLeaseRepository", lambda db: lease_repo)

        sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_reconciliation_sweep", sweep)
        resettle_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_entitlement_resettle_sweep", resettle_sweep)
        capture_audit_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_capture_audit_sweep", capture_audit_sweep)
        refund_audit_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_refund_audit_sweep", refund_audit_sweep)
        monkeypatch.setattr(pr.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await pr.periodic_payment_reconciliation(MagicMock(), interval_seconds=600)
        return lease_repo, sweep, resettle_sweep, refund_audit_sweep, capture_audit_sweep

    async def test_lease_lost_skips_both_sweeps(self, monkeypatch):
        lease_repo, sweep, resettle_sweep, refund_audit_sweep, capture_audit_sweep = await self._run_one_round(
            monkeypatch, claim_ok=False, refund_audit_claim_ok=False,
        )
        lease_repo.claim_window.assert_any_await("payment_reconciliation", 600)
        lease_repo.claim_window.assert_any_await("refund_audit", pr.REFUND_AUDIT_LEASE_WINDOW_SECONDS)
        sweep.assert_not_awaited()
        resettle_sweep.assert_not_awaited()
        refund_audit_sweep.assert_not_awaited()
        capture_audit_sweep.assert_not_awaited()

    async def test_lease_won_runs_both_sweeps(self, monkeypatch):
        _, sweep, resettle_sweep, refund_audit_sweep, capture_audit_sweep = await self._run_one_round(
            monkeypatch, claim_ok=True,
        )
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()
        refund_audit_sweep.assert_awaited_once()
        capture_audit_sweep.assert_awaited_once()

    async def test_lease_check_exception_fails_open_and_runs_sweeps(self, monkeypatch):
        _, sweep, resettle_sweep, refund_audit_sweep, capture_audit_sweep = await self._run_one_round(
            monkeypatch, claim_raises=RuntimeError("mongo down"), refund_audit_claim_raises=RuntimeError("mongo down"),
        )
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()
        refund_audit_sweep.assert_awaited_once()
        capture_audit_sweep.assert_awaited_once()

    async def test_refund_audit_lease_is_independent_of_main_lease(self, monkeypatch):
        """主迴圈搶輸（should_run=False）不影響 refund_audit 照自己的節奏判斷；
        capture_audit 共用主 lease，搶輸時應跟前兩段一樣不執行。"""
        _, sweep, resettle_sweep, refund_audit_sweep, capture_audit_sweep = await self._run_one_round(
            monkeypatch, claim_ok=False, refund_audit_claim_ok=True,
        )
        sweep.assert_not_awaited()
        resettle_sweep.assert_not_awaited()
        refund_audit_sweep.assert_awaited_once()
        capture_audit_sweep.assert_not_awaited()

    async def test_main_lease_win_does_not_force_refund_audit_to_run(self, monkeypatch):
        """反之：主迴圈搶到了，不代表 refund_audit 的一天一輪視窗也一定搶得到；
        capture_audit 共用主 lease，主迴圈搶到就會跑。"""
        _, sweep, resettle_sweep, refund_audit_sweep, capture_audit_sweep = await self._run_one_round(
            monkeypatch, claim_ok=True, refund_audit_claim_ok=False,
        )
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()
        refund_audit_sweep.assert_not_awaited()
        capture_audit_sweep.assert_awaited_once()

    async def test_reconciliation_sweep_exception_does_not_block_resettle_sweep(self, monkeypatch):
        lease_repo = MagicMock()
        lease_repo.claim_window = AsyncMock(return_value=True)
        monkeypatch.setattr(pr, "JobLeaseRepository", lambda db: lease_repo)
        sweep = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(pr, "run_reconciliation_sweep", sweep)
        resettle_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_entitlement_resettle_sweep", resettle_sweep)
        capture_audit_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_capture_audit_sweep", capture_audit_sweep)
        refund_audit_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_refund_audit_sweep", refund_audit_sweep)
        monkeypatch.setattr(pr.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await pr.periodic_payment_reconciliation(MagicMock(), interval_seconds=600)
        resettle_sweep.assert_awaited_once()
        capture_audit_sweep.assert_awaited_once()
        refund_audit_sweep.assert_awaited_once()

    async def test_refund_audit_sweep_exception_is_isolated(self, monkeypatch):
        """refund_audit sweep 炸掉不可拖累前面幾段（也不可讓整個背景迴圈死掉）。"""
        lease_repo = MagicMock()
        lease_repo.claim_window = AsyncMock(return_value=True)
        monkeypatch.setattr(pr, "JobLeaseRepository", lambda db: lease_repo)
        sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_reconciliation_sweep", sweep)
        resettle_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_entitlement_resettle_sweep", resettle_sweep)
        capture_audit_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_capture_audit_sweep", capture_audit_sweep)
        refund_audit_sweep = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(pr, "run_refund_audit_sweep", refund_audit_sweep)
        monkeypatch.setattr(pr.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await pr.periodic_payment_reconciliation(MagicMock(), interval_seconds=600)
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()
        capture_audit_sweep.assert_awaited_once()
        refund_audit_sweep.assert_awaited_once()

    async def test_capture_audit_sweep_exception_is_isolated(self, monkeypatch):
        """capture_audit sweep 炸掉不可拖累其餘段落（也不可讓整個背景迴圈死掉）。"""
        lease_repo = MagicMock()
        lease_repo.claim_window = AsyncMock(return_value=True)
        monkeypatch.setattr(pr, "JobLeaseRepository", lambda db: lease_repo)
        sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_reconciliation_sweep", sweep)
        resettle_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_entitlement_resettle_sweep", resettle_sweep)
        capture_audit_sweep = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(pr, "run_capture_audit_sweep", capture_audit_sweep)
        refund_audit_sweep = AsyncMock()
        monkeypatch.setattr(pr, "run_refund_audit_sweep", refund_audit_sweep)
        monkeypatch.setattr(pr.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await pr.periodic_payment_reconciliation(MagicMock(), interval_seconds=600)
        sweep.assert_awaited_once()
        resettle_sweep.assert_awaited_once()
        refund_audit_sweep.assert_awaited_once()


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


# ── run_refund_audit_sweep（M3，第二意見審查）───────────────────────────────

def _paid_order(**over):
    base = {
        "merchant_order_no": "SLSUB1",
        "user_id": "u1",
        "type": "subscription",
        "status": "paid",
        "trade_id": "T1",
        "paid_at": get_utc_timestamp() - 1000,
    }
    base.update(over)
    return base


def _patch_refund_audit(monkeypatch, *, orders=None, query_trade=None,
                         full_refund_outcome="revoked", partial_refund_outcome="needs_manual"):
    order_repo = MagicMock()
    order_repo.iter_for_refund_audit = MagicMock(side_effect=lambda: _aiter(list(orders or [])))
    order_repo.stamp_refund_audited = AsyncMock(return_value=None)
    monkeypatch.setattr(pr, "OrderRepository", lambda db: order_repo)

    svc = MagicMock()
    svc.query_trade = AsyncMock(side_effect=query_trade) if callable(query_trade) else \
        AsyncMock(return_value=query_trade if query_trade is not None else {"_http_status": 200, "recordStatus": 4})
    monkeypatch.setattr(pr, "get_payments91_service", lambda: svc)

    settlement = MagicMock()
    settlement.handle_full_refund = AsyncMock(return_value=full_refund_outcome)
    settlement.flag_partial_refund = AsyncMock(return_value=partial_refund_outcome)
    monkeypatch.setattr(pr, "build_order_settlement", lambda db: settlement)

    return order_repo, svc, settlement


class TestRefundAuditSweep:
    """/callback 是 paid 單退款唯一即時路徑——這支 sweep 是唯一 fallback，掃 30 天
    內 paid、還沒被退款流程認領過的訂閱型/extra_quota 單，主動回查有沒有
    recordStatus 6/7。"""

    async def test_full_refund_dispatches_to_handle_full_refund(self, monkeypatch):
        order_repo, svc, settlement = _patch_refund_audit(
            monkeypatch, orders=[_paid_order()], query_trade={"_http_status": 200, "recordStatus": 7},
        )
        counts = await pr.run_refund_audit_sweep(MagicMock())
        settlement.handle_full_refund.assert_awaited_once_with("SLSUB1", trade_id="T1")
        settlement.flag_partial_refund.assert_not_awaited()
        assert counts["refund_full"] == 1
        order_repo.stamp_refund_audited.assert_awaited_once()

    async def test_partial_refund_dispatches_to_flag_partial_refund(self, monkeypatch):
        order_repo, svc, settlement = _patch_refund_audit(
            monkeypatch, orders=[_paid_order()], query_trade={"_http_status": 200, "recordStatus": 6},
        )
        counts = await pr.run_refund_audit_sweep(MagicMock())
        settlement.flag_partial_refund.assert_awaited_once_with("SLSUB1", record_status=6)
        settlement.handle_full_refund.assert_not_awaited()
        assert counts["refund_partial"] == 1

    async def test_non_refund_record_status_is_unresolved_and_untouched(self, monkeypatch):
        """已付款單正常的成功 recordStatus（4/5）——不是退款，維持 paid，不動它。"""
        order_repo, svc, settlement = _patch_refund_audit(
            monkeypatch, orders=[_paid_order()], query_trade={"_http_status": 200, "recordStatus": 4},
        )
        counts = await pr.run_refund_audit_sweep(MagicMock())
        settlement.handle_full_refund.assert_not_awaited()
        settlement.flag_partial_refund.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_non_200_http_status_is_unresolved(self, monkeypatch):
        """判讀 gate 比照主 sweep：非 200 或缺 recordStatus 一律 unresolved，不得
        誤判成任何退款分支。"""
        order_repo, svc, settlement = _patch_refund_audit(
            monkeypatch, orders=[_paid_order()], query_trade={"_http_status": 404},
        )
        counts = await pr.run_refund_audit_sweep(MagicMock())
        settlement.handle_full_refund.assert_not_awaited()
        settlement.flag_partial_refund.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_missing_trade_id_is_unresolved_without_querying(self, monkeypatch):
        order_repo, svc, settlement = _patch_refund_audit(
            monkeypatch, orders=[_paid_order(trade_id="")],
        )
        counts = await pr.run_refund_audit_sweep(MagicMock())
        svc.query_trade.assert_not_awaited()
        assert counts["unresolved"] == 1

    async def test_stamps_refund_audited_before_querying(self, monkeypatch):
        """輪替 stamp：處理前先寫，讓積壓超過 batch 上限時下一輪能撈到別筆。"""
        order_repo, svc, settlement = _patch_refund_audit(
            monkeypatch, orders=[_paid_order()], query_trade={"_http_status": 200, "recordStatus": 4},
        )
        await pr.run_refund_audit_sweep(MagicMock())
        order_repo.stamp_refund_audited.assert_awaited_once()
        assert order_repo.stamp_refund_audited.await_args.args[0] == "SLSUB1"

    async def test_poison_item_does_not_stall_the_whole_sweep(self, monkeypatch):
        good = _paid_order(merchant_order_no="O2")
        poison = _paid_order(merchant_order_no="O1")
        order_repo, svc, settlement = _patch_refund_audit(monkeypatch, orders=[poison, good])
        svc.query_trade = AsyncMock(
            side_effect=[ValueError("bad trade_id"), {"_http_status": 200, "recordStatus": 7}]
        )
        counts = await pr.run_refund_audit_sweep(MagicMock())
        assert counts["errored"] == 1
        assert counts["refund_full"] == 1  # 第二筆仍正常處理

    async def test_no_candidates_returns_zero_counts(self, monkeypatch):
        order_repo, svc, settlement = _patch_refund_audit(monkeypatch, orders=[])
        counts = await pr.run_refund_audit_sweep(MagicMock())
        assert counts == {"refund_full": 0, "refund_partial": 0, "unresolved": 0, "errored": 0}


# ── run_capture_audit_sweep（唯讀偵測「91APP 自動請款失效」+ Sentry）──────────
# 授權成功（recordStatus 4）不代表錢真的進帳——91APP 兩段式請款要靠「自動請款」
# 把 captureStatus 從 0 推到 1。這個 sweep 純唯讀：只查詢 + 告警，不 settle、
# 不改 order.status、不動權益/發票/退款。

def _paid_order_for_capture(**over):
    base = {
        "merchant_order_no": "SLSUB1",
        "user_id": "u1",
        "type": "subscription",
        "status": "paid",
        "trade_id": "T1",
        "paid_at": get_utc_timestamp() - 1000,
    }
    base.update(over)
    return base


def _patch_capture_audit(monkeypatch, *, orders=None, query_trade=None):
    order_repo = MagicMock()
    order_repo.iter_for_capture_audit = MagicMock(side_effect=lambda grace: _aiter(list(orders or [])))
    order_repo.stamp_capture_audited = AsyncMock(return_value=None)
    order_repo.stamp_capture_gap_alerted = AsyncMock(return_value=None)
    monkeypatch.setattr(pr, "OrderRepository", lambda db: order_repo)

    svc = MagicMock()
    svc.query_trade = AsyncMock(side_effect=query_trade) if callable(query_trade) else \
        AsyncMock(return_value=query_trade if query_trade is not None else
                  {"_http_status": 200, "statusCode": "Success", "captureStatus": 1})
    monkeypatch.setattr(pr, "get_payments91_service", lambda: svc)

    alert = MagicMock()
    monkeypatch.setattr(pr, "_capture_capture_gap_alert", alert)

    return order_repo, svc, alert


class TestCaptureAuditSweep:
    """純新增、唯讀 lane：statusCode==Success 但 captureStatus==0 → 每輪照舊 log +
    counts["capture_gap"]++，但 Sentry 受 `CAPTURE_AUDIT_ALERT_THROTTLE_SECONDS`
    節流（未過節流窗才真的發，發了才 stamp `capture_gap_alerted_at`）；
    captureStatus>=1 → 標記 capture_audited_at（避免每輪重複 query_trade / 重複
    告警），不告警。"""

    async def test_capture_status_zero_alerts_and_does_not_mark_audited(self, monkeypatch):
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 0},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_called_once_with("SLSUB1", "T1", 0)
        order_repo.stamp_capture_audited.assert_not_awaited()
        order_repo.stamp_capture_gap_alerted.assert_awaited_once()
        assert order_repo.stamp_capture_gap_alerted.await_args.args[0] == "SLSUB1"
        assert counts["capture_gap"] == 1
        assert counts["alerted"] == 1
        assert counts["captured_ok"] == 0
        assert counts["checked"] == 1
        assert counts["errored"] == 0

    async def test_capture_status_one_marks_audited_and_does_not_alert(self, monkeypatch):
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 1},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_awaited_once()
        assert order_repo.stamp_capture_audited.await_args.args[0] == "SLSUB1"
        order_repo.stamp_capture_gap_alerted.assert_not_awaited()
        assert counts["captured_ok"] == 1
        assert counts["capture_gap"] == 0
        assert counts["alerted"] == 0

    async def test_capture_status_above_one_also_marks_audited(self, monkeypatch):
        """captureStatus>=1 一律視為已請款（不只是恰好等於 1）。"""
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 2},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_awaited_once()
        assert counts["captured_ok"] == 1

    async def test_capture_status_zero_as_string_still_alerts(self, monkeypatch):
        """captureStatus 以字串 "0" 回傳時 int() 能處理——釘住字串路徑。"""
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": "0"},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_called_once_with("SLSUB1", "T1", 0)
        order_repo.stamp_capture_audited.assert_not_awaited()
        assert counts["capture_gap"] == 1
        assert counts["alerted"] == 1

    async def test_capture_status_one_as_string_still_marks_audited(self, monkeypatch):
        """captureStatus 以字串 "1" 回傳時 int() 能處理——釘住字串路徑。"""
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": "1"},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_awaited_once()
        assert counts["captured_ok"] == 1

    async def test_non_200_http_status_is_left_unresolved(self, monkeypatch):
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()], query_trade={"_http_status": 500},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_not_awaited()
        assert counts["capture_gap"] == 0
        assert counts["captured_ok"] == 0
        assert counts["errored"] == 0

    async def test_missing_capture_status_is_left_unresolved(self, monkeypatch):
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Success"},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_not_awaited()
        assert counts["capture_gap"] == 0
        assert counts["captured_ok"] == 0

    async def test_status_code_not_success_is_left_unresolved_even_if_capture_status_present(self, monkeypatch):
        """query 層 statusCode 非 Success 代表查詢本身沒查到結果，不能拿 captureStatus
        當真——即使 body 剛好帶了這個欄位也不算數。"""
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[_paid_order_for_capture()],
            query_trade={"_http_status": 200, "statusCode": "Fail", "captureStatus": 0},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_not_awaited()
        assert counts["capture_gap"] == 0

    async def test_poison_item_does_not_stall_the_whole_sweep(self, monkeypatch):
        good = _paid_order_for_capture(merchant_order_no="O2")
        poison = _paid_order_for_capture(merchant_order_no="O1")
        order_repo, svc, alert = _patch_capture_audit(monkeypatch, orders=[poison, good])
        svc.query_trade = AsyncMock(
            side_effect=[
                ValueError("bad trade_id"),
                {"_http_status": 200, "statusCode": "Success", "captureStatus": 0},
            ]
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        assert counts["errored"] == 1
        assert counts["capture_gap"] == 1  # 第二筆仍正常處理
        assert counts["checked"] == 2

    async def test_no_candidates_returns_zero_counts(self, monkeypatch):
        order_repo, svc, alert = _patch_capture_audit(monkeypatch, orders=[])
        counts = await pr.run_capture_audit_sweep(MagicMock())
        assert counts == {"checked": 0, "captured_ok": 0, "capture_gap": 0, "alerted": 0, "errored": 0}

    async def test_grace_seconds_passed_to_iter(self, monkeypatch):
        """寬限期常數確實被傳給查詢層，避免跟自動請款流程本身賽跑。"""
        order_repo, svc, alert = _patch_capture_audit(monkeypatch, orders=[])
        await pr.run_capture_audit_sweep(MagicMock())
        order_repo.iter_for_capture_audit.assert_called_once_with(pr.CAPTURE_AUDIT_GRACE_SECONDS)


class TestCaptureAuditAlertThrottle:
    """告警抑制窗（避免 Sentry 風暴）：同一張卡在 0 的單，連續多輪重查，Sentry
    只在節流窗過期後才重發；`capture_gap` 計數與 log 完全不受節流影響，每輪都
    照舊反映「現在仍卡在 0」的事實。"""

    async def test_first_encounter_alerts_and_stamps(self, monkeypatch):
        """第一輪（order 沒有 capture_gap_alerted_at 欄位）→ 發 Sentry + 記錄時間。"""
        order = _paid_order_for_capture()  # 無 capture_gap_alerted_at 欄位
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[order],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 0},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_called_once_with("SLSUB1", "T1", 0)
        order_repo.stamp_capture_gap_alerted.assert_awaited_once()
        assert counts["capture_gap"] == 1
        assert counts["alerted"] == 1

    async def test_within_throttle_window_logs_but_does_not_alert_again(self, monkeypatch):
        """第二輪：capture_gap_alerted_at 在節流窗內（例如 1 小時前，< 6 小時）→
        仍然偵測到（capture_gap++）、仍然 log，但**不**重發 Sentry。"""
        recent_alert = get_utc_timestamp() - 3600  # 1hr 前，在 6hr 節流窗內
        order = _paid_order_for_capture(capture_gap_alerted_at=recent_alert)
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[order],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 0},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_gap_alerted.assert_not_awaited()
        assert counts["capture_gap"] == 1  # 偵測本身不受節流影響
        assert counts["alerted"] == 0

    async def test_after_throttle_window_expires_alerts_again(self, monkeypatch):
        """超過節流窗（例如 7 小時前，> 6 小時）→ 重新發 Sentry + 更新時間戳。"""
        stale_alert = get_utc_timestamp() - (pr.CAPTURE_AUDIT_ALERT_THROTTLE_SECONDS + 3600)
        order = _paid_order_for_capture(capture_gap_alerted_at=stale_alert)
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[order],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 0},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_called_once_with("SLSUB1", "T1", 0)
        order_repo.stamp_capture_gap_alerted.assert_awaited_once()
        assert counts["alerted"] == 1

    async def test_capture_gap_alerted_at_does_not_suppress_stamp_capture_audited(self, monkeypatch):
        """capture_gap_alerted_at 只節流 Sentry，跟 capture_audited_at（確認請款
        成功）完全獨立——即使之前發過 capture_gap 告警，一旦這輪 captureStatus>=1，
        照樣正常標記終局旗標。"""
        order = _paid_order_for_capture(capture_gap_alerted_at=get_utc_timestamp() - 100)
        order_repo, svc, alert = _patch_capture_audit(
            monkeypatch, orders=[order],
            query_trade={"_http_status": 200, "statusCode": "Success", "captureStatus": 1},
        )
        counts = await pr.run_capture_audit_sweep(MagicMock())
        alert.assert_not_called()
        order_repo.stamp_capture_audited.assert_awaited_once()
        assert counts["captured_ok"] == 1
