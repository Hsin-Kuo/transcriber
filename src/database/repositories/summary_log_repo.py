"""Summary generation logs 資料存取層

每次 AI 摘要生成都會 append 一筆記錄（成功 / 失敗皆記），
與 summaries collection（task_id 一對一、會被 upsert 覆蓋）不同，
此 collection 保留完整歷史，供後台稽核每次的時間與 token 消耗。
"""
from typing import Optional, Dict, Any, List

from motor.motor_asyncio import AsyncIOMotorDatabase

from ...utils.time_utils import get_utc_timestamp
from src.utils.logger import get_logger

log = get_logger(__name__)


class SummaryLogRepository:
    """Summary generation logs 資料存取層（append-only）"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.summary_logs

    async def add(
        self,
        task_id: str,
        user_id: Optional[str],
        status: str,
        model: Optional[str] = None,
        language: Optional[str] = None,
        mode: Optional[str] = None,
        source_length: Optional[int] = None,
        token_usage: Optional[Dict[str, int]] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增一筆摘要生成記錄

        Args:
            task_id: 任務 ID
            user_id: 觸發者 user_id
            status: "completed" | "failed"
            model: 實際使用的 Gemini 模型
            language: 偵測到的語言代碼
            mode: 來源模式 (paragraph | subtitle)
            source_length: 原文字數
            token_usage: {total, prompt, completion}
            duration_ms: Gemini 生成耗時（毫秒）
            error: 失敗原因（status=failed 時）

        Returns:
            寫入的文件
        """
        doc = {
            "task_id": task_id,
            "user_id": user_id,
            "status": status,
            "model": model,
            "language": language,
            "mode": mode,
            "source_length": source_length,
            "token_usage": token_usage,
            "duration_ms": duration_ms,
            "error": error,
            "created_at": get_utc_timestamp(),
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def list_by_task(self, task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """取得某任務的所有摘要生成記錄（新到舊）

        Args:
            task_id: 任務 ID
            limit: 最多回傳筆數

        Returns:
            記錄列表（_id 已轉成字串）
        """
        cursor = (
            self.collection.find({"task_id": task_id})
            .sort("created_at", -1)
            .limit(limit)
        )
        logs = await cursor.to_list(length=limit)
        for entry in logs:
            entry["_id"] = str(entry["_id"])
        return logs

    async def create_indexes(self):
        """建立索引"""
        # 後台依 task_id 查詢、依時間排序
        await self.collection.create_index([("task_id", 1), ("created_at", -1)])
        log.info("summary_log.indexes.created")
