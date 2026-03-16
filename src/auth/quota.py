"""配額管理器"""
from datetime import datetime, timedelta
from fastapi import HTTPException, status

from src.utils.time_utils import timestamp_to_datetime


class QuotaManager:
    """配額管理器"""

    @staticmethod
    async def check_transcription_quota(user: dict, audio_duration: float, db=None):
        """檢查轉錄配額

        Args:
            user: 用戶資料
            audio_duration: 音訊時長 (秒)
            db: 資料庫實例（用於跨月自動歸零寫回）

        Raises:
            HTTPException: 配額不足
        """
        quota = user.get("quota", {})
        usage = user.get("usage", {})

        # 重置每月配額 (如果需要)
        usage = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=db)

        # 檢查轉錄時數
        duration_minutes = audio_duration / 60
        current_usage = usage.get("duration_minutes", 0)
        quota_limit = quota.get("max_duration_minutes", 60)

        if current_usage + duration_minutes > quota_limit:
            remaining = max(0, quota_limit - current_usage)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"本月剩餘時數不足 (剩餘 {remaining:.1f} 分鐘)",
                    "quota": {
                        "used": current_usage,
                        "limit": quota_limit,
                        "remaining": remaining,
                        "type": "duration_minutes"
                    }
                }
            )

        return True

    @staticmethod
    async def check_concurrent_tasks(user: dict, active_count: int):
        """檢查並發任務數

        Args:
            user: 用戶資料
            active_count: 當前進行中的任務數

        Raises:
            HTTPException: 超過並發限制
        """
        quota = user.get("quota", {})
        max_concurrent = quota.get("max_concurrent_tasks", 1)

        if active_count >= max_concurrent:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"已達並發任務數上限 ({max_concurrent} 個)",
                    "quota": {
                        "current": active_count,
                        "limit": max_concurrent,
                        "type": "concurrent_tasks"
                    }
                }
            )

    @staticmethod
    async def check_ai_summary_quota(user: dict, db=None):
        """檢查 AI 摘要配額

        Args:
            user: 用戶資料
            db: 資料庫實例（用於跨月自動歸零寫回）

        Raises:
            HTTPException: 配額不足
        """
        quota = user.get("quota", {})
        usage = user.get("usage", {})

        # 重置每月配額 (如果需要)
        usage = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=db)

        current_usage = usage.get("ai_summaries", 0)
        quota_limit = quota.get("max_ai_summaries", 3)

        if current_usage >= quota_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"本月 AI 摘要次數已達上限 ({quota_limit} 次)",
                    "quota": {
                        "used": current_usage,
                        "limit": quota_limit,
                        "remaining": 0,
                        "type": "ai_summaries"
                    }
                }
            )

        return True

    @staticmethod
    async def increment_ai_summary_usage(db, user_id: str):
        """增加 AI 摘要使用量

        Args:
            db: 資料庫實例
            user_id: 用戶 ID
        """
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$inc": {
                    "usage.ai_summaries": 1,
                    "usage.total_ai_summaries": 1
                },
                "$set": {
                    "updated_at": datetime.utcnow()
                }
            }
        )

    @staticmethod
    async def increment_usage(db, user_id: str, duration_seconds: float):
        """增加使用量統計

        Args:
            db: 資料庫實例
            user_id: 用戶 ID
            duration_seconds: 轉錄時長（秒）
        """
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$inc": {
                    "usage.transcriptions": 1,
                    "usage.duration_minutes": duration_seconds / 60,
                    "usage.total_transcriptions": 1,
                    "usage.total_duration_minutes": duration_seconds / 60
                },
                "$set": {
                    "updated_at": datetime.utcnow()
                }
            }
        )

    @staticmethod
    async def _reset_monthly_quota_if_needed(user: dict, usage: dict, db=None) -> dict:
        """重置每月配額 (如果需要)

        Args:
            user: 用戶資料
            usage: 使用量資料
            db: 資料庫實例（有提供時會寫回 DB）

        Returns:
            更新後的使用量資料
        """
        last_reset = usage.get("last_reset")

        if not last_reset:
            return usage

        # 轉換 Unix timestamp 為 datetime（如果需要）
        if isinstance(last_reset, (int, float)):
            last_reset = timestamp_to_datetime(last_reset)

        # 檢查是否跨月
        now = datetime.utcnow()
        if now.month != last_reset.month or now.year != last_reset.year:
            new_usage = {
                "transcriptions": 0,
                "duration_minutes": 0,
                "ai_summaries": 0,
                "last_reset": now,
                "total_transcriptions": usage.get("total_transcriptions", 0),
                "total_duration_minutes": usage.get("total_duration_minutes", 0),
                "total_ai_summaries": usage.get("total_ai_summaries", 0)
            }

            # 寫回 DB
            if db is not None:
                try:
                    from bson import ObjectId
                    user_id = str(user["_id"])
                    await db.users.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "usage.transcriptions": 0,
                                "usage.duration_minutes": 0,
                                "usage.ai_summaries": 0,
                                "usage.last_reset": now,
                                "updated_at": now
                            }
                        }
                    )
                    print(f"🔄 已自動重置用戶 {user_id} 的每月配額")
                except Exception as e:
                    print(f"⚠️ 自動重置配額寫回 DB 失敗：{e}")

            return new_usage

        return usage

    @staticmethod
    async def reset_user_monthly_quota(db, user_id: str):
        """手動重置用戶每月配額

        Args:
            db: 資料庫實例
            user_id: 用戶 ID
        """
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "usage.transcriptions": 0,
                    "usage.duration_minutes": 0,
                    "usage.ai_summaries": 0,
                    "usage.last_reset": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            }
        )
