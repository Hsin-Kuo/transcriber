"""Webhook 冪等性記錄。

第一個到達的 webhook 透過 `claim()` 拿到處理權；後續重發或重試會收到
already_processed=True，可直接回 200 略過。

Mongo `_id` 用 deterministic key：`<provider>:<natural_id>`。
靠 _id unique 約束達成「至多一次」處理語意，無需額外鎖或 transaction。
"""
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError


class ProcessedWebhookRepository:
    """跨 webhook provider 共用的冪等性記錄"""

    def __init__(self, db):
        self.db = db
        self.collection = db.processed_webhooks

    async def create_indexes(self):
        # _id 預設 unique，這裡可加 TTL 讓記錄保留例如 90 天即可
        await self.collection.create_index(
            "processed_at",
            expireAfterSeconds=90 * 24 * 3600,
        )

    @staticmethod
    def make_key(provider: str, natural_id: str) -> str:
        """組 deterministic _id（外部呼叫前先決定 natural_id 結構）"""
        return f"{provider}:{natural_id}"

    async def claim(
        self,
        provider: str,
        natural_id: str,
        metadata: Optional[dict] = None,
    ) -> bool:
        """嘗試取得此 webhook 的處理權。

        Returns:
            True: 第一次看到，呼叫者應繼續處理
            False: 已處理過，呼叫者應略過並回 200
        """
        key = self.make_key(provider, natural_id)
        try:
            await self.collection.insert_one({
                "_id": key,
                "provider": provider,
                "natural_id": natural_id,
                "processed_at": datetime.now(timezone.utc),
                "metadata": metadata or {},
            })
            return True
        except DuplicateKeyError:
            return False
