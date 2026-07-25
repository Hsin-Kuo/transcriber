"""OrderSettlement — 把 91APP 付款收斂成帳號狀態變更的 deep module。

兩個入口：
- `open_pending(order_data)`：建 pending [[Order]]（防連點冷卻 + supersede 既有
  pending + 靠 DB unique index 防並發 TOCTOU）。
- `settle(notification)`：收一個 typed [[PaymentNotification]]，依
  `(order_type, is_first_payment, success)` 矩陣套用 Settlement effect
  （啟用訂閱 / 續訂展期 / 降為 free / 加值 / 拒絕重複完成），回 SettleResult。

91APP 是 merchant-initiated：無 gateway 委託，故無「終止委託」動作——取消訂閱只是
停止排程（見 quota.py 到期掃描與 Phase 2 續扣排程器）。cardToken 由 router `/pay`
從 request-by-txnToken 回應捕捉、暫存 pending order，首扣成功時搬進 subscription。

settle() 不碰任何金流 provider / webhook / FastAPI——test surface 就是
PaymentNotification dataclass。詳見 CONTEXT.md「金流與訂單」。
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from fastapi import HTTPException

from ..database.repositories.order_repo import (
    DuplicatePendingOrderError,
    OrderRepository,
)
from ..database.repositories.user_repo import UserRepository
from ..models.quota import build_quota_from_tier
from ..utils.billing_period import calc_period_end
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

log = get_logger(__name__)

# 防連點冷卻秒數：同類型付款在這個秒數內重複送出才擋（防誤觸 / 連點）；
# 超過此秒數的舊 pending 單不擋，改由 supersede 取代，讓使用者可立即重試。
PENDING_COOLDOWN_SECONDS = 30

_SUBSCRIPTION_TYPES = ("subscription", "upgrade_subscription", "downgrade_subscription", "renewal")


@dataclass
class PaymentNotification:
    """跨 settlement seam 的 typed payload（router 回查交易 + claim 後交進來）。

    is_first_payment：初次建立訂閱（含升降級換約）為 True；續扣（Phase 2 排程器）為 False。
    trade_id：91APP 交易序號。cardToken 不走這裡——由 /pay 存進 order，settle 從 order 讀。
    """
    order_no: str
    success: bool
    is_first_payment: bool
    trade_id: str = ""


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
    ):
        self.order_repo = order_repo
        self.user_repo = user_repo

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

        if not n.success:
            await self.order_repo.update_by_order_no(n.order_no, {"status": "failed"})
            # 續扣失敗不在此即時降 free——由 renewal_service 的 dunning 接手（past_due→重試→寬限滿降 free）。
            # settle 失敗僅標記 order + 回 FAILED。
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
        period_end = calc_period_end(billing_cycle, now)

        await self.order_repo.update_by_order_no(n.order_no, {"trade_id": n.trade_id})

        if not n.is_first_payment:
            # 續扣成功：標 order paid + 滾計費週期 + 歸零當期用量 + 清 dunning（past_due→active）
            await self.order_repo.update_by_order_no(
                n.order_no, {"status": "paid", "paid_at": now.timestamp()}
            )
            full_user = await self.user_repo.get_by_id(user_id)
            sub = full_user.get("subscription", {}) if full_user else {}
            # 方案變更（期末降級 pending_plan_change 生效）：續扣單帶的是「目標 tier」。
            #   以 tier 判定（quota 由 tier 決定，與 billing_cycle 無關）。
            plan_changed = sub.get("tier") != tier
            sub.update({
                "status": "active",  # 若原為 past_due（重試/換卡成功）→ 回 active
                "tier": tier,                       # 套用續扣單的 tier（降級生效時 = 目標 tier）
                "billing_cycle": billing_cycle,
                "current_period_start": now.timestamp(),
                "current_period_end": period_end.timestamp(),
                "next_charge_at": period_end.timestamp(),
                "pending_plan_change": None,         # 已套用 → 清空
                "dunning_attempts": 0,
                "next_retry_at": None,
                "dunning_started_at": None,
                "needs_card_update": False,
                "last_payment_error": None,
                "updated_at": now.timestamp(),
            })
            # 換卡挽回：recovery order 帶新 card_token → 更新綁定
            new_token = order.get("card_token")
            if new_token:
                sub["card_token"] = new_token
            await self.user_repo.update_subscription(user_id, sub)
            await self.user_repo.reset_monthly_usage(user_id, now)
            # 方案有變更（升/降級生效）→ 一律重套目標方案額度；否則同 tier 續扣：
            #   月繳重套最新、年繳凍結（週期內由 lazy refill 補額不改額度）。
            if plan_changed or billing_cycle == "monthly":
                await self.user_repo.update_quota(user_id, build_quota_from_tier(tier))
            # 降級生效（新 tier 額度變小）→ 釋放超額釘選音檔進寬限期
            if plan_changed:
                await self._reconcile_pinned_audio(user_id, tier)
            log.info("subscription.renewed", user_id=user_id, type=order_type, plan_changed=plan_changed)
            return SettleResult(SettleOutcome.RENEWED, n.order_no)

        # 首期成功
        full_user = await self.user_repo.get_by_id(user_id)
        cur_sub = full_user.get("subscription", {}) if full_user else {}
        if self._is_duplicate_first_completion(cur_sub, order):
            await self._reject_duplicate(order, user_id)
            return SettleResult(SettleOutcome.REJECTED_DUPLICATE, n.order_no)

        # 升級：把舊方案剩餘額度結轉進 extra_quota（91APP 無 gateway 委託可終止，換約即換 tier）
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
            "next_charge_at": period_end.timestamp(),  # Phase 2 續扣排程器讀此
            "cancel_at_period_end": False,
            "canceled_at": None,
            "pending_plan_change": None,
            "payment_provider": "91app",
            "active_order_no": order["merchant_order_no"],
            "card_token": order.get("card_token", ""),      # /pay 捕捉並暫存於 order
            "merchant_consumer_id": str(user_id),           # 綁卡與續扣共用
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
        # 降級生效後（quota 已 commit）：釋放超過新方案額度的釘選音檔，進寬限期。
        #   best-effort（reconcile 自行吞例外），不影響已成功的訂閱啟用。
        if order_type == "downgrade_subscription":
            await self._reconcile_pinned_audio(user_id, tier)
        return SettleResult(SettleOutcome.ACTIVATED, n.order_no)

    # ── 額外額度（一次性加購）────────────────────────────────────────────────

    async def _settle_extra_quota(self, order: dict, n: PaymentNotification) -> SettleResult:
        user_id = order["user_id"]
        extra_dur = order.get("extra_duration_minutes", 0)
        extra_ai = order.get("extra_ai_summaries", 0)
        await self.user_repo.add_extra_quota(user_id, extra_dur, extra_ai)
        await self.order_repo.update_by_order_no(n.order_no, {
            "status": "paid",
            "trade_id": n.trade_id,
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
        # 降為 free（quota 已 commit）：free 不能保留音檔 → 釋放全部釘選進寬限期。
        await self._reconcile_pinned_audio(user_id, "free")

    async def _reconcile_pinned_audio(self, user_id: str, new_tier: str) -> None:
        """降額後核對釘選音檔（best-effort，絕不拋例外拖垮結算流程）。"""
        try:
            from .pinned_audio_reconciler import reconcile_pinned_audio
            await reconcile_pinned_audio(self.user_repo.db, user_id, new_tier)
        except Exception as e:
            log.error("subscription.reconcile_pinned_audio.failed", user_id=user_id, error=str(e), exc_info=True)

    @staticmethod
    def _is_duplicate_first_completion(sub: dict, order: dict) -> bool:
        """判斷這筆 first-payment 是否為『重複完成』（sibling 已先啟動）。

        使用者過了冷卻後重開 checkout 會 supersede 舊單並建新單，兩張付款頁
        都可能被完成。第一張完成正常啟動；第二張完成時應被擋下（需退款）。
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

    async def _reject_duplicate(self, order: dict, user_id: str) -> None:
        """重複完成處理：標記需退款，不啟用/不加值。

        首期已實際扣款，故標記 needs_refund + 送 Sentry 供人工用 91APP refund API 退款。
        91APP 無 gateway 委託可終止，這裡不再有終止動作。
        """
        ono = order["merchant_order_no"]
        await self.order_repo.update_by_order_no(ono, {
            "status": "paid",
            "paid_at": get_utc_timestamp(),
            "is_duplicate": True,
            "needs_refund": True,
        })
        log.warning(
            "subscription.duplicate_completion.rejected",
            user_id=user_id, order_no=ono,
        )
        self._capture_refund_alert(user_id, ono, "重複完成已拒絕，需退首期款")

    @staticmethod
    def _capture_refund_alert(user_id: str, order_no: str, detail: str) -> None:
        """需人工退款事件 → 送 Sentry。lazy import：未裝 sentry_sdk 時靜默略過。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("payment.issue", "needs_manual_refund")
                scope.set_context("refund", {"user_id": user_id, "order_no": order_no, "detail": detail})
                sentry_sdk.capture_message(
                    f"91APP 付款需人工退款：user={user_id} order={order_no}",
                    level="error",
                )
        except Exception:
            pass


def build_order_settlement(db) -> OrderSettlement:
    """以 request-scoped db 組出 OrderSettlement（repos 從 db 建；不再依賴金流 provider）。"""
    return OrderSettlement(
        order_repo=OrderRepository(db),
        user_repo=UserRepository(db),
    )
