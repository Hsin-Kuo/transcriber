"""線上使用者 presence 資料存取層。

用途：估算「當下有多少已登入使用者正在使用」。每個已驗證請求會（經節流後）
upsert 一筆 {_id: user_id, last_seen: <datetime>}，靠 MongoDB TTL 索引在閒置
一段時間後自動刪除。線上人數 = 未過期的文件數。

設計取捨：
- 只存 user_id + last_seen，不放任何 PII。
- 用 user_id 當 _id，天然去重（同一人多分頁/多裝置只算一個）。
- TTL 只對 BSON Date 生效（既有 audit_log 的踩雷紀錄），故 last_seen 存 datetime。
- count 另帶明確時間窗過濾，不依賴 TTL 掃描時機（TTL sweep 約每 60s 一次，
  文件實際可能多存活到 ~TTL+60s；用時間窗過濾讓讀數精準）。
"""
from datetime import datetime, timedelta, timezone

from ...utils.logger import get_logger

log = get_logger(__name__)

# 閒置超過此秒數即視為離線（也是 TTL 上限）
PRESENCE_TTL_SECONDS = 120


class PresenceRepository:
    """線上使用者 presence 操作。"""

    def __init__(self, db):
        self.db = db
        self.collection = db.user_presence

    async def ensure_indexes(self):
        """確保 TTL 索引存在（應用啟動時呼叫）。

        last_seen 為 BSON Date；MongoDB 在其超過 PRESENCE_TTL_SECONDS 後自動刪除。
        """
        await self.collection.create_index(
            "last_seen",
            expireAfterSeconds=PRESENCE_TTL_SECONDS,
            name="last_seen_ttl",
        )

    async def touch(self, user_id: str) -> None:
        """記錄某使用者「剛剛還活著」。呼叫端負責節流（見 dependencies.py）。"""
        await self.collection.update_one(
            {"_id": user_id},
            {"$set": {"last_seen": datetime.now(timezone.utc)}},
            upsert=True,
        )

    async def count_online(self, window_seconds: int = PRESENCE_TTL_SECONDS) -> int:
        """回傳最近 window_seconds 內有活動的使用者數。

        用明確時間窗過濾，讀數不受 TTL 掃描延遲影響（可能有已過期但尚未被
        TTL sweep 刪除的殘留文件）。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        return await self.collection.count_documents({"last_seen": {"$gte": cutoff}})
