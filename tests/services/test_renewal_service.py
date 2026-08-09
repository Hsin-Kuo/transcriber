"""renewal_service（續扣排程器 + Dunning）單元測試。

用 monkeypatch 換掉 repo/service/settlement，聚焦 Dunning 狀態機與 claim 去重，
免 Mongo / 91APP / email。
"""
import asyncio
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

from src.database.repositories.order_repo import DuplicatePendingOrderError  # noqa: E402
from src.services import renewal_service as rs  # noqa: E402
from src.services.order_settlement import SettleResult, SettleOutcome  # noqa: E402
from src.utils.card_token_cipher import encrypt  # noqa: E402


class FakeCursor:
    """比照 test_invoice_service.py 的形狀：db.users.find(...) 回傳的 motor cursor 替身。"""

    def __init__(self, docs):
        self.docs = docs

    def sort(self, *a, **kw):
        return self

    async def to_list(self, length=None):
        return self.docs[:length] if length else list(self.docs)

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


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
    order_repo.mark_failed_unless_paid = AsyncMock(return_value=True)
    monkeypatch.setattr(rs, "OrderRepository", lambda db: order_repo)

    user_repo = MagicMock()
    user_repo.update_subscription = AsyncMock()
    user_repo.update_subscription_fields = AsyncMock(return_value=True)
    user_repo.get_by_id = AsyncMock(return_value={"email": None})  # _send_email 早退
    monkeypatch.setattr(rs, "UserRepository", lambda db: user_repo)

    svc = MagicMock()
    svc.get_subscription_price = MagicMock(return_value=299)
    svc.charge_renewal = AsyncMock(return_value=charge_resp or {"statusCode": "Success", "tradeId": "T1"})
    monkeypatch.setattr(rs, "get_payments91_service", lambda: svc)

    settlement = MagicMock()
    settlement.settle = AsyncMock(return_value=SettleResult(SettleOutcome.RENEWED, "o"))
    settlement._expire_to_free = AsyncMock(return_value=True)
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
        m["webhook"].release.assert_not_awaited()  # 已 paid 早退：claim 留著防重扣，不 release

    async def test_late_failure_response_does_not_overwrite_paid_order(self, monkeypatch):
        """F1 時序測試（第二意見審查）：sweep 發起扣款後，91APP 先送 callback 讓
        settle() 的 claim_paid 把單搶成 paid，charge_renewal 的 HTTP response 才姍姍
        來遲且回非 Success（例如逾時後 91APP 端其實成功了）。改用
        mark_failed_unless_paid 之後，不該再用會無條件覆寫的 update_by_order_no 寫
        status=failed；這裡直接把 mark_failed_unless_paid mock 回 False（模擬它在 DB
        層被 $ne paid 擋下），驗證呼叫路徑正確且不因此拋例外。
        """
        m = _patch(monkeypatch, charge_resp={"statusCode": "RefuseTrade"})
        m["order_repo"].mark_failed_unless_paid = AsyncMock(return_value=False)
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})

        m["order_repo"].mark_failed_unless_paid.assert_awaited_once()
        args = m["order_repo"].mark_failed_unless_paid.await_args.args
        assert args[1] == {"status": "failed"}
        # 沒有透過會無條件覆寫的 update_by_order_no 寫 status=failed
        assert not any(
            c.args[1].get("status") == "failed"
            for c in m["order_repo"].update_by_order_no.await_args_list
        )
        # Dunning 狀態機仍照跑（不因為 mark 被擋就跳過失敗分類處理）
        m["user_repo"].update_subscription_fields.assert_awaited_once()

    async def test_retryable_failure_sets_past_due(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "RefuseTrade", "message": "decline"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(dunning_attempts=0)})
        # P0-2(b)：dotted 欄位寫入改走 update_subscription_fields（不再整包 $set）
        saved = m["user_repo"].update_subscription_fields.await_args.args[1]
        assert saved["status"] == "past_due"
        assert saved["dunning_attempts"] == 1
        assert saved["next_retry_at"] is not None
        assert saved["dunning_started_at"] is not None
        m["settlement"]._expire_to_free.assert_not_awaited()  # 寬限期不降 free

    async def test_retries_exhausted_downgrades(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "RefuseTrade"})
        # 已重試 3 次 → 本次為第 4 次(RETRY_MAX) → 降 free
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(status="past_due", dunning_attempts=3, dunning_started_at=100)})
        # P0-2(b)：guard 帶手上快照的 next_charge_at（_sub() 預設 1000）
        m["settlement"]._expire_to_free.assert_awaited_once_with(
            "u1", guard={"subscription.next_charge_at": 1000}
        )

    async def test_card_fix_flags_needs_update_no_retry(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "CardExpired"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        saved = m["user_repo"].update_subscription_fields.await_args.args[1]
        assert saved["status"] == "past_due"
        assert saved["needs_card_update"] is True
        assert saved["next_retry_at"] is None  # 換卡類不自動重試
        m["settlement"]._expire_to_free.assert_not_awaited()

    async def test_hard_stop_downgrades_immediately(self, monkeypatch):
        m = _patch(monkeypatch, charge_resp={"statusCode": "CreditCardBlacklist"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["settlement"]._expire_to_free.assert_awaited_once_with(
            "u1", guard={"subscription.next_charge_at": 1000}
        )

    async def test_no_card_token_needs_update(self, monkeypatch):
        m = _patch(monkeypatch)
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(card_token=None)})
        m["svc"].charge_renewal.assert_not_awaited()
        saved = m["user_repo"].update_subscription_fields.await_args.args[1]
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

    async def test_encrypted_card_token_is_decrypted_before_charge(self, monkeypatch):
        """P2-10（金流體檢）：sub.card_token 落庫時已是密文，charge_renewal（純 adapter，
        只認明文）收到的必須是解密後的明文。"""
        m = _patch(monkeypatch, charge_resp={"statusCode": "Success", "tradeId": "T9"})
        await rs._attempt_charge(
            MagicMock(), {"_id": "u1", "subscription": _sub(card_token=encrypt("CT1"))}
        )
        m["svc"].charge_renewal.assert_awaited_once()
        assert m["svc"].charge_renewal.await_args.kwargs["card_token"] == "CT1"

    async def test_decrypt_failure_routes_to_needs_card_update_not_infinite_retry(self, monkeypatch):
        """P2-10（第二意見審查 LOW）：card_token 解密失敗（KEK 輪替未 re-encrypt、密文毀損）
        是永久性壞資料——不扣款、release claim、走 needs_card_update dunning 停止無限重試，
        而不是靜默 return 讓 sweep 每輪重撞同一個壞 token。"""
        m = _patch(monkeypatch)
        monkeypatch.setattr(rs, "decrypt", lambda v: (_ for _ in ()).throw(ValueError("MAC check failed")))
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub(card_token="v1:garbage")})
        m["svc"].charge_renewal.assert_not_awaited()      # 未扣款
        m["webhook"].release.assert_awaited_once()         # claim 釋放
        saved = m["user_repo"].update_subscription_fields.await_args.args[1]
        assert saved["status"] == "past_due" and saved["needs_card_update"] is True
        assert saved["next_retry_at"] is None              # 換卡類不自動重試

    async def test_pending_plan_change_charges_target_tier(self, monkeypatch):
        # 期末降級：pro→basic 的 pending_plan_change → 續扣單用目標 tier basic
        m = _patch(monkeypatch, charge_resp={"statusCode": "Success", "tradeId": "T"})
        sub = _sub(tier="pro", pending_plan_change={"tier": "basic", "billing_cycle": "monthly"})
        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": sub})
        created = m["order_repo"].create.await_args.args[0]
        assert created["tier"] == "basic" and created["type"] == "renewal"


class TestSweep:
    """run_renewal_sweep 隔離層（P1-7）：單筆例外不擋整輪 + 孤兒 claim 修復。

    比照 test_invoice_service.py 的 TestSweep 形狀：poison-doc 測試用 FakeCursor 餵
    db.users.find() 的三次序列呼叫（到期續扣/past_due重試/寬限降級），聚焦排程隔離
    本身；orphan-claim 兩測直接對 _attempt_charge 下手（沿用既有 _patch helper），
    聚焦 claim 是否正確 release，不重複測整輪 sweep。
    """

    def _db_with_cursors(self, *cursor_docs):
        """cursor_docs 依序對應 sweep 內三個 db.users.find() 呼叫。"""
        db = MagicMock()
        db.users.find = MagicMock(side_effect=[FakeCursor(docs) for docs in cursor_docs])
        return db

    async def test_poison_user_does_not_stall_the_whole_sweep(self, monkeypatch):
        u1 = {"_id": "u1", "subscription": _sub()}
        u2 = {"_id": "u2", "subscription": _sub()}
        db = self._db_with_cursors([u1, u2], [], [])

        attempt = AsyncMock(side_effect=[RuntimeError("boom"), None])
        monkeypatch.setattr(rs, "_attempt_charge", attempt)

        counts = await rs.run_renewal_sweep(db)
        assert counts == {"charged": 1, "retried": 0, "expired": 0, "errored": 1, "skipped_duplicate": 0}
        assert attempt.await_count == 2  # 第一筆炸掉不擋第二筆被處理

    async def test_duplicate_pending_order_releases_claim_and_continues(self, monkeypatch):
        # 使用者走 /update-card 建了 in-flight pending recovery 單 → DuplicatePendingOrderError
        # 是預期情況，不是錯誤：release claim、不繼續扣款、也不向上拋例外。
        m = _patch(monkeypatch)
        m["order_repo"].create = AsyncMock(side_effect=DuplicatePendingOrderError("u1", "renewal"))
        result = await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        assert result == "skipped_duplicate"
        m["webhook"].release.assert_awaited_once()
        m["svc"].charge_renewal.assert_not_awaited()

    async def test_sweep_counts_duplicate_pending_as_skipped_not_charged(self, monkeypatch):
        # F6：DuplicatePendingOrderError 不是「已扣款」也不是「錯誤」，sweep 該計入
        # skipped_duplicate，不能落進 charged/retried。
        u1 = {"_id": "u1", "subscription": _sub()}
        db = self._db_with_cursors([u1], [], [])
        monkeypatch.setattr(rs, "_attempt_charge", AsyncMock(return_value="skipped_duplicate"))
        counts = await rs.run_renewal_sweep(db)
        assert counts == {"charged": 0, "retried": 0, "expired": 0, "errored": 0, "skipped_duplicate": 1}

    async def test_setup_exception_releases_claim_and_raises(self, monkeypatch):
        # 建單前置作業（定價/查單）任何非預期例外都要 release 孤兒 claim，並向上拋
        # 讓 sweep 層（run_renewal_sweep 的 try/except）接住、計入 errored。
        m = _patch(monkeypatch)
        m["svc"].get_subscription_price = MagicMock(side_effect=RuntimeError("price lookup failed"))
        with pytest.raises(RuntimeError):
            await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})
        m["webhook"].release.assert_awaited_once()
        m["svc"].charge_renewal.assert_not_awaited()


class TestDeterministicOrderNo:
    def test_stable_per_attempt(self):
        a = rs._renewal_order_no("6a631c4ec1ad174ecb0a716d", 1787446766, 2)
        b = rs._renewal_order_no("6a631c4ec1ad174ecb0a716d", 1787446766, 2)
        c = rs._renewal_order_no("6a631c4ec1ad174ecb0a716d", 1787446766, 3)
        assert a == b and a != c and len(a) <= 50


# ── P0-2(b)：dunning 更新 / 降級的樂觀併發 guard ─────────────────────────────────

class TestApplyUpdatesGuard:
    async def test_stale_guard_is_silently_skipped(self, monkeypatch):
        """update_subscription_fields 回 False（guard 不符，代表併發續約已推進 next_charge_at）
        → 不拋例外、只記警告（呼叫端不重試，下一輪 sweep 會用新狀態重新判斷）。"""
        user_repo = MagicMock()
        user_repo.update_subscription_fields = AsyncMock(return_value=False)
        monkeypatch.setattr(rs, "UserRepository", lambda db: user_repo)

        await rs._apply_updates(MagicMock(), "u1", {"next_charge_at": 1000}, {"status": "past_due"})

        user_repo.update_subscription_fields.assert_awaited_once_with(
            "u1", {"status": "past_due"}, guard={"subscription.next_charge_at": 1000}
        )


class TestDowngradeGuard:
    async def test_guard_failure_skips_downgrade_and_returns_false(self, monkeypatch):
        settlement = MagicMock()
        settlement._expire_to_free = AsyncMock(return_value=False)
        monkeypatch.setattr(rs, "build_order_settlement", lambda db: settlement)

        ok = await rs._downgrade(
            MagicMock(), "u1", reason="hard_stop:X", sub_snapshot={"next_charge_at": 1000}
        )
        assert ok is False
        settlement._expire_to_free.assert_awaited_once_with(
            "u1", guard={"subscription.next_charge_at": 1000}
        )

    async def test_no_snapshot_passes_no_guard(self, monkeypatch):
        """呼叫端沒有快照可傳（sub_snapshot=None）→ guard=None，行為等同舊版一律降級。"""
        settlement = MagicMock()
        settlement._expire_to_free = AsyncMock(return_value=True)
        monkeypatch.setattr(rs, "build_order_settlement", lambda db: settlement)

        ok = await rs._downgrade(MagicMock(), "u1", reason="grace_expired")
        assert ok is True
        settlement._expire_to_free.assert_awaited_once_with("u1", guard=None)

    async def test_hard_stop_downgrade_skipped_stale_does_not_send_email(self, monkeypatch):
        """P0-2(b) 的完整鏈路：guard 失敗 → _downgrade 回 False → _handle_failure 不寄
        『已降級』通知信（訂閱其實已被併發續約救回，寄這封信會誤導用戶）。"""
        m = _patch(monkeypatch, charge_resp={"statusCode": "CreditCardBlacklist"})
        m["settlement"]._expire_to_free = AsyncMock(return_value=False)
        send_email = AsyncMock()
        monkeypatch.setattr(rs, "_send_email", send_email)

        await rs._attempt_charge(MagicMock(), {"_id": "u1", "subscription": _sub()})

        m["settlement"]._expire_to_free.assert_awaited_once()
        send_email.assert_not_awaited()


# ── P0-2(a)：periodic_renewal_check 的 sweep lease gate ─────────────────────────

class TestPeriodicRenewalCheckLeaseGate:
    """用 asyncio.sleep 的 side_effect 拋 CancelledError 收束無限迴圈，只驗證單輪行為
    （比照本檔案既有的 async 測試慣例，不真的跑多輪）。
    """

    async def _run_one_round(self, monkeypatch, *, claim_ok=True, claim_raises=None):
        lease_repo = MagicMock()
        if claim_raises:
            lease_repo.claim_window = AsyncMock(side_effect=claim_raises)
        else:
            lease_repo.claim_window = AsyncMock(return_value=claim_ok)
        monkeypatch.setattr(rs, "JobLeaseRepository", lambda db: lease_repo)

        sweep = AsyncMock()
        monkeypatch.setattr(rs, "run_renewal_sweep", sweep)
        monkeypatch.setattr(rs.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await rs.periodic_renewal_check(MagicMock(), interval_seconds=1800)
        return lease_repo, sweep

    async def test_lease_lost_skips_sweep(self, monkeypatch):
        lease_repo, sweep = await self._run_one_round(monkeypatch, claim_ok=False)
        lease_repo.claim_window.assert_awaited_once_with("renewal_sweep", 1800)
        sweep.assert_not_awaited()

    async def test_lease_won_runs_sweep(self, monkeypatch):
        _, sweep = await self._run_one_round(monkeypatch, claim_ok=True)
        sweep.assert_awaited_once()

    async def test_lease_check_exception_fails_open_and_runs_sweep(self, monkeypatch):
        _, sweep = await self._run_one_round(monkeypatch, claim_raises=RuntimeError("mongo down"))
        sweep.assert_awaited_once()  # fail-open：lease 查詢失敗仍照跑本輪
