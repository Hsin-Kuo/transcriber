"""線上人數長期 rollup 資料存取層。

用途：把「當下線上人數」定時抽樣後，聚合成**每小時一桶**的長期時間序列，
供後台看「歷史活躍巔峰」與趨勢。與即時的 user_presence 分工：

- user_presence：只答「此刻誰在線」，TTL 120s、_id=user_id，天生封頂不累積。
- presence_rollup（本檔）：答「每個時段的在線巔峰」，每小時一筆、長期保留。

設計取捨：
- **每分鐘抽樣、每小時彙整**：抽樣頻率（60s）比桶寬（1h）細，桶內取 $max 才抓得到
  桶內尖峰。8,760 筆/年、每筆數十 bytes → <1MB/年，永久放也無壓力。
- **bucket 當 _id 的 pipeline upsert**：$max / $add 皆可交換，uvicorn --workers 2
  兩個 worker 打同一桶會收斂成一筆，不需分散式鎖（沿用本 codebase 唯一的併發防護
  慣例——見 presence_repo 用 user_id 去重）。
- **peak_at 用 $cond 只在刷新高時更新**：記下「該時段峰值發生的分鐘」，全表 max(peak)
  的那筆 peak_at 即歷史尖峰時間。
- **TTL 存 BSON Date**（踩雷紀錄同 presence_repo）：bucket_start 存 datetime，給長期
  保留上限用。3 年只是保險上限，實際體積永遠很小。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ...utils.logger import get_logger
from .presence_repo import PresenceRepository

log = get_logger(__name__)

# 背景抽樣間隔（秒）。比桶寬（1h）細很多，確保抓得到桶內尖峰。
PRESENCE_ROLLUP_INTERVAL_SECONDS = 60

# 長期保留上限（秒）。3 年只是防呆上限；每年 <1MB，通常不會真的觸及。
PRESENCE_ROLLUP_TTL_SECONDS = 3 * 365 * 24 * 3600


def _hour_floor(dt: datetime) -> datetime:
    """把 datetime 向下取整到整點（UTC）。"""
    return dt.replace(minute=0, second=0, microsecond=0)


def _iso(dt) -> str | None:
    """輸出明確帶 UTC 的 ISO 字串，避免前端把 naive datetime 當本地時間。"""
    if dt is None:
        return None
    if dt.tzinfo is None:  # motor 讀回預設是 naive UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class PresenceRollupRepository:
    """線上人數每小時 rollup 操作。"""

    def __init__(self, db):
        self.db = db
        self.collection = db.presence_rollup

    async def ensure_indexes(self):
        """確保索引存在（應用啟動時呼叫）。

        bucket_start 為 BSON Date，同時充當：
        - 範圍查詢索引（趨勢圖 / 峰值查詢）
        - 長期保留 TTL（超過 PRESENCE_ROLLUP_TTL_SECONDS 自動刪）
        """
        await self.collection.create_index(
            "bucket_start",
            expireAfterSeconds=PRESENCE_ROLLUP_TTL_SECONDS,
            name="bucket_start_ttl",
        )

    async def record_sample(self, count: int, now: datetime | None = None) -> None:
        """記錄一次抽樣到當前小時桶。呼叫端負責抽樣頻率（見 periodic_presence_rollup）。

        用 aggregation-pipeline upsert 一次維護「桶內峰值」與「峰值發生時間」：
        - peak_online = max(既有, count)
        - peak_at 只在 count 刷新高時更新為 now
        - sample_sum / samples 供算平均
        """
        now = now or datetime.now(timezone.utc)
        bucket_start = _hour_floor(now)
        bucket_id = bucket_start.strftime("%Y-%m-%dT%H:00Z")
        await self.collection.update_one(
            {"_id": bucket_id},
            [{"$set": {
                "peak_at": {"$cond": [
                    {"$gt": [count, {"$ifNull": ["$peak_online", 0]}]},
                    now,
                    {"$ifNull": ["$peak_at", now]},
                ]},
                "peak_online": {"$max": [{"$ifNull": ["$peak_online", 0]}, count]},
                "sample_sum": {"$add": [{"$ifNull": ["$sample_sum", 0]}, count]},
                "samples": {"$add": [{"$ifNull": ["$samples", 0]}, 1]},
                "bucket_start": {"$ifNull": ["$bucket_start", bucket_start]},
            }}],
            upsert=True,
        )

    def _shape(self, doc: dict) -> dict:
        """把 raw 文件整理成 API/前端友善格式。"""
        samples = doc.get("samples", 0) or 0
        sample_sum = doc.get("sample_sum", 0) or 0
        return {
            "bucket": doc["_id"],
            "bucket_start": _iso(doc.get("bucket_start")),
            "peak_online": doc.get("peak_online", 0),
            "peak_at": _iso(doc.get("peak_at")),
            "avg_online": round(sample_sum / samples, 1) if samples else 0,
            "samples": samples,
        }

    async def buckets_between(self, start: datetime, end: datetime) -> list[dict]:
        """回傳 [start, end] 區間內的小時桶，依時間正序。"""
        cursor = self.collection.find(
            {"bucket_start": {"$gte": start, "$lte": end}}
        ).sort("bucket_start", 1)
        return [self._shape(d) async for d in cursor]

    async def peak_between(self, start: datetime, end: datetime) -> dict | None:
        """回傳區間內峰值最高的那一桶（含峰值發生時間）；無資料回 None。"""
        cursor = self.collection.find(
            {"bucket_start": {"$gte": start, "$lte": end}}
        ).sort("peak_online", -1).limit(1)
        docs = [d async for d in cursor]
        return self._shape(docs[0]) if docs else None


async def periodic_presence_rollup(
    db, interval_seconds: int = PRESENCE_ROLLUP_INTERVAL_SECONDS
) -> None:
    """定期抽樣線上人數，寫入每小時 rollup 桶（背景任務，由 main.py startup 啟動）。

    抽樣本身只是對 user_presence 做一次 count（極輕）。兩個 worker 各跑一份無妨，
    bucket-idempotent upsert 會收斂成同一筆。
    """
    presence_repo = PresenceRepository(db)
    rollup_repo = PresenceRollupRepository(db)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            count = await presence_repo.count_online()
            await rollup_repo.record_sample(count)
        except Exception as e:
            log.error("presence_rollup.sample.failed", error=str(e), exc_info=True)
