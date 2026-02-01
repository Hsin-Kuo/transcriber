"""Summaries 資料存取層"""
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from ...utils.time_utils import get_utc_timestamp


class SummaryRepository:
    """Summaries 資料存取層"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.summaries

    async def create(
        self,
        task_id: str,
        content: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """建立摘要

        Args:
            task_id: 任務 ID（作為 _id）
            content: 摘要內容 (highlights, summary, keywords)
            metadata: 元數據 (model, language, source_length)

        Returns:
            建立的文檔
        """
        now = get_utc_timestamp()
        doc = {
            "_id": task_id,
            "content": content,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now
        }
        await self.collection.insert_one(doc)
        return doc

    async def get_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根據 task_id 獲取摘要

        Args:
            task_id: 任務 ID

        Returns:
            摘要文檔，不存在則返回 None
        """
        return await self.collection.find_one({"_id": task_id})

    async def update(
        self,
        task_id: str,
        content: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> bool:
        """更新摘要

        Args:
            task_id: 任務 ID
            content: 新的摘要內容
            metadata: 新的元數據

        Returns:
            是否更新成功
        """
        result = await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "content": content,
                    "metadata": metadata,
                    "updated_at": get_utc_timestamp()
                }
            }
        )
        return result.modified_count > 0

    async def upsert(
        self,
        task_id: str,
        content: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """建立或更新摘要

        Args:
            task_id: 任務 ID
            content: 摘要內容
            metadata: 元數據

        Returns:
            更新後的文檔
        """
        now = get_utc_timestamp()
        result = await self.collection.find_one_and_update(
            {"_id": task_id},
            {
                "$set": {
                    "content": content,
                    "metadata": metadata,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True,
            return_document=True
        )
        return result

    async def delete(self, task_id: str) -> bool:
        """刪除摘要

        Args:
            task_id: 任務 ID

        Returns:
            是否刪除成功
        """
        result = await self.collection.delete_one({"_id": task_id})
        return result.deleted_count > 0

    async def exists(self, task_id: str) -> bool:
        """檢查摘要是否存在

        Args:
            task_id: 任務 ID

        Returns:
            是否存在
        """
        count = await self.collection.count_documents({"_id": task_id}, limit=1)
        return count > 0

    async def create_indexes(self):
        """建立索引"""
        # _id 已經是主鍵，自動有唯一索引
        await self.collection.create_index("created_at")
        print("✅ Summaries 索引已建立")
