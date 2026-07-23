"""日活躍使用者（DAU）資料存取層。

回答「每天有多少不同使用者登入過」——與 presence/presence_rollup 的「同時在線
併發數」是**不同指標**（去重計數 vs 併發），故獨立成兩個 collection：

- daily_active（原始去重集）：_id = "YYYY-MM-DD:user_id"，天然去重。只為算最近幾天
  的 DAU，靠 TTL（DAILY_ACTIVE_TTL_SECONDS）自動清、**永不累積**（封頂 ≈ DAU × 天數）。
- dau_daily（長期 rollup）：_id = "YYYY-MM-DD"，每天一筆 {dau}，長期保留（365 筆/年，
  極小）。由背景任務每小時把 daily_active 的當日/昨日去重數 $max 進來。

設計取捨：
- 去重必須有「集合」語意，無法從併發抽樣推導 → 必須存 per-(user, day) 標記。
- 寫入來源是 auth 被動路徑（dependencies._record_presence），用 per-worker 每日
  guard 壓到「每人每天每 worker 一次」，成本極低。
- rollup 用 $max：單日 DAU 隨時間單調成長，重算/多 worker 重入都收斂，不需鎖。
- TTL 一律存 BSON Date（踩雷紀錄同 presence_repo）：day_start 存 datetime。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from ...utils.logger import get_logger

log = get_logger(__name__)

# 原始去重集保留天數（只需算得出「今天/昨天」DAU，3 天很寬裕）
DAILY_ACTIVE_TTL_SECONDS = 3 * 24 * 3600
# 長期 DAU rollup 保留上限（3 年防呆；每年 <0.1MB）
DAU_ROLLUP_TTL_SECONDS = 3 * 365 * 24 * 3600
# 背景 rollup 間隔（每小時把當日 DAU 刷進 rollup、順便定案昨日）
DAU_ROLLUP_INTERVAL_SECONDS = 3600


def _date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _day_floor(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_day(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # motor 讀回預設 naive UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class DailyActiveRepository:
    """DAU 去重與長期 rollup 操作。"""

    def __init__(self, db):
        self.db = db
        self.raw = db.daily_active     # _id "YYYY-MM-DD:user_id"，TTL 3 天
        self.rollup = db.dau_daily     # _id "YYYY-MM-DD"，長期保留

    async def ensure_indexes(self):
        """建立兩個 collection 的 TTL 索引（day_start 兼作範圍查詢索引）。"""
        await self.raw.create_index(
            "day_start",
            expireAfterSeconds=DAILY_ACTIVE_TTL_SECONDS,
            name="day_start_ttl",
        )
        await self.rollup.create_index(
            "day_start",
            expireAfterSeconds=DAU_ROLLUP_TTL_SECONDS,
            name="day_start_ttl",
        )

    async def mark_active(self, user_id: str, now: datetime | None = None) -> None:
        """標記某使用者今天活躍過。呼叫端負責每日 guard（見 dependencies.py）。

        _id = "YYYY-MM-DD:user_id" 天然去重：同一人一天多次只留一筆。
        """
        now = now or datetime.now(timezone.utc)
        date_str = _date_str(now)
        day_start = _day_floor(now)
        await self.raw.update_one(
            {"_id": f"{date_str}:{user_id}"},
            {"$setOnInsert": {"date": date_str, "day_start": day_start}},
            upsert=True,
        )

    async def count_active(self, date_str: str) -> int:
        """某天的去重活躍數（即時查原始集；用 day_start 等值走索引）。"""
        return await self.raw.count_documents({"day_start": _parse_day(date_str)})

    async def rollup_day(self, date_str: str) -> int:
        """把某天的去重 DAU 定案進長期 rollup（$max 冪等、多 worker 安全）。回傳該 DAU。"""
        day_start = _parse_day(date_str)
        dau = await self.raw.count_documents({"day_start": day_start})
        await self.rollup.update_one(
            {"_id": date_str},
            {"$max": {"dau": dau},
             "$setOnInsert": {"date": date_str, "day_start": day_start}},
            upsert=True,
        )
        return dau

    async def dau_between(self, start: datetime, end: datetime) -> list[dict]:
        """回傳 [start, end] 區間內的每日 DAU（依日期正序）。"""
        cursor = self.rollup.find(
            {"day_start": {"$gte": _day_floor(start), "$lte": _day_floor(end)}}
        ).sort("day_start", 1)
        return [
            {"date": d["_id"], "day_start": _iso(d.get("day_start")), "dau": d.get("dau", 0)}
            async for d in cursor
        ]


async def periodic_dau_rollup(
    db, interval_seconds: int = DAU_ROLLUP_INTERVAL_SECONDS
) -> None:
    """定期把 daily_active 的當日/昨日去重數 $max 進 dau_daily（背景任務）。

    每次刷新「今天」（DAU 當日單調成長）並重算「昨天」以定案；因原始集 TTL 3 天，
    只要每小時跑一次，昨日一定在被 TTL 清掉前就已定案。
    """
    repo = DailyActiveRepository(db)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            now = datetime.now(timezone.utc)
            yesterday = _date_str(now - timedelta(days=1))
            today = _date_str(now)
            for d in (yesterday, today):
                await repo.rollup_day(d)
        except Exception as e:
            log.error("dau_rollup.failed", error=str(e), exc_info=True)
