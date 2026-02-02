"""速率限制資料存取層"""
from typing import Optional, Dict, Any
from ...utils.time_utils import get_utc_timestamp


class RateLimitRepository:
    """速率限制資料庫操作

    使用 MongoDB 存儲速率限制記錄，支援多實例部署。
    記錄會自動過期清理（透過 MongoDB TTL 索引）。
    """

    def __init__(self, db):
        self.db = db
        self.collection = db.rate_limits

    async def ensure_indexes(self):
        """確保必要的索引存在（應用啟動時呼叫）"""
        # TTL 索引：自動刪除過期記錄
        await self.collection.create_index(
            "expires_at",
            expireAfterSeconds=0
        )
        # 複合索引：快速查詢
        await self.collection.create_index([
            ("type", 1),
            ("key", 1)
        ])

    async def get_request_count(
        self,
        limit_type: str,
        key: str,
        window_seconds: int
    ) -> int:
        """取得時間窗口內的請求次數

        Args:
            limit_type: 限制類型（如 'forgot_password_ip'）
            key: 限制的鍵值（如 IP 地址）
            window_seconds: 時間窗口（秒）

        Returns:
            請求次數
        """
        now = get_utc_timestamp()
        window_start = now - window_seconds

        count = await self.collection.count_documents({
            "type": limit_type,
            "key": key,
            "created_at": {"$gte": window_start}
        })
        return count

    async def record_request(
        self,
        limit_type: str,
        key: str,
        ttl_seconds: int = 3600
    ) -> None:
        """記錄一次請求

        Args:
            limit_type: 限制類型
            key: 限制的鍵值
            ttl_seconds: 記錄保留時間（秒），預設 1 小時
        """
        now = get_utc_timestamp()
        await self.collection.insert_one({
            "type": limit_type,
            "key": key,
            "created_at": now,
            "expires_at": now + ttl_seconds  # MongoDB TTL 會自動刪除
        })

    async def check_rate_limit(
        self,
        limit_type: str,
        key: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        """檢查是否超過速率限制

        Args:
            limit_type: 限制類型
            key: 限制的鍵值
            max_requests: 最大請求次數
            window_seconds: 時間窗口（秒）

        Returns:
            (是否允許, 剩餘次數)
        """
        count = await self.get_request_count(limit_type, key, window_seconds)
        remaining = max(0, max_requests - count)
        allowed = count < max_requests
        return allowed, remaining

    async def check_cooldown(
        self,
        last_request_timestamp: Optional[int],
        cooldown_seconds: int
    ) -> tuple[bool, int]:
        """檢查冷卻時間

        Args:
            last_request_timestamp: 上次請求時間戳
            cooldown_seconds: 冷卻時間（秒）

        Returns:
            (是否允許, 剩餘秒數)
        """
        if last_request_timestamp is None:
            return True, 0

        # 處理可能的 datetime 格式
        if hasattr(last_request_timestamp, 'timestamp'):
            last_request_timestamp = int(last_request_timestamp.timestamp())

        now = get_utc_timestamp()
        elapsed = now - last_request_timestamp
        remaining = max(0, cooldown_seconds - elapsed)
        allowed = elapsed >= cooldown_seconds

        return allowed, remaining
