"""續扣排程器 + Dunning（91APP merchant-initiated 循環計費）。

91APP 無 gateway 自動續扣，由本地背景任務主動發起：到期以 `request-by-cardToken`（MIT 免 3D）
續扣，失敗走 Dunning（past_due 保留服務 → 智慧重試 → 寬限滿降 free）。

🔴 防重複扣款：呼叫 91APP 前先 claim（deterministic order_no per (user, period, attempt) 當
natural_id），只有一個 worker/replica 成功；order_no 亦作 N1-IDEMPOTENCY-KEY，跨重試穩定 →
即使 release 後重入，91APP 端仍冪等去重。動到 payment 走 judgment-rubrics §5。
"""
import asyncio
import os
from typing import Optional

from ..database.repositories.job_lease_repo import JobLeaseRepository
from ..database.repositories.order_repo import DuplicatePendingOrderError, OrderRepository
from ..database.repositories.processed_webhook_repo import ProcessedWebhookRepository
from ..database.repositories.user_repo import UserRepository
from .invoice_service import build_invoice_snapshot_from_user_invoice_info
from .order_settlement import build_order_settlement, PaymentNotification
from ..utils.payments91_service import get_payments91_service
from ..utils.card_token_cipher import decrypt
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

log = get_logger(__name__)

# Dunning 政策（使用者定案）：4 次重試、間隔 2 天、寬限 6 天
RETRY_MAX = 4
RETRY_INTERVAL_SECONDS = 2 * 86400
GRACE_SECONDS = 6 * 86400
RENEWAL_INTERVAL_SECONDS = 1800  # 每 30 分掃描（縮短「期末→扣款」窗口）

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# 失敗分類（statusCode → 行為），對應 ASSESSMENT §6
_CARD_FIX = {"CardExpired", "cardExpired", "CardNumberWrong", "NoCardToken", "CardTokenDecryptError"}
_HARD_STOP = {"CreditCardBlacklist", "IPBlacklist"}


def classify_failure(status_code: Optional[str]) -> str:
    """retryable | card_fix | hard_stop。預設可重試（餘額不足多落 RefuseTrade）。"""
    if status_code in _CARD_FIX:
        return "card_fix"
    if status_code in _HARD_STOP:
        return "hard_stop"
    return "retryable"


def _renewal_order_no(user_id: str, period_key: int, attempt: int) -> str:
    """(user, period, attempt) 的 deterministic 訂單號 → 穩定 idempotency key（≤50 字、半形英數）。"""
    return f"REN{period_key}A{attempt}{user_id[-8:]}"


# ── 背景排程 ────────────────────────────────────────────────────────────────

async def periodic_renewal_check(db, interval_seconds: int = RENEWAL_INTERVAL_SECONDS) -> None:
    """啟動嘗試搶當前時間窗執行權，搶到才立即跑一次；搶不到等下一輪。之後每 interval
    掃描。受 main.py 的 RUN_BACKGROUND_JOBS 保護（單主 replica）。

    🔴 P0-2(a)：prod 用 `uvicorn --workers 2`，兩個 worker process 都跑這個背景任務。用
    JobLeaseRepository 對本輪時間窗搶執行權，搶不到代表另一個 worker 已在跑本輪續扣掃描，
    本輪略過（否則同一個到期訂閱可能被兩個 worker 同時發起續扣）。lease 檢查本身失敗
    （DB 例外）採 fail-open：照跑本輪並記警告——sweep 本身靠 claim 冪等，寧可偶發重跑
    也不要續扣排程器全停。
    """
    lease_repo = JobLeaseRepository(db)
    while True:
        should_run = True
        try:
            should_run = await lease_repo.claim_window("renewal_sweep", interval_seconds)
        except Exception as e:
            log.warning("renewal.sweep.lease_check_failed", error=str(e))
        if should_run:
            try:
                await run_renewal_sweep(db)
            except Exception as e:
                log.error("renewal.sweep.failed", error=str(e), exc_info=True)
        await asyncio.sleep(interval_seconds)


async def run_renewal_sweep(db) -> dict:
    """一輪掃描：到期續扣 / past_due 重試 / 寬限滿降 free。回傳計數（測試用）。

    🔴 sweep 隔離：每個迴圈先把 cursor 物化成 list（理由同 invoice_service.py 的
    run_invoice_retry_sweep——迴圈體有長 I/O(91APP API 呼叫)，沿用 async for 直接吃
    motor cursor 會在長時間掛在迴圈中時撞 Mongo cursor idle timeout），逐筆處理並
    包 try/except，避免單筆例外癱瘓整輪掃描、留下其他到期用戶未被處理。
    """
    now_ts = get_utc_timestamp()
    counts = {"charged": 0, "retried": 0, "expired": 0, "errored": 0, "skipped_duplicate": 0}

    # 1) 到期續扣：active、未排定取消、next_charge_at 到期
    cursor = db.users.find(
        {
            "subscription.status": "active",
            "subscription.cancel_at_period_end": {"$ne": True},
            "subscription.next_charge_at": {"$lte": now_ts},
        },
        {"_id": 1, "subscription": 1, "invoice_info": 1},
    )
    users = [u async for u in cursor]
    for user in users:
        try:
            result = await _attempt_charge(db, user)
            if result == "skipped_duplicate":
                counts["skipped_duplicate"] += 1
            else:
                counts["charged"] += 1
        except Exception as e:
            counts["errored"] += 1
            log.error("renewal.sweep.item_failed", user_id=str(user.get("_id")), error=str(e), exc_info=True)

    # 2) past_due 重試：非 needs_card_update、到重試時間
    cursor = db.users.find(
        {
            "subscription.status": "past_due",
            "subscription.cancel_at_period_end": {"$ne": True},  # 已取消者不再重試
            "subscription.needs_card_update": {"$ne": True},
            "subscription.next_retry_at": {"$lte": now_ts},
        },
        {"_id": 1, "subscription": 1, "invoice_info": 1},
    )
    users = [u async for u in cursor]
    for user in users:
        try:
            result = await _attempt_charge(db, user)
            if result == "skipped_duplicate":
                counts["skipped_duplicate"] += 1
            else:
                counts["retried"] += 1
        except Exception as e:
            counts["errored"] += 1
            log.error("renewal.sweep.item_failed", user_id=str(user.get("_id")), error=str(e), exc_info=True)

    # 3) 寬限期滿（含 needs_card_update 未換卡者）→ 降 free
    grace_cutoff = now_ts - GRACE_SECONDS
    cursor = db.users.find(
        {
            "subscription.status": "past_due",
            "subscription.dunning_started_at": {"$lte": grace_cutoff},
        },
        {"_id": 1, "subscription": 1},
    )
    users = [u async for u in cursor]
    for user in users:
        try:
            await _expire_after_grace(db, user)
            counts["expired"] += 1
        except Exception as e:
            counts["errored"] += 1
            log.error("renewal.sweep.item_failed", user_id=str(user.get("_id")), error=str(e), exc_info=True)

    if any(counts.values()):
        log.info("renewal.sweep.completed", **counts)
    return counts


# ── 單筆處理 ────────────────────────────────────────────────────────────────

async def _attempt_charge(db, user: dict) -> Optional[str]:
    """對單一到期/待重試訂閱發動續扣（claim 去重 + 依結果走成功/Dunning）。

    回傳 "skipped_duplicate" 表示撞到 DuplicatePendingOrderError（使用者走 /update-card
    建了 in-flight pending 單，非錯誤）；其餘路徑回傳 None，呼叫端（sweep）依此分計數。
    """
    user_id = str(user["_id"])
    sub = user.get("subscription", {})

    if not sub.get("card_token"):
        # 沒有可續扣的 token → 進 past_due 並要求換卡
        await _handle_failure(db, user_id, sub, attempt=int(sub.get("dunning_attempts", 0)) + 1,
                              status_code="NoCardToken", message="無綁定卡片")
        return

    period_key = int(sub.get("next_charge_at") or 0)
    attempt = int(sub.get("dunning_attempts", 0)) + 1
    order_no = _renewal_order_no(user_id, period_key, attempt)

    webhook_repo = ProcessedWebhookRepository(db)
    # 🔴 扣款前 claim：只有一個 worker/replica 拿得到此 (user, period, attempt)
    if not await webhook_repo.claim(provider="91app-renewal", natural_id=order_no,
                                    metadata={"attempt": attempt}):
        log.info("renewal.attempt.already_claimed", user_id=user_id, order_no=order_no)
        return

    try:
        # 期末降級：pending_plan_change 存在 → 本期續扣用「目標 tier」，settle 成功即套用（見 order_settlement）
        pc = sub.get("pending_plan_change")
        if pc and pc.get("tier"):
            tier = pc["tier"]
            billing = pc.get("billing_cycle") or sub["billing_cycle"]
        else:
            tier = sub["tier"]
            billing = sub["billing_cycle"]
        svc = get_payments91_service()
        amount = svc.get_subscription_price(tier, billing)
        order_repo = OrderRepository(db)

        # deterministic order_no：若前次中斷已建同號單，續用（靠 idempotency key 去重）
        existing = await order_repo.get_by_order_no(order_no)
        if existing and existing.get("status") == "paid":
            return  # 已成功，勿重扣
        if not existing:
            await order_repo.create({
                "user_id": user_id,
                "merchant_order_no": order_no,
                "type": "renewal",
                "tier": tier,
                "billing_cycle": billing,
                "amount_twd": amount,
                "status": "pending",
                "card_token": sub.get("card_token"),
                # 取 user.invoice_info 當下值（經 key 對映 `type`→`invoice_type`）快照。
                "invoice_snapshot": build_invoice_snapshot_from_user_invoice_info(user.get("invoice_info")),
            })
    except DuplicatePendingOrderError:
        # 預期情況：使用者走 /update-card 建了 in-flight 的 pending recovery 單。
        # release claim，下輪 sweep 待該單解決/過期後可重試，不算錯誤，也不算「已扣款」。
        await webhook_repo.release(provider="91app-renewal", natural_id=order_no)
        log.warning("renewal.attempt.duplicate_pending_order", user_id=user_id, order_no=order_no)
        return "skipped_duplicate"
    except Exception as e:
        # 孤兒 claim 修復：建單前置作業（定價/查單）炸掉也要 release，否則此 (user, period, attempt)
        # 永久卡死、下輪 sweep 再也撈不到它。re-raise 讓上層 sweep 隔離層計入 errored。
        await webhook_repo.release(provider="91app-renewal", natural_id=order_no)
        log.error("renewal.attempt.setup_failed", user_id=user_id, order_no=order_no, error=str(e), exc_info=True)
        raise

    # P2-10（金流體檢）：sub["card_token"] 落庫時已加密，這是唯一使用點（實際扣款），
    # 單點解密成明文餵給 payments91_service（純 adapter，只認明文）。解密失敗（KEK 輪替
    # 未 re-encrypt、密文毀損）是永久性壞資料，重試不會變好——release claim 後走
    # needs_card_update dunning（比照 NoCardToken），逼使用者重新綁卡並停止每輪無限重試，
    # 而不是靜默 return 讓 sweep 每 30 分鐘重撞同一個壞 token（第二意見審查 LOW）。
    try:
        card_token_plain = decrypt(sub["card_token"])
    except Exception as e:
        await webhook_repo.release(provider="91app-renewal", natural_id=order_no)
        log.error("renewal.charge.decrypt_failed", user_id=user_id, order_no=order_no, error=str(e))
        await _handle_failure(db, user_id, sub, attempt, status_code="CardTokenDecryptError",
                              message="card_token 解密失敗")
        return

    try:
        resp = await svc.charge_renewal(
            card_token=card_token_plain,
            consumer_id=sub.get("merchant_consumer_id", user_id),
            order_no=order_no,
            amount=amount,
            redirect_url=f"{BACKEND_URL}/subscriptions/payment-return?order_no={order_no}",
            callback_url=f"{BACKEND_URL}/subscriptions/callback",
            prod_name=f"SoundLite {str(tier).capitalize()} 方案（續扣）",
            billing_cycle=billing,
        )
    except Exception as e:
        # 結果未知：release 讓下輪重試（order_no=idempotency key 保護不重扣）
        await webhook_repo.release(provider="91app-renewal", natural_id=order_no)
        log.error("renewal.charge.exception", user_id=user_id, order_no=order_no, error=str(e), exc_info=True)
        return

    status_code = resp.get("statusCode")
    if status_code == "Success":
        # 存卡別/末四碼供收據用（request-by-cardToken 回應含 cardInfo）
        ci = resp.get("cardInfo") or {}
        card_updates = {}
        if ci.get("cardBrand"):
            card_updates["card_brand"] = str(ci["cardBrand"])
        if ci.get("lastFour"):
            card_updates["card_last4"] = str(ci["lastFour"])
        if card_updates:
            await order_repo.update_by_order_no(order_no, card_updates)
        await build_order_settlement(db).settle(PaymentNotification(
            order_no=order_no, success=True, is_first_payment=False,
            trade_id=resp.get("tradeId") or "",
        ))
        log.info("renewal.charge.success", user_id=user_id, attempt=attempt, order_no=order_no)
    else:
        # F1（第二意見審查）：不得無條件覆寫。時序縫隙——sweep 發起扣款、91APP 先送
        # callback 且 settle() 已經 claim_paid 把單搶成 paid，這裡 charge_renewal 的
        # HTTP response 才姍姍來遲且回非 Success（例如逾時後 91APP 端其實成功了）。
        # 用 update_by_order_no 會無條件把已 paid 的單蓋成 failed，還讓 claim_paid 的
        # `$ne paid` 條件重新可搶（等於把已生效的續扣又打開一個重放縫隙）。
        await order_repo.mark_failed_unless_paid(order_no, {"status": "failed"})
        await _handle_failure(db, user_id, sub, attempt, status_code, resp.get("message"))


async def _handle_failure(db, user_id: str, sub: dict, attempt: int,
                          status_code: Optional[str], message: Optional[str]) -> None:
    """依失敗分類推進 Dunning 狀態機。"""
    category = classify_failure(status_code)
    now = get_utc_timestamp()
    log.warning("renewal.charge.failed", user_id=user_id, attempt=attempt,
                status_code=status_code, category=category)

    if category == "hard_stop":
        downgraded = await _downgrade(db, user_id, reason=f"hard_stop:{status_code}", sub_snapshot=sub)
        if downgraded:
            await _send_email(db, user_id, "downgraded", status_code)
        return

    updates = {
        "status": "past_due",
        "dunning_attempts": attempt,
        "last_payment_error": status_code,
        "updated_at": now,
    }
    if not sub.get("dunning_started_at"):
        updates["dunning_started_at"] = now  # 寬限起點（首次失敗）

    if category == "card_fix":
        updates["needs_card_update"] = True
        updates["next_retry_at"] = None  # 換卡類不自動重試（重試同卡無用）
        applied = await _apply_updates(db, user_id, sub, updates)
        if applied:
            await _send_email(db, user_id, "card_update", status_code)
        return

    # retryable：重試耗盡 → 降 free；否則排下次重試
    if attempt >= RETRY_MAX:
        downgraded = await _downgrade(db, user_id, reason=f"retries_exhausted:{status_code}", sub_snapshot=sub)
        if downgraded:
            await _send_email(db, user_id, "downgraded", status_code)
        return
    updates["next_retry_at"] = now + RETRY_INTERVAL_SECONDS
    applied = await _apply_updates(db, user_id, sub, updates)
    if applied:
        await _send_email(db, user_id, "payment_failed" if attempt == 1 else "final_notice", status_code)


async def _expire_after_grace(db, user: dict) -> None:
    user_id = str(user["_id"])
    sub = user.get("subscription", {})
    downgraded = await _downgrade(db, user_id, reason="grace_expired", sub_snapshot=sub)
    if downgraded:
        await _send_email(db, user_id, "downgraded", sub.get("last_payment_error"))


# ── 狀態變更 helpers ─────────────────────────────────────────────────────────

async def _apply_updates(db, user_id: str, sub: dict, updates: dict) -> bool:
    """P0-2(b)：dotted $set 只寫 `updates` 指定的欄位（不再讀-改-寫整包 subscription 快照）。

    guard=next_charge_at：呼叫端手上的 `sub` 是掃描當下的快照，next_charge_at 是續扣
    狀態的天然版本 token——若併發的續扣成功已經推進它，代表我們手上這份 past_due 判斷
    已經過期，這次 dunning 更新應該放棄（靜默略過，不重試；下一輪 sweep 會用新狀態
    重新判斷），而不是照樣覆寫把剛續約成功的訂閱打回 past_due。

    回傳是否真的寫入（F4，第二意見審查）：guard 沒中時呼叫端不該寄 dunning 通知信——
    訂閱已經被併發續約救回，寄「卡片有問題」或「付款失敗」信會誤導用戶。
    """
    guard = {"subscription.next_charge_at": sub.get("next_charge_at")}
    ok = await UserRepository(db).update_subscription_fields(user_id, updates, guard=guard)
    if not ok:
        log.warning("renewal.dunning.update_skipped_stale", user_id=user_id)
    return ok


async def _downgrade(db, user_id: str, reason: str, sub_snapshot: Optional[dict] = None) -> bool:
    """寬限滿/重試耗盡/硬停 → 降 free（reuse OrderSettlement 的到期降級：status expired + quota free + 釘選核對）。

    P0-2(b)：sub_snapshot 有值時帶 guard=next_charge_at（樂觀併發）——併發續約成功會
    推進 next_charge_at，guard 不符代表訂閱已經被續約救回，這次降級應該放棄（訂閱沒動
    就不能動配額）。回傳是否真的降級，供呼叫端決定要不要寄「已降級」通知信。
    """
    log.warning("renewal.downgrade", user_id=user_id, reason=reason)
    guard = None
    if sub_snapshot is not None:
        guard = {"subscription.next_charge_at": sub_snapshot.get("next_charge_at")}
    ok = await build_order_settlement(db)._expire_to_free(user_id, guard=guard)
    if not ok:
        log.warning("renewal.downgrade.skipped_stale", user_id=user_id, reason=reason)
    return ok


async def _send_email(db, user_id: str, kind: str, status_code: Optional[str]) -> None:
    """寄 dunning 通知（best-effort，絕不拖垮續扣流程）。"""
    try:
        from ..utils.email_service import get_email_service
        user = await UserRepository(db).get_by_id(user_id)
        if not user or user.get("email_bounced"):
            return
        to = user.get("email")
        if not to:
            return
        lang = (user.get("preferences") or {}).get("language", "zh-TW")
        sub = user.get("subscription", {})
        svc = get_email_service()
        await svc.send_dunning_email(to_email=to, kind=kind, lang=lang, subscription=sub)
    except Exception as e:
        log.error("renewal.email.failed", user_id=user_id, kind=kind, error=str(e))
