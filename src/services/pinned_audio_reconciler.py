"""方案降級時的釘選音檔核對（reconcile pinned audio on tier downgrade）。

降級（主動降級結算 / 訂閱到期 / 續扣失敗）後，使用者的 max_keep_audio 可能低於
目前釘選數。本模組把「超過新方案額度」的釘選音檔釋放，但給一段寬限期（grace
period）而非立刻刪除：

  - 保留「最新完成」的 N 個（N = 新方案 max_keep_audio），其餘最舊的釋放。
  - 釋放 = keep_audio→False ＋ 把 S3 音檔從 kept/ 搬回新 tier 資料夾
    （copy+delete 會重設物件年齡 → S3 Lifecycle 從現在起算，天然等於寬限期）
    ＋ 寫 audio_expires_at = now + 新方案 retention（給 is_audio_expired / 前端 badge，
    與 lifecycle 對齊）。
  - 寄信通知使用者「N 個保留音檔將於 X 日刪除」。

設計要點：
  - idempotent：超額為 0 直接 no-op；可安全重複呼叫（每次依當下超額量重算）。
  - best-effort：個別 S3 搬移失敗只記 log，不拋例外拖垮呼叫端（金流 webhook /
    到期流程）。呼叫端務必在 quota 寫入 commit 之後才呼叫本函式。

手動取消釘選（PUT /keep-audio）刻意不走這條寬限期路徑——那是使用者明確意圖，
維持既有「舊檔秒刪」行為。本模組只處理「系統強制降級」。
"""
from datetime import datetime, timezone
from typing import Any, Dict, List

from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.user_repo import UserRepository
from ..models.quota import QUOTA_TIERS, QuotaTier
from ..utils.logger import get_logger
from ..utils.time_utils import get_utc_timestamp

log = get_logger(__name__)

SECONDS_PER_DAY = 86400


def _completed_at_ts(task: Dict[str, Any]) -> float:
    """取任務完成時間的 Unix 秒（排序用）；缺失/無法解析回 0（排最舊、優先釋放）。"""
    ts = (task.get("timestamps") or {}).get("completed_at")
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts).timestamp()
        except ValueError:
            return 0.0
    return 0.0


async def reconcile_pinned_audio(db, user_id: str, new_tier: str) -> int:
    """把超過新方案額度的釘選音檔釋放並進入寬限期。回傳被釋放的音檔數。

    best-effort：本函式自行吞掉所有例外（除了無法辨識的 tier 直接 no-op），
    確保不會拖垮呼叫端的降級流程。
    """
    try:
        tier_cfg = QUOTA_TIERS.get(QuotaTier(new_tier))
    except ValueError:
        tier_cfg = None
    if tier_cfg is None:
        return 0

    max_keep = tier_cfg.get("max_keep_audio", 0)
    retention_days = tier_cfg.get("audio_retention_days", 7)

    task_repo = TaskRepository(db)
    try:
        cursor = task_repo.collection.find({
            **task_repo.owned_by(user_id),
            "keep_audio": True,
            "result.audio_file": {"$exists": True, "$ne": None},
            "deleted": {"$ne": True},
        })
        pinned: List[Dict[str, Any]] = await cursor.to_list(length=None)
    except Exception as e:
        log.error("pinned_audio.reconcile.query_failed", user_id=user_id, error=str(e), exc_info=True)
        return 0

    if len(pinned) <= max_keep:
        return 0  # idempotent no-op

    # 保留最新完成的 max_keep 個，其餘（最舊的）釋放
    pinned.sort(key=_completed_at_ts, reverse=True)
    released = pinned[max_keep:]

    expires_at = get_utc_timestamp() + retention_days * SECONDS_PER_DAY

    # lazy import 避免 storage 層 import cycle
    from ..utils.storage.compact import extract_tier_from_path, move_audio
    from ..utils.storage.backend import is_aws

    released_ok = 0
    for task in released:
        task_id = task.get("_id")
        try:
            audio_path = (task.get("result") or {}).get("audio_file")
            new_path = audio_path
            if is_aws() and audio_path:
                # 搬出 kept/ → 新 tier 資料夾，重設 S3 物件年齡 → lifecycle 從現在起算
                if extract_tier_from_path(audio_path) == "kept":
                    new_path = move_audio(task_id, "kept", new_tier)
            updates = {"keep_audio": False, "audio_expires_at": expires_at}
            if new_path != audio_path:
                updates["result.audio_file"] = new_path
            await task_repo.update(task_id, updates)
            released_ok += 1
        except Exception as e:
            log.error(
                "pinned_audio.reconcile.release_failed",
                user_id=user_id, task_id=task_id, error=str(e), exc_info=True,
            )

    if released_ok:
        log.info(
            "pinned_audio.reconcile.released",
            user_id=user_id, new_tier=new_tier, released=released_ok,
            max_keep=max_keep, expires_at=expires_at,
        )
        await _notify_release(db, user_id, released_ok, expires_at)

    return released_ok


async def _notify_release(db, user_id: str, released_count: int, expires_at: int) -> None:
    """寄信通知使用者保留音檔被釋放、將於寬限期結束時刪除（best-effort）。"""
    try:
        user = await UserRepository(db).get_by_id(user_id)
        email = (user or {}).get("email")
        if not email:
            return
        expiry_date = datetime.fromtimestamp(expires_at, tz=timezone.utc).strftime("%Y-%m-%d")
        from ..utils.email_service import get_email_service
        await get_email_service().send_audio_grace_period_email(
            to_email=email,
            released_count=released_count,
            expiry_date=expiry_date,
        )
    except Exception as e:
        log.error("pinned_audio.reconcile.notify_failed", user_id=user_id, error=str(e), exc_info=True)
