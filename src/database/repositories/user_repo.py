"""用戶資料存取層"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from bson import ObjectId

from ...utils.time_utils import get_utc_timestamp
from src.utils.logger import get_logger

log = get_logger(__name__)


class UserRepository:
    """用戶資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.users

    async def create_indexes(self):
        """建立索引"""
        # Partial index：只索引「正在預扣 AI 摘要」的用戶（平常幾乎是空集合），
        # 讓 sweep_stale_ai_summary_reservations 的背景掃描不需要全表掃 users。
        await self.collection.create_index(
            [("reserved_ai_summaries", 1)],
            partialFilterExpression={"reserved_ai_summaries": {"$gt": 0}},
        )
        log.info("user.indexes.created")

    async def create(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立新用戶"""
        result = await self.collection.insert_one(user_data)
        user_data["_id"] = result.inserted_id
        return user_data

    async def get_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根據 ID 獲取用戶"""
        try:
            return await self.collection.find_one({"_id": ObjectId(user_id)})
        except:
            return None

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """根據 Email 獲取用戶"""
        return await self.collection.find_one({"email": email})

    async def get_by_verification_token(self, token: str) -> Optional[Dict[str, Any]]:
        """根據驗證 token 獲取用戶"""
        return await self.collection.find_one({"verification_token": token})

    async def get_by_password_reset_token(self, token: str) -> Optional[Dict[str, Any]]:
        """根據密碼重設 token 獲取用戶"""
        return await self.collection.find_one({"password_reset_token": token})

    async def get_by_google_id(self, google_id: str) -> Optional[Dict[str, Any]]:
        """根據 Google ID 獲取用戶"""
        return await self.collection.find_one({"google_id": google_id})

    async def delete(self, user_id: str) -> bool:
        """刪除用戶"""
        try:
            result = await self.collection.delete_one({"_id": ObjectId(user_id)})
            return result.deleted_count > 0
        except:
            return False

    async def update(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """更新用戶資料"""
        updates["updated_at"] = get_utc_timestamp()
        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def update_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新用戶偏好設定（merge 而非覆蓋）"""
        set_fields = {
            f"preferences.{key}": value
            for key, value in preferences.items()
            if value is not None
        }
        if not set_fields:
            # 沒有要更新的欄位，直接回傳現有 preferences
            user = await self.get_by_id(user_id)
            return user.get("preferences", {}) if user else {}

        set_fields["updated_at"] = get_utc_timestamp()
        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": set_fields},
            return_document=True
        )
        return result.get("preferences", {}) if result else None

    async def update_quota(self, user_id: str, quota: Dict[str, Any]) -> bool:
        """更新用戶配額"""
        return await self.update(user_id, {"quota": quota})

    MAX_REFRESH_TOKENS = 5  # 最多保留 5 個同時登入的 session

    async def save_refresh_token(self, user_id: str, token: str) -> bool:
        """保存 Refresh Token（清理無效 token，並限制同時存活數量）"""
        now = get_utc_timestamp()
        token_data = {
            "token": token,
            "created_at": now,
            "expires_at": now + (30 * 24 * 60 * 60),  # 30 天（秒）
            "revoked": False
        }

        oid = ObjectId(user_id)

        # 先清理已撤銷或已過期的 token（MongoDB 不允許同一欄位同時 $pull + $push）
        await self.collection.update_one(
            {"_id": oid},
            {"$pull": {"refresh_tokens": {
                "$or": [
                    {"revoked": True},
                    {"expires_at": {"$lt": now}}
                ]
            }}}
        )

        # push 新 token，按 created_at 排序後只保留最新的 N 筆
        # $slice: -N 表示保留陣列尾端（最新）的 N 個元素
        result = await self.collection.update_one(
            {"_id": oid},
            {"$push": {"refresh_tokens": {
                "$each": [token_data],
                "$sort": {"created_at": 1},
                "$slice": -self.MAX_REFRESH_TOKENS
            }}}
        )
        return result.modified_count > 0

    async def verify_refresh_token(self, user_id: str, token: str) -> bool:
        """驗證 Refresh Token 是否有效"""
        user = await self.collection.find_one({
            "_id": ObjectId(user_id),
            "refresh_tokens": {
                "$elemMatch": {
                    "token": token,
                    "revoked": False,
                    "expires_at": {"$gt": get_utc_timestamp()}
                }
            }
        })
        return user is not None

    async def revoke_refresh_token(self, user_id: str, token: str) -> bool:
        """撤銷 Refresh Token"""
        result = await self.collection.update_one(
            {
                "_id": ObjectId(user_id),
                "refresh_tokens.token": token
            },
            {"$set": {"refresh_tokens.$.revoked": True}}
        )
        return result.modified_count > 0

    async def update_subscription(self, user_id: str, subscription_data: Dict[str, Any]) -> bool:
        """更新用戶訂閱資料"""
        return await self.update(user_id, {"subscription": subscription_data})

    async def add_extra_quota(
        self, user_id: str, duration_minutes: float = 0, ai_summaries: int = 0
    ) -> bool:
        """累加額外額度（不重置，可跨月累計）"""
        inc: Dict[str, Any] = {}
        if duration_minutes:
            inc["extra_quota.duration_minutes"] = duration_minutes
        if ai_summaries:
            inc["extra_quota.ai_summaries"] = ai_summaries
        if not inc:
            return True
        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": inc, "$set": {"updated_at": get_utc_timestamp()}}
        )
        return result.modified_count > 0

    async def adjust_extra_quota_atomic(
        self, user_id: str, duration_minutes: float = 0, ai_summaries: int = 0
    ) -> Optional[Dict[str, Any]]:
        """原子調整額外額度，扣除時保證不會變負

        正數累加、負數扣除；負數時用 filter 條件確保餘額足夠。
        回傳更新後的 document（含 extra_quota），或 None 表示餘額不足。
        """
        inc: Dict[str, Any] = {}
        filter_conditions: Dict[str, Any] = {"_id": ObjectId(user_id)}

        if duration_minutes:
            inc["extra_quota.duration_minutes"] = duration_minutes
            if duration_minutes < 0:
                filter_conditions["extra_quota.duration_minutes"] = {
                    "$gte": abs(duration_minutes)
                }
        if ai_summaries:
            inc["extra_quota.ai_summaries"] = ai_summaries
            if ai_summaries < 0:
                filter_conditions["extra_quota.ai_summaries"] = {
                    "$gte": abs(ai_summaries)
                }

        if not inc:
            return await self.get_by_id(user_id)

        return await self.collection.find_one_and_update(
            filter_conditions,
            {"$inc": inc, "$set": {"updated_at": get_utc_timestamp()}},
            return_document=True
        )

    async def update_invoice_info(self, user_id: str, invoice_info: Dict[str, Any]) -> bool:
        """更新用戶發票資訊"""
        return await self.update(user_id, {"invoice_info": invoice_info})

    async def count(self, filters: Dict[str, Any] = None) -> int:
        """計算用戶數量"""
        if filters is None:
            filters = {}
        return await self.collection.count_documents(filters)

    async def find(
        self,
        filters: Dict[str, Any] = None,
        skip: int = 0,
        limit: int = 20,
        sort: List[tuple] = None
    ) -> List[Dict[str, Any]]:
        """查詢用戶列表"""
        if filters is None:
            filters = {}
        if sort is None:
            sort = [("created_at", -1)]

        cursor = self.collection.find(filters).skip(skip).limit(limit).sort(sort)
        return await cursor.to_list(length=limit)
