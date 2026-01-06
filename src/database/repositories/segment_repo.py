"""Segments 資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase


class SegmentRepository:
    """Segments 資料存取層"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.segments

    async def create(self, task_id: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """建立 segments

        Args:
            task_id: 任務 ID（作為 _id）
            segments: Segments 陣列

        Returns:
            建立的文檔
        """
        now = datetime.utcnow()
        doc = {
            "_id": task_id,
            "segments": segments,
            "segment_count": len(segments),
            "created_at": now,
            "updated_at": now
        }
        await self.collection.insert_one(doc)
        return doc

    async def get_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根據 task_id 獲取 segments

        Args:
            task_id: 任務 ID

        Returns:
            Segments 文檔，不存在則返回 None
        """
        return await self.collection.find_one({"_id": task_id})

    async def update(self, task_id: str, segments: List[Dict[str, Any]]) -> bool:
        """更新 segments

        Args:
            task_id: 任務 ID
            segments: 新的 segments 陣列

        Returns:
            是否更新成功
        """
        result = await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "segments": segments,
                    "segment_count": len(segments),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        return result.modified_count > 0

    async def delete(self, task_id: str) -> bool:
        """刪除 segments

        Args:
            task_id: 任務 ID

        Returns:
            是否刪除成功
        """
        result = await self.collection.delete_one({"_id": task_id})
        return result.deleted_count > 0

    async def exists(self, task_id: str) -> bool:
        """檢查 segments 是否存在

        Args:
            task_id: 任務 ID

        Returns:
            是否存在
        """
        count = await self.collection.count_documents({"_id": task_id}, limit=1)
        return count > 0

    async def create_indexes(self):
        """建立索引"""
        # _id 已經是主鍵,自動有唯一索引
        await self.collection.create_index("created_at")
        print("✅ Segments 索引已建立")
