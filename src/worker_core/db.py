"""
Worker 用 MongoDB 同步連線（pymongo）

Web Server 使用 Motor（非同步），Worker 執行在背景執行緒中，
因此使用同步的 pymongo 客戶端，避免 event loop 衝突。
"""

from typing import Optional
from pymongo import MongoClient
from src.utils.time_utils import get_utc_timestamp
from src.worker_core.config import MONGODB_URL, MONGODB_DB_NAME, MONGODB_POOL_SIZE, MONGODB_TIMEOUT_MS

_mongo_client: Optional[MongoClient] = None


def get_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(
            MONGODB_URL,
            serverSelectionTimeoutMS=MONGODB_TIMEOUT_MS,
            maxPoolSize=MONGODB_POOL_SIZE,
        )
    return _mongo_client[MONGODB_DB_NAME]


def update_task(db, task_id: str, updates: dict, unset_fields=None) -> None:
    """更新 task document。

    Args:
        updates: $set 內容
        unset_fields: 要 $unset 的欄位名稱列表（例如完成時清掉 SERVER_RESTART 殘留的 error）
    """
    updates["updated_at"] = get_utc_timestamp()
    op = {"$set": updates}
    if unset_fields:
        op["$unset"] = {f: "" for f in unset_fields}
    db.tasks.update_one({"_id": task_id}, op)
