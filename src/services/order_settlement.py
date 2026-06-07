"""OrderSettlement — 把藍新付款收斂成帳號狀態變更的 deep module。

兩個入口：
- `open_pending(order_data)`：建 pending [[Order]]（防連點冷卻 + supersede 既有
  pending + 靠 DB unique index 防並發 TOCTOU）。
- `settle(notification)`：收一個 typed [[PaymentNotification]]，依
  `(order_type, is_first_payment, success)` 矩陣套用 Settlement effect
  （啟用訂閱 / 續訂展期 / 降為 free / 加值 / 拒絕重複完成），回 SettleResult。

Router 的殘留責任：checkout 組裝（算 amount、判 upgrade/downgrade/scheduled、用
newebpay_service adapter 產 form）、webhook 解密、idempotency claim/release。
settle() 完全不碰 AES / webhook_repo / FastAPI——它的 test surface 就是
PaymentNotification dataclass。詳見 CONTEXT.md「金流與訂單」。
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi import HTTPException

from ..database.repositories.order_repo import (
    DuplicatePendingOrderError,
    OrderRepository,
)
from ..database.repositories.user_repo import UserRepository
from ..models.quota import build_quota_from_tier
from ..utils.newebpay_service import NewebpayService, get_newebpay_service
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

log = get_logger(__name__)

# 防連點冷卻秒數：同類型付款在這個秒數內重複送出才擋（防誤觸 / 連點）；
# 超過此秒數的舊 pending 單不擋，改由 supersede 取代，讓使用者可立即重試。
PENDING_COOLDOWN_SECONDS = 30

_SUBSCRIPTION_TYPES = ("subscription", "upgrade_subscription", "downgrade_subscription")


@dataclass
class PaymentNotification:
    """跨 settlement seam 的 typed payload（router 解密 + claim 後交進來）。

    is_first_payment：藍新定期定額以 Result 是否含 AlreadyTimes 區分初次建立 vs
    續扣（==1 為首期）；MPG 一次性付款一律視為 first。
    """
    order_no: str
    success: bool
    is_first_payment: bool
    period_no: str = ""
    trade_no: str = ""
    auth_times: Optional[int] = None


class SettleOutcome(str, Enum):
    """settle() 對單一 notification 的結果（供 router 記 log / 測試斷言）。"""
    ACTIVATED = "activated"                 # 首期成功，啟用訂閱
    RENEWED = "renewed"                     # 續扣成功，展期
    EXPIRED = "expired"                     # 續扣失敗，降為 free
    GRANTED = "granted"                     # extra_quota 加值成功
    REJECTED_DUPLICATE = "rejected_duplicate"  # sibling 已先啟動 → 拒絕重複完成
    FAILED = "failed"                       # 首期失敗 / extra_quota 失敗
    ORDER_NOT_FOUND = "order_not_found"
    ALREADY_PAID = "already_paid"           # order 狀態已 paid（重發短路）


@dataclass
class SettleResult:
    outcome: SettleOutcome
    order_no: str = ""


class OrderSettlement:
    def __init__(
        self,
        *,
        order_repo: OrderRepository,
        user_repo: UserRepository,
        newebpay: NewebpayService,
    ):
        self.order_repo = order_repo
        self.user_repo = user_repo
        self.newebpay = newebpay

    # ── 建單（checkout 入口）────────────────────────────────────────────────

    async def open_pending(self, order_data: dict) -> dict:
        """付款防重（冷卻 + supersede）後建立 pending Order。

        order_data 須含 user_id / type / status="pending" 與該 type 的欄位
        （tier / billing_cycle / amount_twd / prev_* / extra_* 等，由 router 組裝）。
        冷卻內重複送出或撞並發 unique index → HTTPException(429)。
        """
        user_id = order_data["user_id"]
        order_type = order_data["type"]

        if await self.order_repo.has_recent_pending_order(
            user_id, order_type, PENDING_COOLDOWN_SECONDS
        ):
            raise HTTPException(status_code=429, detail="付款請求處理中，請稍候幾秒再試")
        superseded = await self.order_repo.supersede_pending_orders(user_id, order_type)
        if superseded:
            log.info(
                "subscription.pending.superseded",
                user_id=user_id, order_type=order_type, count=superseded,
            )

        try:
            return await self.order_repo.create(order_data)
        except DuplicatePendingOrderError:
            # 兩個幾乎同時的請求都通過冷卻+supersede 後，DB partial unique index 只讓
            # 一張 pending 成功，另一張在這裡被攔成 429（而非 500）。防 TOCTOU race。
            raise HTTPException(status_code=429, detail="付款請求處理中，請稍候幾秒再試")

    # ── 收斂（webhook 入口）────────────────────────────────────────────────

    async def settle(self, n: PaymentNotification) -> SettleResult:
        """把單一 notification 收斂成帳號狀態變更。"""
        order = await self.order_repo.get_by_order_no(n.order_no)
        if not order:
            log.warning("subscription.webhook.order_not_found", merchant_order_no=n.order_no)
            return SettleResult(SettleOutcome.ORDER_NOT_FOUND, n.order_no)

        # order 生命週期 idempotency：首期重發但 order 已 paid → 短路（webhook_repo
        # claim 擋同一封重發，這裡擋「不同封但 order 已處理」）。
        if n.is_first_payment and order.get("status") == "paid":
            log.warning("subscription.webhook.order_already_paid", merchant_order_no=n.order_no)
            return SettleResult(SettleOutcome.ALREADY_PAID, n.order_no)

        order_type = order.get("type", "subscription")
        user_id = order["user_id"]

        if not n.success:
            await self.order_repo.update_by_order_no(n.order_no, {"status": "failed"})
            # 續扣失敗（非首期、非一次性）→ 立即降為 free
            if not n.is_first_payment and order_type in _SUBSCRIPTION_TYPES:
                await self._expire_to_free(user_id)
                return SettleResult(SettleOutcome.EXPIRED, n.order_no)
            log.warning("payment.failed", merchant_order_no=n.order_no, type=order_type)
            return SettleResult(SettleOutcome.FAILED, n.order_no)

        if order_type in _SUBSCRIPTION_TYPES:
            return await self._settle_subscription(order, n)
        if order_type == "extra_quota":
            return await self._settle_extra_quota(order, n)

        log.warning("payment.unknown_order_type", merchant_order_no=n.order_no, type=order_type)
        return SettleResult(SettleOutcome.FAILED, n.order_no)

    # ── 訂閱（subscription / upgrade / downgrade）─────────────────────────────

    async def _settle_subscription(self, order: dict, n: PaymentNotification) -> SettleResult:
        now = datetime.utcnow()
        user_id = order["user_id"]
        tier = order["tier"]
        billing_cycle = order["billing_cycle"]
        order_type = order.get("type", "subscription")
        period_end = self.newebpay.calc_period_end(billing_cycle, now)

        # 定期定額成功一律先記委託編號 / 期數 / 交易序號
        await self.order_repo.update_by_order_no(n.order_no, {
            "period_no": n.period_no,
            "auth_times": n.auth_times or 1,
            "newebpay_trade_no": n.trade_no,
        })

        if not n.is_first_payment:
            # 續扣成功：只滾計費週期 + 歸零當期用量
            full_user = await self.user_repo.get_by_id(user_id)
            sub = full_user.get("subscription", {}) if full_user else {}
            sub.update({
                "current_period_start": now.timestamp(),
                "current_period_end": period_end.timestamp(),
                "updated_at": now.timestamp(),
            })
            await self.user_repo.update_subscription(user_id, sub)
            await self.user_repo.reset_monthly_usage(user_id, now)
            log.info("subscription.renewed", user_id=user_id, type=order_type)
            return SettleResult(SettleOutcome.RENEWED, n.order_no)

        # 首期成功
        full_user = await self.user_repo.get_by_id(user_id)
        cur_sub = full_user.get("subscription", {}) if full_user else {}
        if self._is_duplicate_first_completion(cur_sub, order):
            await self._reject_duplicate(order, user_id, n.period_no)
            return SettleResult(SettleOutcome.REJECTED_DUPLICATE, n.order_no)

        # 升降級：終止舊委託；升級另把舊方案剩餘額度結轉進 extra_quota
        if order_type in ("upgrade_subscription", "downgrade_subscription"):
            await self._terminate_prev(order)
        if order_type == "upgrade_subscription":
            extra_dur = order.get("extra_duration_minutes", 0)
            extra_ai = order.get("extra_ai_summaries", 0)
            if extra_dur or extra_ai:
                await self.user_repo.add_extra_quota(user_id, extra_dur, extra_ai)

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
            "period_no": n.period_no,
            # 沿用既有訂閱的建立時間（降級/升級換約時不重置）；全新訂閱才用 now
            "created_at": cur_sub.get("created_at", now.timestamp()),
            "updated_at": now.timestamp(),
        }
        await self.user_repo.update_subscription(user_id, subscription)
        await self.user_repo.update_quota(user_id, build_quota_from_tier(tier))
        await self.user_repo.reset_monthly_usage(user_id, now)
        await self.order_repo.update_by_order_no(
            n.order_no, {"status": "paid", "paid_at": now.timestamp()}
        )
        log.info("subscription.activated", user_id=user_id, tier=tier, billing_cycle=billing_cycle, type=order_type)
        # 對帳收斂：終止此 user 其他非當前的 active 委託（防雙重完成造成孤兒重複扣款）
        await self._terminate_orphan_contracts(user_id, n.period_no)
        return SettleResult(SettleOutcome.ACTIVATED, n.order_no)

    # ── 額外額度（MPG 一次性）────────────────────────────────────────────────

    async def _settle_extra_quota(self, order: dict, n: PaymentNotification) -> SettleResult:
        user_id = order["user_id"]
        extra_dur = order.get("extra_duration_minutes", 0)
        extra_ai = order.get("extra_ai_summaries", 0)
        await self.user_repo.add_extra_quota(user_id, extra_dur, extra_ai)
        await self.order_repo.update_by_order_no(n.order_no, {
            "status": "paid",
            "newebpay_trade_no": n.trade_no,
            "paid_at": datetime.utcnow().timestamp(),
        })
        log.info(
            "payment.extra_quota.purchased",
            user_id=user_id, extra_duration_minutes=extra_dur, extra_ai_summaries=extra_ai,
        )
        return SettleResult(SettleOutcome.GRANTED, n.order_no)

    # ── 內部 effect helpers ─────────────────────────────────────────────────

    async def _expire_to_free(self, user_id: str) -> None:
        """續扣失敗：訂閱標 expired、quota 降為 free。"""
        full_user = await self.user_repo.get_by_id(user_id)
        sub = full_user.get("subscription", {}) if full_user else {}
        sub.update({
            "status": "expired",
            "cancel_at_period_end": False,
            "updated_at": datetime.utcnow().timestamp(),
        })
        await self.user_repo.update_subscription(user_id, sub)
        await self.user_repo.update_quota(user_id, build_quota_from_tier("free"))
        log.warning("subscription.renewal.payment_failed", user_id=user_id)

    async def _terminate_prev(self, order: dict) -> None:
        """升降級首期成功後，終止被取代的前一張藍新委託。"""
        prev_order_no = order.get("prev_order_no")
        prev_period_no = order.get("prev_period_no")
        if not (prev_order_no and prev_period_no):
            return
        ok, msg = await self.newebpay.terminate_period_contract(prev_order_no, prev_period_no)
        if not ok:
            log.warning(
                "subscription.prev_contract_terminate_failed",
                type=order.get("type"), prev_period_no=prev_period_no, message=msg,
            )

    @staticmethod
    def _is_duplicate_first_completion(sub: dict, order: dict) -> bool:
        """判斷這筆 first-payment 是否為『重複完成』（sibling 已先啟動）。

        使用者過了冷卻後重開 checkout 會 supersede 舊單並建新單，兩張藍新付款頁
        都可能被完成。第一張完成正常啟動；第二張完成時應被擋下。
        """
        if sub.get("status") != "active":
            return False  # 無既有 active → 第一筆完成，正常啟動
        active_order = sub.get("active_order_no")
        if not active_order or active_order == order.get("merchant_order_no"):
            return False
        otype = order.get("type", "subscription")
        if otype in ("upgrade_subscription", "downgrade_subscription"):
            # 合法升降級：目前 active 應為這張要取代的前一張(prev)；
            # 若前任已被別的 sibling 換掉（active ≠ prev）→ 這張是重複完成。
            return active_order != order.get("prev_order_no")
        # 新訂閱 / reactivate：重複新訂閱則 sibling 已把 cancel_at_period_end 設為 False。
        return not sub.get("cancel_at_period_end", False)

    async def _reject_duplicate(self, order: dict, user_id: str, period_no: str) -> None:
        """重複完成處理：終止這張多出來的委託、標記需退款，不啟用/不加值。

        首期已立即授權扣款（PeriodStartType=2），故標記 needs_refund + 送 Sentry
        供人工退首期款。狀態保留 paid（period_no 已設），終止失敗時下次啟動的對帳
        收斂仍會接手重試。
        """
        ono = order["merchant_order_no"]
        try:
            ok, msg = await self.newebpay.terminate_period_contract(ono, period_no)
        except Exception as e:
            ok, msg = False, f"exception: {e}"
        already = ("無法重複終止" in (msg or "")) or ("已終止" in (msg or ""))
        updates = {
            "status": "paid",
            "paid_at": get_utc_timestamp(),
            "is_duplicate": True,
            "needs_refund": True,
        }
        if ok or already:
            updates["contract_terminated_at"] = get_utc_timestamp()
        await self.order_repo.update_by_order_no(ono, updates)
        log.warning(
            "subscription.duplicate_completion.rejected",
            user_id=user_id, order_no=ono, period_no=period_no, terminate_ok=ok, message=msg,
        )
        self._capture_orphan_contract_alert(
            user_id, period_no, f"重複完成已拒絕，需退首期款；終止結果: ok={ok} msg={msg}"
        )

    async def _terminate_orphan_contracts(self, user_id: str, keep_period_no: str) -> None:
        """對帳收斂：終止該 user 名下「已 paid 但 period_no ≠ 目前 active」的其他委託。

        best-effort：本函式在訂閱啟動成功之後執行，絕不可拋例外拖垮已成功的啟用；
        任何終止失敗改為記錄 + 送 Sentry 供人工處理。冪等（已標記或藍新回已終止皆略過）。
        """
        # 防呆：拿不到目前委託編號時不敢動（否則 $nin:[None] 可能誤終止其他委託）
        if not keep_period_no:
            return
        try:
            orphans = await self.order_repo.find_orphan_contracts(user_id, keep_period_no)
        except Exception as e:
            log.error("subscription.orphan_contract.scan_failed", user_id=user_id, error=str(e), exc_info=True)
            return

        for o in orphans:
            pno = o.get("period_no")
            ono = o.get("merchant_order_no")
            if not pno or not ono:
                continue
            try:
                ok, msg = await self.newebpay.terminate_period_contract(ono, pno)
            except Exception as e:
                log.error("subscription.orphan_contract.terminate_error", user_id=user_id, period_no=pno, error=str(e), exc_info=True)
                self._capture_orphan_contract_alert(user_id, pno, str(e))
                continue
            already = ("無法重複終止" in (msg or "")) or ("已終止" in (msg or ""))
            if ok or already:
                await self.order_repo.update_by_order_no(ono, {"contract_terminated_at": get_utc_timestamp()})
                log.info("subscription.orphan_contract.terminated", user_id=user_id, period_no=pno, already=already)
            else:
                log.warning("subscription.orphan_contract.terminate_failed", user_id=user_id, period_no=pno, message=msg)
                self._capture_orphan_contract_alert(user_id, pno, msg)

    @staticmethod
    def _capture_orphan_contract_alert(user_id: str, period_no: str, detail: str) -> None:
        """孤兒/重複委託未能自動終止 → 送 Sentry 供人工終止（可能造成重複扣款）。

        lazy import：未裝 sentry_sdk 時靜默略過，且絕不在錯誤處理路徑上再炸一次。
        """
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("payment.issue", "orphan_contract_terminate_failed")
                scope.set_context("orphan_contract", {"user_id": user_id, "period_no": period_no, "detail": detail})
                sentry_sdk.capture_message(
                    f"藍新定期定額委託未能自動終止，需人工終止：user={user_id} period_no={period_no}",
                    level="error",
                )
        except Exception:
            pass


def build_order_settlement(db) -> OrderSettlement:
    """以 request-scoped db 組出 OrderSettlement（repos 從 db 建、newebpay 用 singleton）。"""
    return OrderSettlement(
        order_repo=OrderRepository(db),
        user_repo=UserRepository(db),
        newebpay=get_newebpay_service(),
    )
