"""對帳補償 sweep（金流體檢 P1-9）。

背景：`/callback` 的 `query_trade` 逾時 → raise 500 → 91APP 依規格不重送 → 該筆單
在 T+1h 被 `order_cleanup` 標成 expired——使用者已扣款、卻無訂閱、無發票、無告警，
且完全靜默（沒有任何一條既有告警路徑會浮現這個狀態）。ASSESSMENT §6.1 早就記載
「callback 不可依賴重送，需自建定時掃 pending 主動回查」，但直到這個 PR 之前未實作。

本檔案三段式運作（`periodic_payment_reconciliation` 每輪都跑前兩段；第三段用獨立
window lease，一天最多一輪）：
1. `run_reconciliation_sweep`：掃「已進入付款（有 trade_id）但仍 pending/expired」的
   單，主動回查 91APP `query_trade`，依回查結果收斂（成功/失敗/退款）或暫緩
   （pending）或放棄（72h 仍懸而不決 → 轉人工）。成功/失敗收斂靠
   `OrderSettlement.settle()`——settle 本身是冪等閘門（`claim_paid` +
   ALREADY_PAID 短路），與併發抵達的真 callback 撞期也安全，不會雙重結算。退款
   （P1-5，已實作）收斂靠 `OrderSettlement.handle_full_refund`（全額，7）/
   `flag_partial_refund`（部分，6）——兩者的冪等閘門分別是 `claim_refund_processed`
   （全額，與 `/callback` 側共用同一張 order）/`claim_marker(..., "refund_partial_flagged")`
   （部分，M5 第二意見審查：改用獨立閘門，避免 6 先到卡住 7 的重入防線），兩條路徑
   撞期一樣安全。
2. `run_entitlement_resettle_sweep`：掃 `entitlement_pending`（PR#324 引入的「已
   paid 但 settle handler crash 導致權益可能未施加完整」旗標）的單，呼叫
   `OrderSettlement.resettle_entitlement` 補施權益。這個旗標在本 PR 之前零消費者
   ——沒有它，crash 留下的單只能等 admin 主動翻 log 才會發現。
3. `run_refund_audit_sweep`（M3，第二意見審查）：`/callback` 是「已 paid 訂單」收到
   退款通知的**唯一**即時路徑——`run_reconciliation_sweep` 的查詢範圍限定
   `status in (pending, expired)`，對已經 paid 的單結構性不可達。若 91APP 真的沒打
   `/callback`（或打到但處理失敗且沒被重送），一張已 paid 的訂閱/加購單被使用者
   事後對發卡行申訴退款，系統完全沒有第二條路能發現——這支 sweep 是唯一 fallback：
   每天掃一輪「30 天內 paid、還沒被退款流程認領過」的單，主動回查 91APP 有沒有
   recordStatus 6/7，有就分流到跟 `/callback` 完全同一套 `handle_full_refund`/
   `flag_partial_refund`。

`_http_status != 200` 或缺 `recordStatus`（91APP 非 200 回應 body 常缺欄位）一律歸
`unresolved`，**不得**丟給 `interpret_record_status`（它對缺欄位/非法值 fail-closed
回 "failed"，會把「查詢本身失敗」誤判成「付款失敗」而錯發失敗通知）——這是探勘
出的地雷，見 tests/services/test_payment_reconciliation.py 的回歸測試。

第二意見審查（P1-C/P1-D/P2-F）追加三條（P1-C 已被 P1-5 取代，見下）：
- recordStatus 6/7（退款）分流呼叫 `OrderSettlement.handle_full_refund`（7）/
  `flag_partial_refund`（6）——兩者都會寫 `refund_seen: True`（前者是
  `claim_refund_processed` 的一部分，後者是 `flag_partial_refund` 自己
  `update_by_order_no` 寫的，見 M5），`iter_for_reconciliation` 的查詢層排除條件
  （`refund_seen: {"$ne": True}`）因此天然停止重查，不需要另外改查詢。P1-5 之前
  這裡只是改寫 `refund_seen` 旗標停住待人工（見已刪除的 `_capture_refund_seen_alert`），
  現在是真正的終局處置。
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

# M3（第二意見審查）：退款稽核 lane 用獨立的 window lease，一天最多一輪——若跟主
# 對帳迴圈共用同一把鎖（interval_seconds 預設 600 秒），200 筆 query_trade 的稽核
# 量級會被排擠到幾乎搶不到執行權；獨立鎖讓它照自己的節奏走，不受主迴圈 interval
# 影響，也不會每 10 分鐘就對 91APP 打一輪 200 筆的查詢。
REFUND_AUDIT_LEASE_WINDOW_SECONDS = 24 * 3600

# recordStatus enum（見 payments91_service.py 權威註解）：
#   1 待付款 / 8 付款處理中 → pending；4 付款成功 / 5 請款成功 → success；
#   2 付款失敗 / 3 付款取消 → failed；6 部分退款 / 7 全部退款 → refund（P1-5 已實作）。
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

        # M3：獨立 window lease（見 REFUND_AUDIT_LEASE_WINDOW_SECONDS 常數說明），
        # 跟上面兩段的 lease 完全分開判定——即使上面搶輸了（should_run=False），
        # 這段仍照自己的一天一輪節奏獨立判斷。
        should_run_refund_audit = True
        try:
            should_run_refund_audit = await lease_repo.claim_window(
                "refund_audit", REFUND_AUDIT_LEASE_WINDOW_SECONDS
            )
        except Exception as e:
            log.warning("payment.refund_audit.lease_check_failed", error=str(e))
        if should_run_refund_audit:
            try:
                await run_refund_audit_sweep(db)
            except Exception as e:
                log.error("payment.refund_audit.sweep_failed", error=str(e), exc_info=True)

        await asyncio.sleep(interval_seconds)


# ── 第一段：主動回查收斂 pending/expired 單 ──────────────────────────────────

async def run_reconciliation_sweep(db) -> Dict[str, int]:
    """一輪對帳：掃有 trade_id 但仍 pending/expired 的單，主動回查 91APP 收斂。

    回傳計數（測試用）：resolved_success 再依 settle outcome 細分
    activated/renewed/already_paid；resolved_failed／still_pending／unresolved／
    refund_full／refund_partial（L7，第二意見審查：舊版 refund_seen 已拆分成這兩個
    更精確的鍵）／gave_up／errored。
    """
    order_repo = OrderRepository(db)
    svc = get_payments91_service()
    settlement = build_order_settlement(db)
    counts = {
        "resolved_success": 0, "activated": 0, "renewed": 0, "already_paid": 0,
        "resolved_failed": 0, "still_pending": 0, "unresolved": 0,
        "refund_full": 0, "refund_partial": 0, "gave_up": 0, "errored": 0,
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
        # P1-5：對帳側掉的退款 callback（`/callback` query_trade 逾時、或這筆單根本
        # 不曾有 pending 以外的 callback 抵達）主動回查認出退款後，分流到跟
        # `/callback` 側的 `_process_refund` 完全同一套處置——settlement 方法本身的
        # `claim_refund_processed` 冪等閘門確保兩條路徑撞期也不會重複降級/重複告警。
        if rs == 7:
            outcome = await settlement.handle_full_refund(order_no, trade_id=trade_id)
            counts["refund_full"] += 1
        else:
            outcome = await settlement.flag_partial_refund(order_no, record_status=rs)
            counts["refund_partial"] += 1
        log.info(
            "payment.reconciliation.refund_resolved",
            order_no=order_no, trade_id=trade_id, record_status=rs, outcome=outcome,
        )
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


# ── 第三段（M3，第二意見審查）：paid 單退款稽核 ───────────────────────────────

async def run_refund_audit_sweep(db) -> Dict[str, int]:
    """一輪稽核：掃 30 天內 paid、還沒被退款流程認領過的訂閱型/extra_quota 單，
    主動回查 91APP 有沒有 recordStatus 6/7——`/callback` 是這類單收到退款通知的
    唯一即時路徑，這是唯一 fallback（見本檔案模組 docstring）。

    判讀 gate（`_http_status==200` 且 `recordStatus` 存在才算「查得到結果」）與
    per-item try/except 隔離比照 `run_reconciliation_sweep`：單筆炸掉（包含
    `query_trade` 對髒 trade_id 的 `ValueError`）不可癱瘓整輪，一律計 errored，
    下一輪（明天）自然會再撈到重試。

    回傳計數（測試用）：refund_full／refund_partial／unresolved／errored。
    """
    order_repo = OrderRepository(db)
    svc = get_payments91_service()
    settlement = build_order_settlement(db)
    counts = {"refund_full": 0, "refund_partial": 0, "unresolved": 0, "errored": 0}

    # ★物化成 list：理由同 run_reconciliation_sweep——迴圈體對每筆都可能觸發 91APP
    # query_trade（httpx，最長 30s），沿用 async for 直接吃 motor cursor 會在長時間
    # 掛在迴圈中時撞 Mongo cursor idle timeout。
    orders = [o async for o in order_repo.iter_for_refund_audit()]

    for order in orders:
        order_no = order.get("merchant_order_no", "")
        try:
            await _refund_audit_one(order_repo, svc, settlement, order, counts)
        except Exception as e:
            counts["errored"] += 1
            log.error("payment.refund_audit.item_failed", order_no=order_no, error=str(e), exc_info=True)

    if any(counts.values()):
        log.info("payment.refund_audit.completed", **counts)
    return counts


async def _refund_audit_one(
    order_repo: OrderRepository, svc, settlement, order: Dict[str, Any], counts: Dict[str, int],
) -> None:
    order_no = order["merchant_order_no"]
    trade_id = order.get("trade_id") or ""

    # 輪替 stamp（比照 `_reconcile_one` 的 `last_reconciled_at`）：處理前先寫，讓
    # 積壓超過 batch 上限時，下一輪撈到的是「最久沒稽核過」的 200 筆，不會永遠卡
    # 在佇列頭部。
    await order_repo.stamp_refund_audited(order_no, get_utc_timestamp())

    if not trade_id:
        # 理論上不該發生在已 paid 的單——claim_paid 的 extra_updates 一定帶
        # trade_id（見 order_settlement.settle）。防禦性略過，不查也不算 errored
        # （沒有查詢對象，不是查詢失敗）。
        counts["unresolved"] += 1
        return

    # query_trade 對格式不符的 trade_id 直接 raise ValueError——交給外層 per-item
    # try/except 當 errored 計，下一輪（明天）重試（比 run_reconciliation_sweep
    # 的 gave_up 更寬鬆：這裡量體小、頻率低，不需要額外的放棄時鐘）。
    resp = await svc.query_trade(trade_id)

    # 判讀 gate 比照主 sweep：91APP 非 200 回應 body 常缺 recordStatus，直接丟給
    # interpret_record_status 會 fail-closed 誤判成失敗——這裡只認 6/7，其他一律
    # unresolved，不擅自判定。
    http_status = resp.get("_http_status")
    record_status = _find(resp, "recordstatus")
    if http_status != 200 or record_status is None:
        counts["unresolved"] += 1
        return

    try:
        rs = int(record_status)
    except (TypeError, ValueError):
        counts["unresolved"] += 1
        return

    if rs == 7:
        outcome = await settlement.handle_full_refund(order_no, trade_id=trade_id)
        counts["refund_full"] += 1
    elif rs == 6:
        outcome = await settlement.flag_partial_refund(order_no, record_status=6)
        counts["refund_partial"] += 1
    else:
        # 已付款單的正常 recordStatus（4/5 成功、2/3 是舊分支殘留不該再變動、
        # 1/8 待付款理論上不會出現在 paid 單身上）——不是退款就不動，維持 paid。
        counts["unresolved"] += 1
        return

    log.info(
        "payment.refund_audit.resolved",
        order_no=order_no, trade_id=trade_id, record_status=rs, outcome=outcome,
    )
