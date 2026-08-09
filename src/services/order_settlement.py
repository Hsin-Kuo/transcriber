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
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException

from ..database.repositories.order_repo import (
    DuplicatePendingOrderError,
    OrderRepository,
)
from ..database.repositories.user_repo import UserRepository
from ..models.quota import build_quota_from_tier
from ..utils.billing_period import calc_period_end
from ..utils.sentry_helpers import create_background_task
from ..utils.logger import get_logger

log = get_logger(__name__)

# settle() 開票白名單：付款成功且帳號狀態已生效的 outcome 才觸發開票
# （REJECTED_DUPLICATE / FAILED / ALREADY_PAID / EXPIRED / ORDER_NOT_FOUND 都不開票）。
_INVOICE_TRIGGER_OUTCOMES = frozenset({"activated", "renewed", "granted"})


async def _default_invoice_issuer(db, order: dict) -> None:
    """lazy import：避免 order_settlement（純 test surface）無條件拉進 httpx/defusedxml 等
    invoice_service 的 transport 依賴，比照既有 `_reconcile_pinned_audio` 的 lazy import 慣例。
    """
    from .invoice_service import issue_for_order
    await issue_for_order(db, order)


# 防連點冷卻秒數：同類型付款在這個秒數內重複送出才擋（防誤觸 / 連點）；
# 超過此秒數的舊 pending 單不擋，改由 supersede 取代，讓使用者可立即重試。
PENDING_COOLDOWN_SECONDS = 30

# resettle_entitlement 補償重試上限：達此值轉人工（needs_manual + Sentry），不再
# 無限重試同一筆。單一定義（P2-G，第二意見審查）：payment_reconciliation.py 的
# iter_entitlement_pending 查詢上限 import 這個常數，避免兩處各自硬編碼 5 飄移。
ENTITLEMENT_RESETTLE_MAX_RETRY = 5

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
        invoice_issuer: Optional[Callable[[Any, dict], Awaitable[None]]] = None,
    ):
        self.order_repo = order_repo
        self.user_repo = user_repo
        # 注入點：測試可傳 fake issuer；生產預設 lazy-import 真正的 invoice_service.issue_for_order。
        self._invoice_issuer = invoice_issuer or _default_invoice_issuer

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
        """把單一 notification 收斂成帳號狀態變更。

        P0-1/P0-3（併發正確性）：settle() 只有一個權威的「已處理過」判斷點——下方
        `claim_paid` 的原子 status!=paid→paid 搶單，不分首購/續扣、不分呼叫路徑
        （/callback webhook 或 renewal sweep）。開頭的 order.status=="paid" 快路徑
        同樣不分 is_first_payment（舊版只在首購擋，續扣重放沒有防線）——但它只是省一次
        不必要的 handler dispatch，真正擋住併發重入的是 claim_paid：即使兩個 settle()
        幾乎同時通過快路徑檢查，也只有一個能搶到 claim_paid，另一個回 ALREADY_PAID。
        """
        order = await self.order_repo.get_by_order_no(n.order_no)
        if not order:
            log.warning("subscription.webhook.order_not_found", merchant_order_no=n.order_no)
            return SettleResult(SettleOutcome.ORDER_NOT_FOUND, n.order_no)

        if order.get("status") == "paid":
            log.warning("subscription.webhook.order_already_paid", merchant_order_no=n.order_no)
            return SettleResult(SettleOutcome.ALREADY_PAID, n.order_no)

        order_type = order.get("type", "subscription")

        if not n.success:
            # mark_failed_unless_paid：擋住「快路徑檢查之後、claim_paid 之前」的 TOCTOU
            # 縫隙——遲到的舊 trade 失敗通知不能把已被另一封通知結算成功的單打成 failed。
            marked = await self.order_repo.mark_failed_unless_paid(n.order_no, {"status": "failed"})
            if not marked:
                log.warning("subscription.webhook.failed_notify_ignored_already_paid", merchant_order_no=n.order_no)
            # 續扣失敗不在此即時降 free——由 renewal_service 的 dunning 接手（past_due→重試→寬限滿降 free）。
            log.warning("payment.failed", merchant_order_no=n.order_no, type=order_type)
            return SettleResult(SettleOutcome.FAILED, n.order_no)

        if order_type in _SUBSCRIPTION_TYPES:
            settle_fn = self._settle_subscription
        elif order_type == "extra_quota":
            settle_fn = self._settle_extra_quota
        else:
            log.warning("payment.unknown_order_type", merchant_order_no=n.order_no, type=order_type)
            return SettleResult(SettleOutcome.FAILED, n.order_no)

        # 權威防線（本 PR 核心）：先原子搶單、贏了才施加權益。取捨：搶到 claim_paid 之後、
        # handler 完成之前若 crash，會留下「paid 但權益未施」的單（可被 P1-9 對帳補回）——
        # 比原本「重放 = 權益重複施加（$inc 兩次配額 / 續期兩次）」更便宜、更容易事後修復。
        extra = {"trade_id": n.trade_id} if n.trade_id else None
        if not await self.order_repo.claim_paid(n.order_no, extra_updates=extra):
            log.warning("subscription.webhook.claim_paid_lost_race", merchant_order_no=n.order_no)
            return SettleResult(SettleOutcome.ALREADY_PAID, n.order_no)

        try:
            result = await settle_fn(order, n)
        except Exception as exc:
            # F5（第二意見審查）：claim_paid 已經贏了、但 handler 施加權益中途 crash/
            # 例外——order 已經是 paid，權益卻可能沒施完整。補寫旗標 + Sentry 告警，
            # 讓 P1-9 對帳 sweep 能認出這種單並補施權益；不吞原例外，往上拋讓既有的
            # webhook release / log 邏輯照舊處理。
            await self._mark_entitlement_pending(n.order_no, exc)
            raise

        if result.outcome.value in _INVOICE_TRIGGER_OUTCOMES:
            await self._trigger_invoice(n.order_no)
        return result

    async def _mark_entitlement_pending(self, order_no: str, exc: Exception) -> None:
        """標記「paid 但權益可能未施加完整」+ Sentry 告警（見 settle() 呼叫處）。

        這個方法本身絕不可拋例外——否則會蓋掉呼叫端正在往外拋的原始例外。

        🔴 第二意見審查 P0-A：一併初始化 `entitlement_retry_count: 0`——若留給欄位
        缺省，`OrderRepository.iter_entitlement_pending` 的 `$lt`/`$gte` 範圍查詢
        （MongoDB 的 type bracketing）完全不會匹配缺欄位的文件，真實 crash 留下的單
        會永遠撈不到、對帳補償 sweep 形同虛設。這裡只會被呼叫一次（settle() 短路
        `status=="paid"` 之後不會再進到這個 try/except），不會被 resettle 的
        `$inc` 併發覆寫成 0。
        """
        try:
            await self.order_repo.update_by_order_no(
                order_no, {"entitlement_pending": True, "entitlement_retry_count": 0}
            )
        except Exception as flag_err:
            log.error(
                "settle.entitlement_pending_flag_failed",
                order_no=order_no, error=str(flag_err), exc_info=True,
            )
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("settle_entitlement_pending", {"order_no": order_no, "error": str(exc)})
                sentry_sdk.capture_message("settle.entitlement_pending", level="error")
        except Exception:
            pass

    async def _trigger_invoice(self, order_no: str) -> None:
        """開票背景觸發（91APP 付款成功後自動開立電子發票）。

        create_background_task 本身已用 done-callback 把例外送 Sentry + log（不影響呼叫端），
        這裡再包一層 try/except 是防禦「組 coroutine / 讀 order」這段同步過程本身出錯
        （例如 order 已被刪除）——絕不可讓開票掛掉拖累 settle() 的回傳。
        """
        try:
            order = await self.order_repo.get_by_order_no(order_no)
            if not order:
                log.warning("invoice.trigger.order_not_found", order_no=order_no)
                return
            create_background_task(
                self._invoice_issuer(self.user_repo.db, order),
                name=f"invoice_issue:{order_no}",
            )
        except Exception as e:
            log.error("invoice.trigger.failed", order_no=order_no, error=str(e), exc_info=True)

    # ── 補結算 entitlement_pending（P1-9 對帳 sweep 第二段）─────────────────────

    async def resettle_entitlement(self, order: dict) -> None:
        """補施加一張 `entitlement_pending` 單的權益（`settle()` handler 中途 crash 留下的坑）。

        order 已經是 `paid`（`claim_paid` 早就贏過一次），這裡**直接呼叫對應
        handler**（`_settle_subscription` / `_settle_extra_quota`），繞過 `claim_paid`
        ——不能再走 `settle()` 的公開入口，因為那個入口的權威閘門就是「status!=paid
        才施加」，重跑會被自己的 ALREADY_PAID 短路擋死。

        兩個已知副作用（呼叫端/告警口徑需知情，見金流體檢 P1-9）：
        - 訂閱 handler 的續扣分支會 `reset_monthly_usage`——補償時會把「權益懸置
          期間累積的用量」一併歸零（不只補發權益，連帶重置當期用量）。
        - 續扣 handler 的 `current_period_start/end` 用補償當下的 `now` 重算，起點
          會比原本的付款時間點往後位移（不是回補「原本該有」的週期起訖）。
        兩者都延續 P0-3「寧少發勿重發」的基調：補償不追求分秒對齊，追求「權益一定
        有補到、不會漏發也不會雙發」。

        失敗不吞：不論是 handler 本身失敗、還是 handler 成功後「清旗標」這步失敗
        （見下方獨立 try），都會 `$inc entitlement_retry_count`（+ 達上限寫
        `needs_manual`/Sentry，見 `_handle_resettle_failure`）後原例外照樣往上拋，
        讓呼叫端（sweep）計入 errored、下一輪憑 `entitlement_retry_count` 繼續重試。
        """
        order_no = order["merchant_order_no"]
        order_type = order.get("type", "subscription")
        n = PaymentNotification(
            order_no=order_no,
            success=True,
            is_first_payment=(order_type != "renewal"),
            trade_id=order.get("trade_id", ""),
        )
        try:
            if order_type in _SUBSCRIPTION_TYPES:
                result = await self._settle_subscription(order, n)
            elif order_type == "extra_quota":
                result = await self._settle_extra_quota(order, n)
            else:
                log.warning("settle.resettle_entitlement.unknown_type", order_no=order_no, type=order_type)
                return
        except Exception as exc:
            await self._handle_resettle_failure(order_no, exc)
            raise

        # P1-B（第二意見審查）：清旗標本身也可能失敗（DB 抖動），若不接住並走同一條
        # `_handle_resettle_failure` $inc 記帳路徑，這筆單會在 entitlement_pending
        # 仍是 True 的狀態下被下一輪 sweep 無限重跑——handler 已經成功，但每輪都白白
        # 重跑一次（訂閱型還會重複 reset_monthly_usage + 重算期別）、且永遠不會因為
        # 「重試次數過多」轉人工終止（因為 handler 本身沒有失敗）。獨立 try（不重跑
        # handler）：handler 已確定成功，沒必要因為單純的旗標寫入失敗而重放它的副
        # 作用；接住例外後 re-raise，讓 sweep 計 errored，也讓 retry_count 持續累積
        # 直到達到 ENTITLEMENT_RESETTLE_MAX_RETRY 轉 needs_manual 為止。
        # 注意「不重跑」只在本次呼叫內成立：旗標沒清掉，下一輪 sweep 仍會整個
        # resettle 重來（$inc 型有 marker 擋、訂閱型會重放 reset_monthly_usage 與
        # 期別重算），上限 ENTITLEMENT_RESETTLE_MAX_RETRY 輪——有界的已接受副作用。
        try:
            await self.order_repo.update_by_order_no(order_no, {
                "entitlement_pending": False,
                "entitlement_resettled_at": datetime.utcnow().timestamp(),
            })
        except Exception as exc:
            await self._handle_resettle_failure(order_no, exc)
            raise

        # 同 settle() 的開票白名單（見 `_INVOICE_TRIGGER_OUTCOMES`）：handler 沒拋例外
        # 不代表結果是「已啟用/已加值」——例如撞上 `_is_duplicate_first_completion`
        # 會回 REJECTED_DUPLICATE（標 needs_refund，不啟用/不加值），這種情況不該
        # 觸發開票。旗標一律清（handler 已跑完，不再是「crash 留下的坑」），開票才
        # 依 outcome 把關。
        if result.outcome.value in _INVOICE_TRIGGER_OUTCOMES:
            await self._trigger_invoice(order_no)
        log.info(
            "settle.entitlement_resettled",
            order_no=order_no, type=order_type, outcome=result.outcome.value,
        )

    async def _handle_resettle_failure(self, order_no: str, exc: Exception) -> None:
        """`resettle_entitlement` 失敗記帳：$inc 重試次數，達上限轉人工 + Sentry。

        比照 `_mark_entitlement_pending`：這個方法本身絕不可拋例外，否則會蓋掉呼叫端
        正在往外拋的原始例外。
        """
        try:
            retry_count = await self.order_repo.increment_entitlement_retry(order_no)
        except Exception as inc_err:
            log.error(
                "settle.resettle_entitlement.retry_inc_failed",
                order_no=order_no, error=str(inc_err), exc_info=True,
            )
            return
        log.error(
            "settle.resettle_entitlement.failed",
            order_no=order_no, retry_count=retry_count, error=str(exc), exc_info=True,
        )
        if retry_count < ENTITLEMENT_RESETTLE_MAX_RETRY:
            return
        try:
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
        except Exception as flag_err:
            log.error(
                "settle.resettle_entitlement.needs_manual_flag_failed",
                order_no=order_no, error=str(flag_err), exc_info=True,
            )
        self._capture_entitlement_manual_alert(order_no, retry_count, str(exc))

    @staticmethod
    def _capture_entitlement_manual_alert(order_no: str, retry_count: int, error: str) -> None:
        """重試耗盡轉人工 → 送 Sentry。lazy import：未裝 sentry_sdk 時靜默略過。

        抽成 helper（比照 `_capture_refund_alert`）讓測試 patch 這裡即可，不必
        monkeypatch 真的 sentry_sdk 模組——CI 環境沒裝 sentry_sdk，直接 import 會炸。
        """
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context(
                    "resettle_entitlement",
                    {"order_no": order_no, "retry_count": retry_count, "error": error},
                )
                sentry_sdk.capture_message("settle.entitlement_manual", level="error")
        except Exception:
            pass

    # ── 退款 / 爭議款處置（P1-5，金流體檢）──────────────────────────────────────
    #
    # 產品決策（已拍板）：全額退款(7) = 即時降級 free；部分退款(6) = 人工處理
    # （needs_manual + 告警，不自動動權益）；已開發票 = 自動作廢（失敗走既有
    # needs_manual 機制）。設計原則：所有自動動作 fail-safe——語意不明確就轉人工，
    # 寧可人工也不誤殺。

    async def handle_full_refund(self, order_no: str, *, trade_id: str = "") -> str:
        """全額退款（91APP recordStatus 7）：自動降級 free + 作廢發票。

        回傳 outcome 字串（供 log/測試）：
        - "order_not_found"：order 不存在。
        - "already_processed"：`claim_refund_processed` 沒搶到——`/callback` 與對帳
          sweep 重複觸發時，只有第一個贏得閘門的呼叫者會執行到這裡以下的分支。
          （M5，第二意見審查：這把閘門現在由 `handle_full_refund` 獨佔，
          `flag_partial_refund` 改用獨立的 `claim_marker`，兩者不再互相卡住。）
        - "duplicate_refund_resolved"：這張單當初被 `_reject_duplicate` 判定為
          『重複完成』（`is_duplicate`/`needs_refund`）——從未真正啟用過訂閱，退款
          只是營運照 SOP 把多扣的錢退回去，跟目前的訂閱狀態無關（H1，第二意見審查）。
        - "needs_manual"：order 非 paid、時效檢查未通過（使用者已重新付款）、
          `active_order_no` 與這張單不符（H1 第 2 層：不是目前訂閱狀態的權威來源）、
          降級的樂觀鎖 guard 沒中（H1 第 3 層：check-then-act 縫隙被併發改掉）、
          額度型退款從未真正發放過/金額缺失/餘額不足、或訂單型別未知——一律轉人工。
        - "revoked"：訂閱型退款通過所有 fail-safe 檢查，已呼叫 `_expire_to_free`
          降級（若該單帶有升級結轉的 extra_quota，會額外標 needs_manual，見 M4）。
        - "quota_deducted"：額度型（extra_quota）退款已原子扣回發放的額度。

        H2（第二意見審查）：claim 一旦搶到就會被消耗掉（`claim_refund_processed`
        是一次性的），若之後的處置動作中途拋例外，91APP 重送只會拿到
        "already_processed"、不會再有機會重跑——因此这段動作整個包在 try/except
        裡，例外時寫入耐久旗標 `refund_action_failed`（見 `_mark_refund_action_failed`）
        讓 admin needs_attention 撈得到，再原例外照樣往上拋。

        發票作廢只在「權益確定已經處置成功」（revoked / quota_deducted）才嘗試
        （L11：needs_manual 類分支留給人工，不搶著自動作廢），見
        `_void_issued_invoice_for_refund`。
        """
        order = await self.order_repo.get_by_order_no(order_no)
        if not order:
            log.warning("payment.refund.order_not_found", order_no=order_no)
            return "order_not_found"

        if not await self.order_repo.claim_refund_processed(order_no):
            log.info("payment.refund.already_processed", order_no=order_no, outcome="already_processed")
            return "already_processed"

        try:
            outcome = await self._dispatch_full_refund(order)
        except Exception as exc:
            await self._mark_refund_action_failed(order_no, exc)
            raise
        log.info("payment.refund.full_refund_processed", order_no=order_no, outcome=outcome)
        return outcome

    async def _dispatch_full_refund(self, order: dict) -> str:
        """claim 贏了之後的實際處置——整段被 `handle_full_refund` 包在 try/except 裡（H2）。"""
        order_no = order["merchant_order_no"]
        if order.get("status") != "paid":
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.on_unpaid_order", order_no=order_no, outcome="needs_manual")
            self._capture_refund_on_unpaid_order_alert(order_no)
            return "needs_manual"

        order_type = order.get("type", "subscription")
        if order_type in _SUBSCRIPTION_TYPES:
            outcome = await self._handle_full_refund_subscription(order)
        elif order_type == "extra_quota":
            outcome = await self._handle_full_refund_extra_quota(order)
        else:
            log.warning("payment.refund.unknown_order_type", order_no=order_no, type=order_type)
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            outcome = "needs_manual"

        # L11：只有「權益確定已經處置成功」的 outcome 才嘗試作廢發票——
        # needs_manual/duplicate_refund_resolved 都不搶著自動作廢，留給人工判斷
        # （duplicate_refund_resolved 這張單本來就從未啟用過，理論上也沒有發票）。
        if outcome in ("revoked", "quota_deducted"):
            await self._void_issued_invoice_for_refund(order_no)
        return outcome

    async def _mark_refund_action_failed(self, order_no: str, exc: Exception) -> None:
        """H2：claim 已消耗、後續動作中途失敗——寫耐久旗標讓 admin 撈得到。

        這個方法本身絕不可拋例外——否則會蓋掉呼叫端正在往外拋的原始例外（比照
        `_mark_entitlement_pending` 形狀）。
        """
        try:
            await self.order_repo.update_by_order_no(
                order_no, {"needs_manual": True, "refund_action_failed": True}
            )
        except Exception as flag_err:
            log.error(
                "payment.refund.action_failed_flag_write_failed",
                order_no=order_no, error=str(flag_err), exc_info=True,
            )
        log.error("payment.refund.action_failed", order_no=order_no, error=str(exc), exc_info=True)
        self._capture_refund_action_failed_alert(order_no, str(exc))

    async def _handle_full_refund_subscription(self, order: dict) -> str:
        """訂閱型（subscription/upgrade/downgrade/renewal）全額退款：層層 fail-safe
        檢查全過才降級（H1，第二意見審查）。"""
        order_no = order["merchant_order_no"]
        user_id = order["user_id"]

        if order.get("is_duplicate") or order.get("needs_refund"):
            # H1 場景：這張單當初被 _reject_duplicate 判定為『重複完成』（sibling
            # 已先啟動），從未真正啟用過訂閱/施加權益。它也是 paid+subscription 型，
            # 若不特判會被下面的邏輯誤判成「這是使用者目前的訂閱」而觸發降級——
            # 但使用者目前生效的其實是另一張 sibling 單，跟這張完全無關。
            log.info("payment.duplicate_refund_resolved", order_no=order_no)
            self._capture_duplicate_refund_resolved_alert(order_no)
            return "duplicate_refund_resolved"

        if await self.order_repo.has_newer_paid_subscription_order(user_id, order.get("paid_at")):
            # 使用者已重新付款（新單晚於這張退款單）——這裡特別涵蓋「續扣不更新
            # active_order_no」的情況：即使 active_order_no 仍指向這張單，只要
            # 使用者之後續扣成功過，訂閱其實已經被那筆續扣接手，自動降級會誤殺。
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.stale_order", order_no=order_no)
            self._capture_refund_stale_order_alert(order_no)
            return "needs_manual"

        user = await self.user_repo.get_by_id(user_id)
        sub = (user or {}).get("subscription") or {}
        if sub.get("active_order_no") != order_no:
            # H1 第 2 層——精確歸屬：active_order_no 是既有的權威欄位（見
            # _settle_subscription 的啟用/續扣分支），只有這張單「目前就是」使用者
            # 訂閱狀態的來源時，自動降級才安全。不符代表使用者的訂閱早就是別張單
            # （升降級換約、reactivate、或本例的『重複完成』sibling）在撐著。
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.order_not_active", order_no=order_no)
            self._capture_refund_order_not_active_alert(order_no)
            return "needs_manual"

        # H1 第 3 層：guard 把上面 check-then-act 的縫隙收成原子條件寫入——
        # active_order_no 若在讀取之後、寫入之前被併發改掉（例如另一張單剛好在這
        # 期間啟用），guard 不中，不能靜默當作『降級成功』。
        ok = await self._expire_to_free(user_id, guard={"subscription.active_order_no": order_no})
        if not ok:
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.guard_lost_race", order_no=order_no)
            self._capture_refund_guard_lost_alert(order_no)
            return "needs_manual"

        self._capture_refund_revoked_alert(order_no)
        log.warning("payment.refund.subscription_revoked", order_no=order_no)

        if order.get("carryover_granted") is True:
            # M4：升級換約時把舊方案剩餘額度結轉進 extra_quota（見 _settle_subscription
            # 的 upgrade_subscription 分支）。降級照做（訂閱本身的權益撤銷跟結轉額度
            # 是兩件事），但結轉出去的額度不自動扣回——使用者可能已經花掉部分，
            # `adjust_extra_quota_atomic` 的『不足就整筆放棄』policy 對這種混合用量
            # 場景太粗糙，交給人工核對實際剩餘量調整。
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.carryover_unreclaimed", order_no=order_no)
            self._capture_refund_carryover_unreclaimed_alert(order_no)

        # L8：不寄「已降級」通知信——既有的 "downgraded" 文案是續扣失敗語境
        # （「您的訂閱因付款失敗已降級」），套在退款情境會誤導使用者。退款情境的
        # 通知信文案待產品定稿，follow-up。

        return "revoked"

    async def _handle_full_refund_extra_quota(self, order: dict) -> str:
        """extra_quota（一次性加購）全額退款：原子扣回當初發放的額度（M4 fail-safe）。"""
        order_no = order["merchant_order_no"]
        user_id = order["user_id"]

        if order.get("quota_granted") is not True:
            # M4：quota_granted 是 claim_marker 在 _settle_extra_quota 真的成功施加
            # $inc 額度時才會寫 True 的一次性 marker——非 True 代表額度從未真正發放
            # 過（例如 entitlement_pending 中途 crash），這裡沒有東西可扣，硬扣會
            # 把使用者既有額度誤扣成負值。
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.quota_not_granted", order_no=order_no)
            self._capture_refund_quota_not_granted_alert(order_no, "not_granted")
            return "needs_manual"

        extra_dur = order.get("extra_duration_minutes", 0) or 0
        extra_ai = order.get("extra_ai_summaries", 0) or 0
        if not extra_dur and not extra_ai:
            # M4：quota_granted=True 但兩個金額欄位都缺/為 0 是矛盾狀態（理論上不會
            # 發生）——沒有東西可扣，不能回報「已扣回」，一律轉人工。
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.quota_amount_missing", order_no=order_no)
            self._capture_refund_quota_not_granted_alert(order_no, "amount_missing")
            return "needs_manual"

        # 不足以全扣時不部分扣——adjust_extra_quota_atomic 的原子條件（`$gte` 餘額）
        # 沒過就回 None，這裡一律轉人工，不做「能扣多少扣多少」的部分扣減（會留下
        # 金額對不上的帳，且更難事後稽核）。
        result = await self.user_repo.adjust_extra_quota_atomic(
            user_id, duration_minutes=-extra_dur, ai_summaries=-extra_ai,
        )
        if result is None:
            await self.order_repo.update_by_order_no(order_no, {"needs_manual": True})
            log.warning("payment.refund.quota_insufficient", order_no=order_no)
            self._capture_refund_quota_insufficient_alert(order_no)
            return "needs_manual"
        log.info("payment.refund.quota_deducted", order_no=order_no)
        return "quota_deducted"

    async def _void_issued_invoice_for_refund(self, order_no: str) -> None:
        """全額退款後嘗試作廢已開立發票（best-effort，絕不拋例外拖垮退款流程）。

        只對 status=="issued" 且有 invoice_number 的發票動作（同 admin 手動作廢端點
        的前置條件，見 routers/admin.py void_invoice 端點）——pending/failed/
        needs_manual/voided 的發票本來就不是「已開立給客戶」的終局狀態，沒有可作廢
        的對象，交給發票側既有機制（sweep/admin）處理。

        作廢失敗（SmilePay 拒絕或例外）不重試、不拋出——log.error + Sentry，讓
        `invoice_service` 既有的 needs_manual/reissue 機制接手人工介入。
        """
        try:
            from ..database.repositories.invoice_repo import InvoiceRepository  # lazy：避免無條件拉進 invoice 依賴
            from .invoice_service import void_invoice_for

            invoice = await InvoiceRepository(self.order_repo.db).get_active_by_order_no(order_no)
            if not invoice or invoice.get("status") != "issued" or not invoice.get("invoice_number"):
                return
            result = await void_invoice_for(self.order_repo.db, invoice, "退款自動作廢", "system:refund")
            if not result.get("success"):
                log.error(
                    "payment.refund.invoice_void_failed",
                    order_no=order_no, status_code=result.get("status_code"),
                )
                self._capture_refund_invoice_void_failed_alert(order_no, str(result.get("status_code")))
        except Exception as e:
            log.error("payment.refund.invoice_void_error", order_no=order_no, error=str(e), exc_info=True)
            self._capture_refund_invoice_void_failed_alert(order_no, "exception")

    async def flag_partial_refund(self, order_no: str, *, record_status: int) -> str:
        """部分退款（91APP recordStatus 6）：只標記人工處理，不動訂閱/額度/發票。

        產品決策：部分退款金額不確定對應多少權益，自動處置風險太高，一律轉人工。

        M5（第二意見審查）：冪等閘門改用獨立的 `claim_marker(order_no,
        "refund_partial_flagged")`，**不再**跟 `handle_full_refund` 共用
        `claim_refund_processed`。舊版共用會有這個 bug：部分退款(6) 先抵達時把
        `claim_refund_processed` 先佔走，之後真正的全額退款(7) callback 抵達時被
        誤判成 "already_processed"、完整跳過自動降級+發票作廢——`claim_refund_processed`
        現在由 `handle_full_refund` 獨佔，兩個閘門互不干擾，6 與 7 不論抵達順序都能
        各自完整執行。

        回傳 outcome 字串：order_not_found / already_processed / needs_manual。
        （`order_not_found` 檢查是防禦性補強——`claim_marker` 對不存在的 order 一樣
        會因為 `update_one` 沒匹配到文件而回 False，若不先檢查 order 是否存在，這種
        情況會被誤報成 "already_processed"，掩蓋「這筆單根本不存在」的異常。）
        """
        order = await self.order_repo.get_by_order_no(order_no)
        if not order:
            log.warning("payment.refund.order_not_found", order_no=order_no)
            return "order_not_found"

        if not await self.order_repo.claim_marker(order_no, "refund_partial_flagged"):
            log.info("payment.refund.already_processed", order_no=order_no, outcome="already_processed")
            return "already_processed"

        try:
            # 自行寫 refund_seen（天然停止對帳 sweep 重查）+ needs_manual，不透過
            # claim_refund_processed（那把鎖保留給 handle_full_refund 獨佔，見上）。
            await self.order_repo.update_by_order_no(order_no, {"refund_seen": True, "needs_manual": True})
            log.warning("payment.refund.partial_refund_needs_manual", order_no=order_no, record_status=record_status)
            self._capture_partial_refund_alert(order_no, record_status)
        except Exception as exc:
            # H2：跟 handle_full_refund 同款——claim_marker 已消耗，動作中途失敗
            # 不能靜默，寫耐久旗標 + re-raise。
            await self._mark_refund_action_failed(order_no, exc)
            raise
        return "needs_manual"

    @staticmethod
    def _capture_duplicate_refund_resolved_alert(order_no: str) -> None:
        """重複完成單的退款已由營運照 SOP 處理完畢 → Sentry info（純記錄，非異常，H1）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.duplicate_refund_resolved", level="info")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_order_not_active_alert(order_no: str) -> None:
        """退款單的 active_order_no 與使用者目前訂閱不符 → 轉人工告警（H1 第 2 層）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refund_order_not_active", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_guard_lost_alert(order_no: str) -> None:
        """降級寫入的樂觀鎖 guard 沒中（併發改掉 active_order_no）→ 轉人工告警（H1 第 3 層）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refund_guard_lost_race", level="error")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_action_failed_alert(order_no: str, error: str) -> None:
        """H2：claim 已消耗、後續動作中途失敗 → Sentry error（耐久旗標見
        `refund_action_failed`，admin needs_attention 撈得到；這裡是即時通知）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no, "error": error})
                sentry_sdk.capture_message("payment.refund_action_failed", level="error")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_carryover_unreclaimed_alert(order_no: str) -> None:
        """升級結轉的 extra_quota 未自動回收 → 轉人工告警（M4）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refund_carryover_unreclaimed", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_quota_not_granted_alert(order_no: str, reason: str) -> None:
        """extra_quota 退款沒有東西可扣（額度從未發放/金額缺失）→ 轉人工告警（M4）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no, "reason": reason})
                sentry_sdk.capture_message("payment.refund_quota_not_granted", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_on_unpaid_order_alert(order_no: str) -> None:
        """未付款單收到全額退款通知（異常）→ Sentry。lazy import：未裝 sentry_sdk 時靜默略過。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refund_on_unpaid_order", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_stale_order_alert(order_no: str) -> None:
        """退款對應舊期別、使用者已重新付款 → 轉人工 Sentry 告警。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refund_stale_order", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_revoked_alert(order_no: str) -> None:
        """全額退款已自動降級 free → Sentry（level=warning：權威事件，值得留意但非錯誤）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refunded_subscription_revoked", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_quota_insufficient_alert(order_no: str) -> None:
        """額度型退款餘額不足以扣回 → 轉人工 Sentry 告警。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no})
                sentry_sdk.capture_message("payment.refund_quota_insufficient", level="warning")
        except Exception:
            pass

    @staticmethod
    def _capture_refund_invoice_void_failed_alert(order_no: str, detail: str) -> None:
        """退款後發票自動作廢失敗 → Sentry（level=error：需要人工介入手動作廢）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no, "detail": detail})
                sentry_sdk.capture_message("payment.refund_invoice_void_failed", level="error")
        except Exception:
            pass

    @staticmethod
    def _capture_partial_refund_alert(order_no: str, record_status: int) -> None:
        """部分退款轉人工 → Sentry（level=warning）。"""
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("order_no", order_no)
                scope.set_context("refund", {"order_no": order_no, "record_status": record_status})
                sentry_sdk.capture_message("payment.partial_refund_needs_manual", level="warning")
        except Exception:
            pass

    # ── 訂閱（subscription / upgrade / downgrade）─────────────────────────────

    async def _settle_subscription(self, order: dict, n: PaymentNotification) -> SettleResult:
        now = datetime.utcnow()
        user_id = order["user_id"]
        tier = order["tier"]
        billing_cycle = order["billing_cycle"]
        order_type = order.get("type", "subscription")
        period_end = calc_period_end(billing_cycle, now)

        if not n.is_first_payment:
            # 續扣成功：order paid（+ trade_id）已由 settle() 的 claim_paid 權威寫入
            # （見上方閘門）。這裡只需展期 + 歸零當期用量 + 清 dunning（past_due→active）。
            full_user = await self.user_repo.get_by_id(user_id)
            sub = full_user.get("subscription", {}) if full_user else {}
            # 方案變更（期末降級 pending_plan_change 生效）：續扣單帶的是「目標 tier」。
            #   以 tier 判定（quota 由 tier 決定，與 billing_cycle 無關）。
            plan_changed = sub.get("tier") != tier
            fields = {
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
            }
            # 換卡挽回：recovery order 帶新 card_token → 更新綁定
            new_token = order.get("card_token")
            if new_token:
                fields["card_token"] = new_token
            # P0-2(b)：dotted $set 只寫這些欄位，guard=None——續扣成功是權威寫入方，
            # 一定要贏（不像 dunning 降級面對續扣要退讓，見 _apply_updates/_expire_to_free）。
            await self.user_repo.update_subscription_fields(user_id, fields, guard=None)
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
        # P1-9：claim_marker 先搶後施——重跑安全化（見 order_repo.claim_marker docstring）。
        if order_type == "upgrade_subscription":
            extra_dur = order.get("extra_duration_minutes", 0)
            extra_ai = order.get("extra_ai_summaries", 0)
            if extra_dur or extra_ai:
                if await self.order_repo.claim_marker(order["merchant_order_no"], "carryover_granted"):
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
        # order paid（+ trade_id）已由 settle() 的 claim_paid 權威寫入（見上方閘門）。
        log.info("subscription.activated", user_id=user_id, tier=tier, billing_cycle=billing_cycle, type=order_type)
        # 降級生效後（quota 已 commit）：釋放超過新方案額度的釘選音檔，進寬限期。
        #   best-effort（reconcile 自行吞例外），不影響已成功的訂閱啟用。
        if order_type == "downgrade_subscription":
            await self._reconcile_pinned_audio(user_id, tier)
        return SettleResult(SettleOutcome.ACTIVATED, n.order_no)

    # ── 額外額度（一次性加購）────────────────────────────────────────────────

    async def _settle_extra_quota(self, order: dict, n: PaymentNotification) -> SettleResult:
        """order paid（+ trade_id）已由 settle() 的 claim_paid 權威寫入（見上方閘門）。

        P1-9：claim_marker 先搶後施——重跑安全化（見 order_repo.claim_marker docstring）。
        """
        user_id = order["user_id"]
        extra_dur = order.get("extra_duration_minutes", 0)
        extra_ai = order.get("extra_ai_summaries", 0)
        if await self.order_repo.claim_marker(order["merchant_order_no"], "quota_granted"):
            await self.user_repo.add_extra_quota(user_id, extra_dur, extra_ai)
        log.info(
            "payment.extra_quota.purchased",
            user_id=user_id, extra_duration_minutes=extra_dur, extra_ai_summaries=extra_ai,
        )
        return SettleResult(SettleOutcome.GRANTED, n.order_no)

    # ── 內部 effect helpers ─────────────────────────────────────────────────

    async def _expire_to_free(self, user_id: str, guard: Optional[dict] = None) -> bool:
        """續扣失敗：訂閱標 expired、quota 降為 free。

        P0-2(b)：guard 有值時走樂觀併發（呼叫端帶著 dunning sweep 手上的訂閱快照，
        guard 通常是 `{"subscription.next_charge_at": snapshot_value}`）——若併發的
        續扣已經成功、把 next_charge_at 推進了，guard 不符代表這份「該降級」的判斷已經
        過期，訂閱其實已經被救回，直接放棄（return False，不執行 update_quota / 釘選
        reconcile：訂閱沒真的動就不能動配額）。guard=None（例如舊呼叫端未提供快照）
        則一律寫入，行為等同舊版。
        """
        ok = await self.user_repo.update_subscription_fields(
            user_id,
            {
                "status": "expired",
                "cancel_at_period_end": False,
                "updated_at": datetime.utcnow().timestamp(),
            },
            guard=guard,
        )
        if not ok:
            log.warning("subscription.expire_to_free.guard_failed", user_id=user_id)
            return False
        await self.user_repo.update_quota(user_id, build_quota_from_tier("free"))
        log.warning("subscription.renewal.payment_failed", user_id=user_id)
        # 降為 free（quota 已 commit）：free 不能保留音檔 → 釋放全部釘選進寬限期。
        await self._reconcile_pinned_audio(user_id, "free")
        return True

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
        91APP 無 gateway 委託可終止，這裡不再有終止動作。order 的 status/paid_at 已由
        settle() 的 claim_paid 權威寫入（見上方閘門），這裡只補寫重複完成專屬的旗標。

        F9（第二意見審查）：Sentry 告警排在 DB 寫入**之前**——若中間被 SIGTERM，至少
        Sentry 留下記錄，不會留下一張「已重複扣款但無旗標、無告警」的單（DB 寫入本身
        是 idempotent 的 $set，重跑一次無害；但告警只有第一次呼叫才有意義，寧可早發）。
        """
        ono = order["merchant_order_no"]
        self._capture_refund_alert(user_id, ono, "重複完成已拒絕，需退首期款")
        await self.order_repo.update_by_order_no(ono, {
            "is_duplicate": True,
            "needs_refund": True,
        })
        log.warning(
            "subscription.duplicate_completion.rejected",
            user_id=user_id, order_no=ono,
        )

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


def build_order_settlement(
    db, *, invoice_issuer: Optional[Callable[[Any, dict], Awaitable[None]]] = None
) -> OrderSettlement:
    """以 request-scoped db 組出 OrderSettlement（repos 從 db 建；不再依賴金流 provider）。

    invoice_issuer：測試注入用（見 tests/services/test_order_settlement.py 的開票 hook 測試）；
    省略時預設走真正的 invoice_service.issue_for_order，既有呼叫點（renewal_service 等）
    不需改動即自動套用。
    """
    return OrderSettlement(
        order_repo=OrderRepository(db),
        user_repo=UserRepository(db),
        invoice_issuer=invoice_issuer,
    )
