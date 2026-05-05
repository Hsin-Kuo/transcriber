"""配額管理器"""
from datetime import datetime, timedelta
from fastapi import HTTPException, status

from src.models.quota import QUOTA_TIERS, QuotaTier
from src.utils.time_utils import timestamp_to_datetime


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
    async def check_ai_summary_quota(user: dict, db=None):
        """檢查 AI 摘要配額（方案額度優先，不足時使用 extra_quota）"""
        quota = user.get("quota", {})
        usage = user.get("usage", {})
        extra_quota = user.get("extra_quota", {})

        usage = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=db)

        current_usage = usage.get("ai_summaries", 0)
        plan_limit = quota.get("max_ai_summaries") or _get_tier_default(user, "max_ai_summaries", 3)
        plan_remaining = max(0, plan_limit - current_usage)
        extra_remaining = max(0, extra_quota.get("ai_summaries", 0))
        total_available = plan_remaining + extra_remaining

        if total_available <= 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"AI 摘要次數不足（方案剩餘 {plan_remaining} 次，額外額度 {extra_remaining} 次）",
                    "quota": {
                        "plan_used": current_usage,
                        "plan_limit": plan_limit,
                        "plan_remaining": plan_remaining,
                        "extra_remaining": extra_remaining,
                        "type": "ai_summaries",
                    }
                }
            )
        return True

    @staticmethod
    async def increment_ai_summary_usage(db, user_id: str, user: dict = None):
        """增加 AI 摘要使用量（先扣方案額度，不足再扣 extra_quota）"""
        from bson import ObjectId

        plan_limit = 0
        current_usage = 0
        if user:
            quota = user.get("quota", {})
            usage = user.get("usage", {})
            plan_limit = quota.get("max_ai_summaries") or _get_tier_default(user, "max_ai_summaries", 3)
            current_usage = usage.get("ai_summaries", 0)

        plan_remaining = max(0, plan_limit - current_usage)

        if plan_remaining > 0:
            await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$inc": {
                        "usage.ai_summaries": 1,
                        "usage.total_ai_summaries": 1,
                    },
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
        else:
            await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$inc": {
                        "usage.total_ai_summaries": 1,
                        "extra_quota.ai_summaries": -1,
                    },
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )

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
                            print(f"⚠️ 訂閱到期降級寫入失敗：{e}")
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
                                "updated_at": now,
                            }
                        }
                    )
                except Exception as e:
                    print(f"⚠️ 自動重置配額寫回 DB 失敗：{e}")
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
                    "updated_at": now,
                }
            }
        )
        print(f"🔻 用戶 {user_id} 訂閱到期，已降為 free", flush=True)

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
                    "updated_at": datetime.utcnow(),
                }
            }
        )
