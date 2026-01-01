"""用戶資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from bson import ObjectId


class UserRepository:
    """用戶資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.users

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

    async def delete(self, user_id: str) -> bool:
        """刪除用戶"""
        try:
            result = await self.collection.delete_one({"_id": ObjectId(user_id)})
            return result.deleted_count > 0
        except:
            return False

    async def update(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """更新用戶資料"""
        updates["updated_at"] = datetime.utcnow()
        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def update_quota(self, user_id: str, quota: Dict[str, Any]) -> bool:
        """更新用戶配額"""
        return await self.update(user_id, {"quota": quota})

    async def save_refresh_token(self, user_id: str, token: str) -> bool:
        """保存 Refresh Token"""
        from datetime import timedelta

        token_data = {
            "token": token,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=30),
            "revoked": False
        }

        result = await self.collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$push": {"refresh_tokens": token_data}}
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
                    "expires_at": {"$gt": datetime.utcnow()}
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
