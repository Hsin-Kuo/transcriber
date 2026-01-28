"""
Audit Log Repository - 操作記錄管理
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase

from ...utils.time_utils import get_utc_timestamp


class AuditLogRepository:
    """操作記錄 Repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.audit_logs

    async def create_indexes(self):
        """建立索引"""
        await self.collection.create_index("user_id")
        await self.collection.create_index("log_type")
        await self.collection.create_index("timestamp")
        await self.collection.create_index([("user_id", 1), ("timestamp", -1)])
        await self.collection.create_index("resource_id")
        print("✅ 操作記錄索引已建立")

    async def log(
        self,
        user_id: Optional[str],
        log_type: str,
        action: str,
        ip_address: str,
        path: str,
        method: str,
        status_code: int,
        request_body: Optional[Dict[str, Any]] = None,
        response_message: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> str:
        """記錄操作日誌

        Args:
            user_id: 用戶 ID（可為 None，例如登入失敗）
            log_type: 日誌類型 (auth, task, transcription, tag, admin, file)
            action: 操作動作 (login, logout, create, update, delete, download, etc.)
            ip_address: IP 地址
            path: 請求路徑
            method: HTTP 方法 (GET, POST, PUT, DELETE)
            status_code: HTTP 狀態碼
            request_body: 請求內容（已清理敏感資訊）
            response_message: 回應訊息
            resource_id: 資源 ID（如 task_id）
            user_agent: User-Agent
            duration_ms: 請求處理時間（毫秒）

        Returns:
            日誌 ID
        """
        timestamp = get_utc_timestamp()

        log_entry = {
            "user_id": user_id,
            "log_type": log_type,
            "action": action,
            "ip_address": ip_address,
            "path": path,
            "method": method,
            "status_code": status_code,
            "timestamp": timestamp
        }

        # 可選欄位
        if request_body is not None:
            log_entry["request_body"] = request_body
        if response_message is not None:
            log_entry["response_message"] = response_message
        if resource_id is not None:
            log_entry["resource_id"] = resource_id
        if user_agent is not None:
            log_entry["user_agent"] = user_agent
        if duration_ms is not None:
            log_entry["duration_ms"] = duration_ms

        result = await self.collection.insert_one(log_entry)
        return str(result.inserted_id)

    async def get_by_user(
        self,
        user_id: str,
        limit: int = 100,
        skip: int = 0,
        log_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """獲取用戶的操作記錄

        Args:
            user_id: 用戶 ID
            limit: 限制數量
            skip: 跳過數量
            log_type: 過濾日誌類型

        Returns:
            操作記錄列表
        """
        query = {"user_id": user_id}
        if log_type:
            query["log_type"] = log_type

        cursor = self.collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_by_resource(
        self,
        resource_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """獲取特定資源的操作記錄

        Args:
            resource_id: 資源 ID
            limit: 限制數量

        Returns:
            操作記錄列表
        """
        cursor = self.collection.find({"resource_id": resource_id}).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_recent(
        self,
        limit: int = 100,
        skip: int = 0,
        log_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """獲取最近的操作記錄

        Args:
            limit: 限制數量
            skip: 跳過數量
            log_type: 過濾日誌類型

        Returns:
            操作記錄列表
        """
        query = {}
        if log_type:
            query["log_type"] = log_type

        cursor = self.collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_failed_operations(
        self,
        days: int = 7,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """獲取失敗的操作記錄

        Args:
            days: 最近幾天
            limit: 限制數量

        Returns:
            失敗操作記錄列表
        """
        days_ago_ts_ts = get_utc_timestamp() - (days * 24 * 60 * 60)

        query = {
            "timestamp": {"$gte": days_ago_ts_ts},
            "status_code": {"$gte": 400}
        }

        cursor = self.collection.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_statistics(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """獲取操作統計

        Args:
            days: 最近幾天

        Returns:
            統計資料
        """
        days_ago_ts_ts = get_utc_timestamp() - (days * 24 * 60 * 60)

        # 總操作數
        total = await self.collection.count_documents({"timestamp": {"$gte": days_ago_ts_ts}})

        # 按類型統計
        type_pipeline = [
            {"$match": {"timestamp": {"$gte": days_ago_ts}}},
            {"$group": {"_id": "$log_type", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        type_stats_cursor = self.collection.aggregate(type_pipeline)
        type_stats = await type_stats_cursor.to_list(length=None)

        # 按操作統計
        action_pipeline = [
            {"$match": {"timestamp": {"$gte": days_ago_ts}}},
            {"$group": {"_id": "$action", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        action_stats_cursor = self.collection.aggregate(action_pipeline)
        action_stats = await action_stats_cursor.to_list(length=None)

        # 失敗操作統計
        failed = await self.collection.count_documents({
            "timestamp": {"$gte": days_ago_ts},
            "status_code": {"$gte": 400}
        })

        return {
            "total_operations": total,
            "failed_operations": failed,
            "success_rate": round((total - failed) / total * 100, 2) if total > 0 else 0,
            "by_type": [{"type": s["_id"], "count": s["count"]} for s in type_stats],
            "top_actions": [{"action": s["_id"], "count": s["count"]} for s in action_stats]
        }
