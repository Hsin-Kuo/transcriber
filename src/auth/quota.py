"""配額管理器"""
import asyncio
from datetime import datetime, timedelta
from fastapi import HTTPException, status

from src.models.quota import QUOTA_TIERS, QuotaTier
from src.utils.time_utils import get_utc_timestamp, timestamp_to_datetime
from src.utils.logger import get_logger

log = get_logger(__name__)


def _get_tier_default(user: dict, field: str, fallback):
    tier_str = user.get("quota", {}).get("tier", "free")
    try:
        tier_enum = QuotaTier(tier_str)
        return QUOTA_TIERS[tier_enum].get(field, fallback)
    except (ValueError, KeyError):
        return fallback


class QuotaManager:
    """配額管理器"""

    @staticmethod
    async def check_transcription_quota(user: dict, audio_duration: float, db=None):
        """檢查轉錄配額（方案額度優先，不足時使用 extra_quota）"""
        quota = user.get("quota", {})
        usage = user.get("usage", {})
        extra_quota = user.get("extra_quota", {})

        usage = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=db)

        duration_minutes = audio_duration / 60
        current_usage = usage.get("duration_minutes", 0)
        plan_limit = quota.get("max_duration_minutes") or _get_tier_default(user, "max_duration_minutes", 60)
        plan_remaining = max(0.0, plan_limit - current_usage)
        extra_remaining = max(0.0, extra_quota.get("duration_minutes", 0))
        total_available = plan_remaining + extra_remaining

        if total_available < duration_minutes:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"轉錄時數不足（方案剩餘 {plan_remaining:.1f} 分鐘，額外額度 {extra_remaining:.1f} 分鐘）",
                    "quota": {
                        "plan_used": current_usage,
                        "plan_limit": plan_limit,
                        "plan_remaining": plan_remaining,
                        "extra_remaining": extra_remaining,
                        "total_available": total_available,
                        "requested": duration_minutes,
                        "type": "duration_minutes",
                    }
                }
            )
        return True

    @staticmethod
    async def check_concurrent_tasks(user: dict, active_count: int):
        """檢查並發任務數"""
        quota = user.get("quota", {})
        max_concurrent = quota.get("max_concurrent_tasks") or _get_tier_default(user, "max_concurrent_tasks", 1)

        if active_count >= max_concurrent:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"已達並發任務數上限 ({max_concurrent} 個)",
                    "quota": {
                        "current": active_count,
                        "limit": max_concurrent,
                        "type": "concurrent_tasks",
                    }
                }
            )

    @staticmethod
    def _ai_summary_plan_limit(user: dict) -> int:
        """取得用戶的方案 AI 摘要上限（quota 未設定時 fallback 到 tier 預設）"""
        quota = user.get("quota", {}) or {}
        return quota.get("max_ai_summaries") or _get_tier_default(user, "max_ai_summaries", 3)

    @staticmethod
    async def reserve_ai_summary(db, user_id: str, user: dict = None):
        """原子預扣 1 次 AI 摘要配額（防並發超扣 / 防被刷 Gemini 費用）

        方案B：只動 user doc 單一文件，用 $expr filter 做 atomic check-and-reserve，
        不需要獨立 collection、transaction、retry（與轉錄的 reservation 機制不同）。

        檢查條件（在 DB 端原子計算）：
            usage.ai_summaries + reserved_ai_summaries + 1
                <= plan_limit + extra_quota.ai_summaries
        通過則 $inc reserved_ai_summaries；find_one_and_update 回 None 代表額度不足。

        呼叫此方法成功後，務必接著呼叫：
          - consume_ai_summary()  → Gemini 成功，預扣轉為實際使用量
          - release_ai_summary()  → Gemini 失敗 / 例外，單純釋放預扣
        """
        from bson import ObjectId

        # 先觸發月配額重置（與 ReservationRepository.reserve_transcription 一致）：
        # 重置會把 usage.ai_summaries 歸零寫回 DB，下面的 $expr 才讀得到最新值。
        if user is None:
            user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用戶不存在",
            )
        await QuotaManager._reset_monthly_quota_if_needed(user, user.get("usage", {}), db=db)

        plan_limit = QuotaManager._ai_summary_plan_limit(user)

        result = await db.users.find_one_and_update(
            {
                "_id": ObjectId(user_id),
                "$expr": {
                    "$lte": [
                        {"$add": [
                            {"$ifNull": ["$usage.ai_summaries", 0]},
                            {"$ifNull": ["$reserved_ai_summaries", 0]},
                            1,
                        ]},
                        {"$add": [
                            plan_limit,
                            {"$ifNull": ["$extra_quota.ai_summaries", 0]},
                        ]},
                    ]
                },
            },
            {
                "$inc": {"reserved_ai_summaries": 1},
                "$set": {
                    # 給背景清掃任務判斷孤兒用：記錄最近一次 reserve 的時間
                    "reserved_ai_summaries_at": get_utc_timestamp(),
                    "updated_at": get_utc_timestamp(),
                },
            },
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "AI 摘要次數不足",
                    "quota": {"type": "ai_summaries"},
                }
            )
        return True

    @staticmethod
    async def consume_ai_summary(db, user_id: str, user: dict = None):
        """將預扣轉為實際使用量（Gemini 成功後呼叫）

        原子 pipeline：扣 reserved_ai_summaries 1，並依方案餘額把這 1 次分流到
        usage.ai_summaries 或 extra_quota.ai_summaries。
        """
        from bson import ObjectId

        plan_limit = QuotaManager._ai_summary_plan_limit(user) if user else 3
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            build_ai_summary_consumption_pipeline(plan_limit, get_utc_timestamp()),
        )

    @staticmethod
    async def release_ai_summary(db, user_id: str):
        """釋放預扣（Gemini 失敗 / 例外時呼叫），不影響使用量

        用 filter 條件確保 reserved_ai_summaries 不會被扣成負數。
        """
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id), "reserved_ai_summaries": {"$gt": 0}},
            {
                "$inc": {"reserved_ai_summaries": -1},
                "$set": {"updated_at": get_utc_timestamp()},
            },
        )

    @staticmethod
    async def sweep_stale_ai_summary_reservations(db, grace_seconds: int = 1800) -> int:
        """清掃孤兒 AI 摘要預扣（背景任務用）

        AI 摘要的 reserve → consume/release 都在單一 HTTP 請求內同步完成，
        一個請求不可能跑超過 grace_seconds（預設 30 分鐘）。因此
        「reserved_ai_summaries > 0 且 reserved_ai_summaries_at 早於 cutoff」
        必定是 process 在請求中途崩潰留下的孤兒，直接歸零釋放。

        正常流程必定會 consume 或 release，不會留下殘留；只有崩潰才會。

        Returns:
            被修正的用戶數
        """
        cutoff = get_utc_timestamp() - grace_seconds
        result = await db.users.update_many(
            {
                "reserved_ai_summaries": {"$gt": 0},
                "reserved_ai_summaries_at": {"$lt": cutoff},
            },
            {
                "$set": {
                    "reserved_ai_summaries": 0,
                    "updated_at": get_utc_timestamp(),
                }
            },
        )
        return result.modified_count

    @staticmethod
    async def _reset_monthly_quota_if_needed(user: dict, usage: dict, db=None) -> dict:
        """
        重置每月配額（如需要）+ 偵測訂閱到期。

        付費用戶：比對 current_period_start 是否 > last_reset
        免費用戶：日曆月制
        到期偵測：current_period_end < now → 自動降為 free
        """
        last_reset = usage.get("last_reset")
        if not last_reset:
            return usage

        if isinstance(last_reset, (int, float)):
            last_reset = timestamp_to_datetime(last_reset)

        now = datetime.utcnow()
        sub = user.get("subscription", {})
        sub_status = sub.get("status")
        should_reset = False

        # ── 訂閱到期偵測 ───────────────────────────────────────
        if sub_status == "active":
            period_end = sub.get("current_period_end")
            if period_end:
                if isinstance(period_end, (int, float)):
                    period_end_dt = datetime.utcfromtimestamp(period_end)
                elif isinstance(period_end, datetime):
                    period_end_dt = period_end
                else:
                    period_end_dt = None

                if period_end_dt and period_end_dt < now:
                    # 訂閱已到期，降為 free
                    if db is not None:
                        try:
                            await QuotaManager._expire_subscription(db, user)
                        except Exception as e:
                            log.warning("quota.subscription.expire.writeback_failed", error=str(e))
                    # 繼續走免費用戶邏輯
                    sub_status = "expired"

        # ── 重置判斷 ────────────────────────────────────────────
        if sub_status in ("active", "trialing"):
            period_start = sub.get("current_period_start")
            if period_start:
                if isinstance(period_start, (int, float)):
                    period_start_dt = datetime.utcfromtimestamp(period_start)
                elif isinstance(period_start, datetime):
                    period_start_dt = period_start
                else:
                    period_start_dt = None

                if period_start_dt and period_start_dt > last_reset:
                    should_reset = True
        else:
            if now.month != last_reset.month or now.year != last_reset.year:
                should_reset = True

        if should_reset:
            new_usage = {
                "transcriptions": 0,
                "duration_minutes": 0,
                "ai_summaries": 0,
                "last_reset": now,
                "total_transcriptions": usage.get("total_transcriptions", 0),
                "total_duration_minutes": usage.get("total_duration_minutes", 0),
                "total_ai_summaries": usage.get("total_ai_summaries", 0),
            }
            if db is not None:
                try:
                    from bson import ObjectId
                    await db.users.update_one(
                        {"_id": ObjectId(str(user["_id"]))},
                        {
                            "$set": {
                                "usage.transcriptions": 0,
                                "usage.duration_minutes": 0,
                                "usage.ai_summaries": 0,
                                "usage.last_reset": now,
                                "updated_at": get_utc_timestamp(),
                            }
                        }
                    )
                except Exception as e:
                    log.warning("quota.monthly_reset.writeback_failed", error=str(e))
            return new_usage

        return usage

    @staticmethod
    async def _expire_subscription(db, user: dict):
        """訂閱到期：更新狀態並降為 free 配額"""
        from bson import ObjectId
        from src.models.quota import QUOTA_TIERS, QuotaTier

        user_id = str(user["_id"])
        now = datetime.utcnow()
        free_config = QUOTA_TIERS[QuotaTier.FREE]
        free_quota = {
            "tier": "free",
            **{k: v for k, v in free_config.items() if k not in ("name", "price")},
        }

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "subscription.status": "expired",
                    "subscription.updated_at": now.timestamp(),
                    "quota": free_quota,
                    "updated_at": get_utc_timestamp(),
                }
            }
        )
        log.warning("quota.subscription.expired", user_id=user_id, downgraded_to="free")

    @staticmethod
    async def reset_user_monthly_quota(db, user_id: str):
        """手動重置用戶每月配額（新計費週期開始時）"""
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "usage.transcriptions": 0,
                    "usage.duration_minutes": 0,
                    "usage.ai_summaries": 0,
                    "usage.last_reset": datetime.utcnow(),
                    "updated_at": get_utc_timestamp(),
                }
            }
        )


def build_transcription_consumption_pipeline(duration_minutes: float, now_ts: int) -> list:
    """建立轉錄消耗的 MongoDB pipeline update

    在 DB 端原子計算：
      plan_remaining = max(0, quota.max_duration_minutes - usage.duration_minutes)
      from_plan = min(plan_remaining, duration_minutes)
      from_extra = min(duration_minutes - from_plan, extra_quota.duration_minutes)

      usage.duration_minutes += from_plan
      extra_quota.duration_minutes -= from_extra
      usage.transcriptions += 1
      usage.total_transcriptions += 1
      usage.total_duration_minutes += duration_minutes  (永遠記實際時長)

    保證 extra_quota.duration_minutes 永不為負（被 $min 與 $max 雙重保護）。
    若 race 導致 plan + extra 不足，會「扣不完」（小幅免費），但不會破壞資料。

    Args:
        duration_minutes: 此次要扣的實際時長（分鐘）
        now_ts: updated_at 時間戳

    Returns:
        MongoDB aggregation pipeline（list of stages），給 update_one 用
    """
    return [
        # Stage 1: 算 plan_remaining
        {"$set": {
            "_plan_remaining": {
                "$max": [
                    0,
                    {"$subtract": [
                        {"$ifNull": ["$quota.max_duration_minutes", 60]},
                        {"$ifNull": ["$usage.duration_minutes", 0]},
                    ]},
                ]
            }
        }},
        # Stage 2: 算 from_plan
        {"$set": {
            "_from_plan": {"$min": ["$_plan_remaining", duration_minutes]}
        }},
        # Stage 3: 算 from_extra（被當下 extra 餘額 cap）
        {"$set": {
            "_from_extra": {
                "$min": [
                    {"$subtract": [duration_minutes, "$_from_plan"]},
                    {"$ifNull": ["$extra_quota.duration_minutes", 0]},
                ]
            }
        }},
        # Stage 4: 套用扣款 + 累加統計
        {"$set": {
            "usage.duration_minutes": {
                "$add": [{"$ifNull": ["$usage.duration_minutes", 0]}, "$_from_plan"]
            },
            "extra_quota.duration_minutes": {
                "$subtract": [
                    {"$ifNull": ["$extra_quota.duration_minutes", 0]},
                    "$_from_extra",
                ]
            },
            "usage.transcriptions": {
                "$add": [{"$ifNull": ["$usage.transcriptions", 0]}, 1]
            },
            "usage.total_transcriptions": {
                "$add": [{"$ifNull": ["$usage.total_transcriptions", 0]}, 1]
            },
            "usage.total_duration_minutes": {
                "$add": [{"$ifNull": ["$usage.total_duration_minutes", 0]}, duration_minutes]
            },
            "updated_at": now_ts,
        }},
        # Stage 5: 清掉暫存欄位
        {"$unset": ["_plan_remaining", "_from_plan", "_from_extra"]},
    ]


def build_ai_summary_consumption_pipeline(plan_limit: int, now_ts: int) -> list:
    """建立 AI 摘要消耗的 MongoDB pipeline update（每次固定扣 1 次）

    在 DB 端原子計算：
      plan_remaining = max(0, plan_limit - usage.ai_summaries)
      from_plan = min(plan_remaining, 1)   # 1 或 0
      from_extra = 1 - from_plan

      usage.ai_summaries += from_plan
      usage.total_ai_summaries += 1
      extra_quota.ai_summaries -= from_extra
      reserved_ai_summaries = max(0, reserved_ai_summaries - 1)  # 把預扣轉成實際使用

    與 build_transcription_consumption_pipeline 同樣的設計：方案額度優先，
    不足才動 extra_quota，且 extra_quota 永不為負。

    Args:
        plan_limit: 用戶方案的 AI 摘要上限
        now_ts: updated_at 時間戳

    Returns:
        MongoDB aggregation pipeline（list of stages），給 update_one 用
    """
    return [
        # Stage 1: 算 plan_remaining
        {"$set": {
            "_plan_remaining": {
                "$max": [
                    0,
                    {"$subtract": [
                        plan_limit,
                        {"$ifNull": ["$usage.ai_summaries", 0]},
                    ]},
                ]
            }
        }},
        # Stage 2: 算 from_plan（1 或 0）
        {"$set": {
            "_from_plan": {"$min": ["$_plan_remaining", 1]}
        }},
        # Stage 3: 套用扣款 + 累加統計 + 釋放預扣
        {"$set": {
            "usage.ai_summaries": {
                "$add": [{"$ifNull": ["$usage.ai_summaries", 0]}, "$_from_plan"]
            },
            "usage.total_ai_summaries": {
                "$add": [{"$ifNull": ["$usage.total_ai_summaries", 0]}, 1]
            },
            "extra_quota.ai_summaries": {
                "$subtract": [
                    {"$ifNull": ["$extra_quota.ai_summaries", 0]},
                    {"$subtract": [1, "$_from_plan"]},
                ]
            },
            "reserved_ai_summaries": {
                "$max": [
                    0,
                    {"$subtract": [{"$ifNull": ["$reserved_ai_summaries", 0]}, 1]},
                ]
            },
            "updated_at": now_ts,
        }},
        # Stage 4: 清掉暫存欄位
        {"$unset": ["_plan_remaining", "_from_plan"]},
    ]


async def periodic_subscription_expiry_check(db, interval_seconds: int = 3600) -> None:
    """定期掃描已過期但 status 仍為 active 的訂閱，主動降級為 free。

    解決：用戶訂閱到期但從未登入，DB 中 status 永遠顯示 active 的問題。
    現有 lazy 機制（_reset_monthly_quota_if_needed）只在用戶請求時觸發。

    第一次 sweep 在啟動後立即跑（不等 interval），避免 restart 緊接的時段
    沒被 sweep 覆蓋；之後每 interval_seconds 跑一次。
    """
    while True:
        try:
            now_ts = get_utc_timestamp()
            cursor = db.users.find(
                {
                    "subscription.status": "active",
                    "subscription.current_period_end": {"$lt": now_ts},
                },
                {"_id": 1, "subscription": 1}
            )
            expired_count = 0
            async for user in cursor:
                await QuotaManager._expire_subscription(db, user)
                expired_count += 1
            if expired_count:
                log.info("subscription.expiry_sweep.completed", expired=expired_count)
        except Exception as e:
            log.error("subscription.expiry_sweep.failed", error=str(e), exc_info=True)
        await asyncio.sleep(interval_seconds)
