"""轉錄內容資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from ...utils.time_utils import get_utc_timestamp


class TranscriptionRepository:
    """轉錄內容資料存取層"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.transcriptions

    async def create(self, task_id: str, content: str) -> Dict[str, Any]:
        """建立轉錄內容

        Args:
            task_id: 任務 ID（作為 _id）
            content: 轉錄文字內容

        Returns:
            建立的文檔
        """
        now = get_utc_timestamp()
        doc = {
            "_id": task_id,
            "content": content,
            "text_length": len(content),
            "created_at": now,
            "updated_at": now
        }
        await self.collection.insert_one(doc)
        return doc

    async def get_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根據 task_id 獲取轉錄內容

        Args:
            task_id: 任務 ID

        Returns:
            轉錄文檔，不存在則返回 None
        """
        return await self.collection.find_one({"_id": task_id})

    async def update(self, task_id: str, content: str) -> bool:
        """更新轉錄內容

        Args:
            task_id: 任務 ID
            content: 新的轉錄內容

        Returns:
            是否更新成功
        """
        result = await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "content": content,
                    "text_length": len(content),
                    "updated_at": get_utc_timestamp()
                }
            }
        )
        return result.modified_count > 0

    async def delete(self, task_id: str) -> bool:
        """刪除轉錄內容

        Args:
            task_id: 任務 ID

        Returns:
            是否刪除成功
        """
        result = await self.collection.delete_one({"_id": task_id})
        return result.deleted_count > 0

    async def exists(self, task_id: str) -> bool:
        """檢查轉錄內容是否存在

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
        # 可根據需要添加其他索引
        await self.collection.create_index("created_at")
        print("✅ Transcription 索引已建立")
