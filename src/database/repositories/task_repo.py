"""任務資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from bson import ObjectId


class TaskRepository:
    """任務資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.tasks

    async def create(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立新任務"""
        result = await self.collection.insert_one(task_data)
        task_data["_id"] = result.inserted_id
        return task_data

    async def get_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根據 ID 獲取任務"""
        return await self.collection.find_one({"_id": task_id})

    async def get_by_id_and_user(self, task_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """根據 ID 和 user_id 獲取任務（權限檢查）"""
        return await self.collection.find_one({
            "_id": task_id,
            "user_id": user_id
        })

    async def update(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """更新任務資料"""
        updates["updated_at"] = datetime.utcnow()
        result = await self.collection.update_one(
            {"_id": task_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def delete(self, task_id: str, user_id: str) -> bool:
        """刪除任務（權限檢查）"""
        result = await self.collection.delete_one({
            "_id": task_id,
            "user_id": user_id
        })
        return result.deleted_count > 0

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        sort: List[tuple] = None
    ) -> List[Dict[str, Any]]:
        """查詢用戶的任務列表"""
        if sort is None:
            sort = [("created_at", -1)]

        filters = {"user_id": user_id}
        if status:
            filters["status"] = status

        cursor = self.collection.find(filters).skip(skip).limit(limit).sort(sort)
        return await cursor.to_list(length=limit)

    async def count_by_user(self, user_id: str, status: Optional[str] = None) -> int:
        """計算用戶的任務數量"""
        filters = {"user_id": user_id}
        if status:
            filters["status"] = status
        return await self.collection.count_documents(filters)

    async def find_active_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """查詢用戶進行中的任務"""
        cursor = self.collection.find({
            "user_id": user_id,
            "status": {"$in": ["pending", "processing"]}
        })
        return await cursor.to_list(length=100)

    async def get_user_total_duration(self, user_id: str, from_date: datetime = None) -> float:
        """計算用戶的總轉錄時長（秒）"""
        filters = {
            "user_id": user_id,
            "status": "completed",
            "audio_duration": {"$exists": True}
        }
        if from_date:
            filters["created_at"] = {"$gte": from_date}

        pipeline = [
            {"$match": filters},
            {
                "$group": {
                    "_id": None,
                    "total_duration": {"$sum": "$audio_duration"}
                }
            }
        ]

        result = await self.collection.aggregate(pipeline).to_list(1)
        if result:
            return result[0].get("total_duration", 0)
        return 0

    async def count_by_user_since(self, user_id: str, from_date: datetime) -> int:
        """計算用戶從某日期起的任務數量"""
        return await self.collection.count_documents({
            "user_id": user_id,
            "status": "completed",
            "created_at": {"$gte": from_date}
        })
