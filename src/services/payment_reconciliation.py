"""對帳補償 sweep（金流體檢 P1-9）。

背景：`/callback` 的 `query_trade` 逾時 → raise 500 → 91APP 依規格不重送 → 該筆單
在 T+1h 被 `order_cleanup` 標成 expired——使用者已扣款、卻無訂閱、無發票、無告警，
且完全靜默（沒有任何一條既有告警路徑會浮現這個狀態）。ASSESSMENT §6.1 早就記載
「callback 不可依賴重送，需自建定時掃 pending 主動回查」，但直到這個 PR 之前未實作。

本檔案兩段式運作（`periodic_payment_reconciliation` 每輪都跑）：
1. `run_reconciliation_sweep`：掃「已進入付款（有 trade_id）但仍 pending/expired」的
   單，主動回查 91APP `query_trade`，依回查結果收斂（成功/失敗）或暫緩（pending/
   退款）或放棄（72h 仍懸而不決 → 轉人工）。收斂靠 `OrderSettlement.settle()`——
   settle 本身是冪等閘門（`claim_paid` + ALREADY_PAID 短路），與併發抵達的真
   callback 撞期也安全，不會雙重結算。
2. `run_entitlement_resettle_sweep`：掃 `entitlement_pending`（PR#324 引入的「已
   paid 但 settle handler crash 導致權益可能未施加完整」旗標）的單，呼叫
   `OrderSettlement.resettle_entitlement` 補施權益。這個旗標在本 PR 之前零消費者
   ——沒有它，crash 留下的單只能等 admin 主動翻 log 才會發現。

`_http_status != 200` 或缺 `recordStatus`（91APP 非 200 回應 body 常缺欄位）一律歸
`unresolved`，**不得**丟給 `interpret_record_status`（它對缺欄位/非法值 fail-closed
回 "failed"，會把「查詢本身失敗」誤判成「付款失敗」而錯發失敗通知）——這是探勘
出的地雷，見 tests/services/test_payment_reconciliation.py 的回歸測試。

第二意見審查（P1-C/P1-D/P2-F）追加三條：
- recordStatus 6/7（退款）改寫 `refund_seen` 旗標 + Sentry 一次，並從查詢層排除
  ——不再每輪重查已經認出的退款單（見 `_capture_refund_seen_alert` 的語意分歧說明）。
- 72 小時放棄時鐘改用 `reconciliation_first_seen_at`（sweep 首次遭遇該單才 stamp）
  而非 `created_at`，避免上線當下 backfill 一批歷史舊單被第一輪就判定放棄+告警
  風暴。
- `query_trade` 對格式不符的 `trade_id` 直接 `raise ValueError`（發生在所有分支
  判讀之前）——這是永久性髒資料，不是暫時性故障，`run_reconciliation_sweep` 的
  per-item 例外處理特別區分 `ValueError`，直接判定放棄轉人工，不留給下一輪的
  `errored` 計數繼續佔位置重試。
"""
import asyncio
from typing import Any, Dict, Optional

from ..database.repositories.job_lease_repo import JobLeaseRepository
from ..database.repositories.order_repo import OrderRepository
from ..utils.payments91_service import get_payments91_service
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger
from .order_settlement import build_order_settlement, ENTITLEMENT_RESETTLE_MAX_RETRY, PaymentNotification

log = get_logger(__name__)

# age gate：避免跟進行中的 3D 導頁流程賽跑（使用者可能還在銀行頁面，此時單子必然
# 還是 pending，主動回查只是浪費一次 API 呼叫、也可能撞見尚未定案的中繼狀態）。
RECONCILE_AGE_GATE_SECONDS = 15 * 60

# 72 小時仍懸而不決（unresolved / still_pending）→ 本地放棄主動回查，狀態交給
# admin 人工（該筆單可能仍在 91APP 側演進，不代表真的失敗，不改 status）。時鐘起點
# 見 `_maybe_give_up`：用 `reconciliation_first_seen_at`（sweep 首次遭遇），不是
# `created_at`（P1-D，第二意見審查）。
RECONCILE_GIVE_UP_SECONDS = 72 * 3600

# recordStatus enum（見 payments91_service.py 權威註解）：
#   1 待付款 / 8 付款處理中 → pending；4 付款成功 / 5 請款成功 → success；
#   2 付款失敗 / 3 付款取消 → failed；6 部分退款 / 7 全部退款 → refund（P1-5 範圍）。
_RECORD_SUCCESS = {4, 5}
_RECORD_PENDING = {1, 8}
_RECORD_FAILED = {2, 3}
_RECORD_REFUND = {6, 7}


def _find(obj: Any, key_lower: str) -> Any:
    """遞迴找第一個名稱等於 key_lower（小寫比較）的值。

    複製自 routers/subscriptions.py 的同名 helper——三層架構下 services 不應該
    反向 import routers，寧可重複這個純函式也不要越層依賴。
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == key_lower and v not in (None, ""):
                return v
            found = _find(v, key_lower)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find(item, key_lower)
            if found not in (None, ""):
                return found
    return None


# ── 背景排程 ────────────────────────────────────────────────────────────────

async def periodic_payment_reconciliation(db, interval_seconds: int = 600) -> None:
    """啟動嘗試搶當前時間窗執行權，搶到才立即跑一次；搶不到等下一輪。之後每 interval
    掃描。受 main.py 的 RUN_BACKGROUND_JOBS 保護（形狀照 renewal_service.py）。

    prod 兩個 uvicorn worker 都會跑這個背景任務，用 JobLeaseRepository 對本輪時間窗
    搶執行權，避免同一輪對帳/補償被跑兩次。lease 檢查本身失敗（DB 例外）採
    fail-open：照跑本輪並記警告——sweep 本身靠 settle() 的 claim_paid 冪等，寧可
    偶發重跑也不要對帳補償全停（那正是本 PR 要修的漏洞本質）。
    """
    lease_repo = JobLeaseRepository(db)
    while True:
        should_run = True
        try:
            should_run = await lease_repo.claim_window("payment_reconciliation", interval_seconds)
        except Exception as e:
            log.warning("payment.reconciliation.lease_check_failed", error=str(e))
        if should_run:
            try:
                await run_reconciliation_sweep(db)
            except Exception as e:
                log.error("payment.reconciliation.sweep_failed", error=str(e), exc_info=True)
            try:
                await run_entitlement_resettle_sweep(db)
            except Exception as e:
                log.error("payment.entitlement_resettle.sweep_failed", error=str(e), exc_info=True)
        await asyncio.sleep(interval_seconds)


# ── 第一段：主動回查收斂 pending/expired 單 ──────────────────────────────────

async def run_reconciliation_sweep(db) -> Dict[str, int]:
    """一輪對帳：掃有 trade_id 但仍 pending/expired 的單，主動回查 91APP 收斂。

    回傳計數（測試用）：resolved_success 再依 settle outcome 細分
    activated/renewed/already_paid；resolved_failed／still_pending／unresolved／
    refund_seen／gave_up／errored。
    """
    order_repo = OrderRepository(db)
    svc = get_payments91_service()
    settlement = build_order_settlement(db)
    counts = {
        "resolved_success": 0, "activated": 0, "renewed": 0, "already_paid": 0,
        "resolved_failed": 0, "still_pending": 0, "unresolved": 0,
        "refund_seen": 0, "gave_up": 0, "errored": 0,
    }

    # ★物化成 list（同 invoice_service.run_invoice_retry_sweep 的理由）：迴圈體對每筆
    # 都可能觸發 91APP query_trade（httpx，最長 30s），沿用 async for 直接吃 motor
    # cursor 會在長時間掛在迴圈中時撞 Mongo cursor idle timeout。
    orders = [o async for o in order_repo.iter_for_reconciliation(RECONCILE_AGE_GATE_SECONDS)]

    for order in orders:
        order_no = order.get("merchant_order_no", "")
        try:
            await _reconcile_one(order_repo, svc, settlement, order, counts)
        except Exception as e:
            # 單筆炸掉不可讓整輪 sweep 停擺（P1-7 同款隔離）。poison trade_id 的
            # ValueError 已在 _reconcile_one 內、緊貼 query_trade 呼叫處處理（P2-F），
            # 不會漏到這裡——settle 路徑若拋 ValueError 屬真異常，照 errored 計。
            counts["errored"] += 1
            log.error("payment.reconciliation.item_failed", order_no=order_no, error=str(e), exc_info=True)

    if any(counts.values()):
        log.info("payment.reconciliation.completed", **counts)
    return counts


async def _reconcile_one(
    order_repo: OrderRepository, svc, settlement, order: Dict[str, Any], counts: Dict[str, int],
) -> None:
    order_no = order["merchant_order_no"]
    trade_id = order.get("trade_id") or ""

    # P1-D（第二意見審查）：72h 放棄時鐘的起點改成「sweep 第一次遭遇這筆單」，不是
    # `created_at`——只在欄位不存在時才真的落庫，往後每輪都讀到同一個值。放在
    # query_trade（可能 raise ValueError/其他例外）之前，確保即使這筆單從第一次
    # 就查詢失敗，時鐘依然從「第一次被掃到」起算，不會因為一直失敗而永遠不 stamp。
    now_ts = get_utc_timestamp()
    first_seen = order.get("reconciliation_first_seen_at")
    if first_seen is None:
        first_seen = now_ts
        await order_repo.stamp_reconciliation_first_seen(order_no, now_ts)
    # 輪替 stamp：iter_for_reconciliation 依 last_reconciled_at 升冪撈單，處理前先
    # stamp 讓這筆排到隊尾——積壓超過 batch 上限時每輪處理的是「最久沒查過」的 50 筆，
    # unresolved 單不會永久霸佔批次頭部（第二意見審查的飢餓觀察）。
    await order_repo.update_by_order_no(order_no, {"last_reconciled_at": now_ts})

    try:
        resp = await svc.query_trade(trade_id)
    except ValueError as e:
        # P2-F（第二意見審查）：query_trade 對格式不符的 trade_id 直接 raise
        # ValueError——這是永久性髒資料（trade_id 存進 order 當下就壞了），不是
        # 暫時性故障，重試不會有不同結果。不歸類 unresolved（那類會一直重試），
        # 直接判定放棄轉人工。try 只包 query_trade 這一行：settle 路徑的 ValueError
        # 屬真異常，該由外層 per-item 隔離計 errored，不能被誤收進 gave_up。
        log.error("payment.reconciliation.poison_trade_id", order_no=order_no, error=str(e))
        await order_repo.update_by_order_no(order_no, {"reconciliation_gave_up": True})
        _capture_gave_up_alert(order_no)
        counts["gave_up"] += 1
        return

    # 🔴 地雷 gate：_parse 對非 200 不拋錯（只回 body + _http_status），91APP 非 200
    # body 常缺 recordStatus——若直接丟給 interpret_record_status，缺欄位 fail-closed
    # 回 "failed"，會把「這次查詢本身失敗」誤判成「付款失敗」進而誤發失敗通知，
    # 把一筆其實還在演進中（或只是暫時查不到）的單錯殺。必須先擋在這裡。
    http_status = resp.get("_http_status")
    record_status = _find(resp, "recordstatus")
    if http_status != 200 or record_status is None:
        log.warning(
            "payment.reconciliation.unresolved",
            order_no=order_no, trade_id=trade_id, http_status=http_status,
        )
        counts["unresolved"] += 1
        await _maybe_give_up(order_repo, order, counts, first_seen)
        return

    try:
        rs = int(record_status)
    except (TypeError, ValueError):
        log.warning(
            "payment.reconciliation.unresolved",
            order_no=order_no, trade_id=trade_id, http_status=http_status,
        )
        counts["unresolved"] += 1
        await _maybe_give_up(order_repo, order, counts, first_seen)
        return

    if rs in _RECORD_PENDING:
        counts["still_pending"] += 1
        await _maybe_give_up(order_repo, order, counts, first_seen)
        return

    if rs in _RECORD_REFUND:
        # P1-C（第二意見審查）：改寫 refund_seen 旗標 + 告警一次，並讓
        # iter_for_reconciliation 的查詢層排除它——不再是「刻意不動、每輪重查」的
        # 殭屍單，而是明確的終局狀態，停住待 P1-5 統一處理「退款是否該撤銷訂閱」。
        await order_repo.update_by_order_no(order_no, {"refund_seen": True})
        log.warning(
            "payment.reconciliation.refund_seen",
            order_no=order_no, trade_id=trade_id, record_status=rs,
        )
        _capture_refund_seen_alert(order_no, rs)
        counts["refund_seen"] += 1
        return

    is_first_payment = order.get("type") != "renewal"

    if rs in _RECORD_SUCCESS:
        result = await settlement.settle(PaymentNotification(
            order_no=order_no, success=True, is_first_payment=is_first_payment, trade_id=trade_id,
        ))
        log.info(
            "payment.reconciliation.resolved",
            order_no=order_no, trade_id=trade_id, record_status=rs, outcome=result.outcome.value,
        )
        # 每一筆對帳收斂都代表 callback 鏈路掉了一封，要看得到——即使 outcome 是
        # ALREADY_PAID（代表真 callback 剛好也到了，對帳只是白跑一趟）也值得一提，
        # 用 level=warning 而非 error：這不是本次 sweep 的錯誤，是既有漏洞的證據。
        _capture_reconciled_alert(order_no, result.outcome.value)
        counts["resolved_success"] += 1
        outcome_key = {"activated": "activated", "renewed": "renewed", "already_paid": "already_paid"}.get(
            result.outcome.value
        )
        if outcome_key:
            counts[outcome_key] += 1
        return

    if rs in _RECORD_FAILED:
        await settlement.settle(PaymentNotification(
            order_no=order_no, success=False, is_first_payment=is_first_payment, trade_id=trade_id,
        ))
        counts["resolved_failed"] += 1
        return

    # 理論上窮舉了 91APP 文件的 recordStatus enum，落到這裡代表未知數值——保守當
    # unresolved，不擅自判定成敗。
    log.warning(
        "payment.reconciliation.unresolved",
        order_no=order_no, trade_id=trade_id, http_status=http_status, record_status=rs,
    )
    counts["unresolved"] += 1
    await _maybe_give_up(order_repo, order, counts, first_seen)


async def _maybe_give_up(
    order_repo: OrderRepository, order: Dict[str, Any], counts: Dict[str, int], first_seen: float,
) -> None:
    """72 小時仍 unresolved/still_pending → 本地放棄，標旗標 + 告警，不再重查。

    `first_seen`（`reconciliation_first_seen_at`，見 `_reconcile_one`）而非
    `created_at`——避免上線當下 backfill 到一批已經建立超過 72 小時的歷史 pending
    單，第一輪掃描就把它們全部判定放棄、觸發告警風暴（P1-D，第二意見審查）。

    不改 order.status：單可能仍在 91APP 側演進，狀態交給 admin 人工判斷，不能由
    sweep 自作主張標 expired（那正是原本漏洞的另一種變形）。
    """
    if first_seen > get_utc_timestamp() - RECONCILE_GIVE_UP_SECONDS:
        return
    order_no = order["merchant_order_no"]
    await order_repo.update_by_order_no(order_no, {"reconciliation_gave_up": True})
    log.error("payment.reconciliation.gave_up", order_no=order_no, trade_id=order.get("trade_id"))
    _capture_gave_up_alert(order_no)
    counts["gave_up"] += 1


def _capture_reconciled_alert(order_no: str, outcome: str) -> None:
    """對帳成功收斂一筆 → Sentry（level=warning：代表 callback 鏈路確實掉過一封）。"""
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("order_no", order_no)
            scope.set_context("payment_reconciliation", {"order_no": order_no, "outcome": outcome})
            sentry_sdk.capture_message("payment.reconciled", level="warning")
    except Exception:
        pass


def _capture_gave_up_alert(order_no: str) -> None:
    """72h 對帳仍懸而不決、本地放棄 → Sentry（level=error：需要人工介入）。"""
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("order_no", order_no)
            scope.set_context("payment_reconciliation", {"order_no": order_no})
            sentry_sdk.capture_message("payment.reconciliation_gave_up", level="error")
    except Exception:
        pass


def _capture_refund_seen_alert(order_no: str, record_status: int) -> None:
    """認出退款/爭議款（recordStatus 6/7）→ Sentry（level=warning）。

    語意刻意與 `/callback` 分歧（P1-C，第二意見審查）：`/callback` 路徑的
    `interpret_record_status` 把 6/7 一併歸類成 "failed"（webhook 即時判讀語意，見
    payments91_service.py 權威註解），但 sweep 面對的單狀態不明（可能已經被
    `/callback` 或另一輪 sweep 結算成 paid）——若也走 `settle(success=False)`，
    `mark_failed_unless_paid` 的 `$ne paid` 條件雖然安全（不會誤蓋已 paid 的單），
    但語意上「已收款後又退款」跟「這筆從未收款過」是兩件事，混在 failed 分支的
    日誌/計數裡會誤導事後排查。這裡改成獨立的 refund_seen 旗標，停住待人工，統一
    交給 P1-5 處理「退款是否該撤銷訂閱」的產品決策。
    """
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("order_no", order_no)
            scope.set_context(
                "payment_reconciliation", {"order_no": order_no, "record_status": record_status}
            )
            sentry_sdk.capture_message("payment.refund_seen", level="warning")
    except Exception:
        pass


# ── 第二段：補結算 entitlement_pending ───────────────────────────────────────

async def run_entitlement_resettle_sweep(db) -> Dict[str, int]:
    """一輪補償：掃 entitlement_pending 且未達重試上限的單，呼叫 resettle_entitlement。

    每筆 per-item try/except——poison item（例如訂閱資料本身損毀）不可癱瘓整輪，
    OrderSettlement.resettle_entitlement 自己會 $inc 重試次數並在失敗時 re-raise，
    這裡接住例外計 errored，不重複處理重試/needs_manual 的記帳（那是
    resettle_entitlement 的職責）。
    """
    order_repo = OrderRepository(db)
    settlement = build_order_settlement(db)
    counts = {"resettled": 0, "errored": 0}

    orders = [o async for o in order_repo.iter_entitlement_pending(ENTITLEMENT_RESETTLE_MAX_RETRY)]

    for order in orders:
        order_no = order.get("merchant_order_no", "")
        try:
            await settlement.resettle_entitlement(order)
            counts["resettled"] += 1
        except Exception as e:
            counts["errored"] += 1
            log.error("payment.entitlement_resettle.item_failed", order_no=order_no, error=str(e), exc_info=True)

    if any(counts.values()):
        log.info("payment.entitlement_resettle.completed", **counts)
    return counts
