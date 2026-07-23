"""PresenceRollupRepository 測試。

需要連得到的 MongoDB（MONGODB_URL 或 localhost:27020），連不上整組 skip。

覆蓋重點：
- record_sample 以整點為桶、pipeline upsert 維護桶內峰值
- peak_online 取 $max；peak_at 只在刷新高時更新（同一人多裝置/多 worker 收斂）
- 多次抽樣彙整 samples / avg_online
- buckets_between 依時間正序、範圍過濾；peak_between 取區間最高桶
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from src.database.repositories.presence_rollup_repo import PresenceRollupRepository  # noqa: E402

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = "transcriber_test"


def _mongo_available() -> bool:
    if MongoClient is None:
        return False
    try:
        c = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=1000)
        c.admin.command("ping")
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}"
)


@pytest.fixture
async def repo():
    client = AsyncIOMotorClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    db = client[_TEST_DB]
    await db.presence_rollup.delete_many({})
    yield PresenceRollupRepository(db)
    await db.presence_rollup.delete_many({})
    client.close()


# 固定測試時間（避免依賴當前時鐘）
_T = datetime(2026, 7, 23, 14, 5, 0, tzinfo=timezone.utc)


async def test_sample_creates_hour_bucket(repo):
    await repo.record_sample(7, now=_T)
    doc = await repo.collection.find_one({"_id": "2026-07-23T14:00Z"})
    assert doc is not None
    assert doc["peak_online"] == 7
    assert doc["samples"] == 1
    # bucket_start 為整點
    assert doc["bucket_start"].replace(tzinfo=timezone.utc) == _T.replace(minute=0, second=0)


async def test_peak_takes_max_and_tracks_time(repo):
    """同小時多次抽樣：peak 取最大，peak_at 記在刷新高的那次。"""
    await repo.record_sample(3, now=_T)
    high = _T + timedelta(minutes=10)
    await repo.record_sample(9, now=high)          # 刷新高 → peak_at 更新
    await repo.record_sample(5, now=_T + timedelta(minutes=20))  # 較低 → 不動 peak_at

    doc = await repo.collection.find_one({"_id": "2026-07-23T14:00Z"})
    assert doc["peak_online"] == 9
    assert doc["samples"] == 3
    assert doc["peak_at"].replace(tzinfo=timezone.utc) == high


async def test_avg_online_from_samples(repo):
    for c in (2, 4, 6):
        await repo.record_sample(c, now=_T)
    shaped = await repo.buckets_between(
        _T - timedelta(hours=1), _T + timedelta(hours=1)
    )
    assert len(shaped) == 1
    assert shaped[0]["avg_online"] == 4.0  # (2+4+6)/3
    assert shaped[0]["peak_online"] == 6


async def test_buckets_between_orders_and_filters(repo):
    await repo.record_sample(1, now=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc))
    await repo.record_sample(2, now=datetime(2026, 7, 23, 13, 0, tzinfo=timezone.utc))
    await repo.record_sample(3, now=datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc))

    # 只取 13:00 起 → 排除 12:00 桶
    buckets = await repo.buckets_between(
        datetime(2026, 7, 23, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc),
    )
    assert [b["bucket"] for b in buckets] == ["2026-07-23T13:00Z", "2026-07-23T14:00Z"]


async def test_peak_between_returns_highest_bucket(repo):
    await repo.record_sample(4, now=datetime(2026, 7, 23, 12, 30, tzinfo=timezone.utc))
    await repo.record_sample(11, now=datetime(2026, 7, 23, 13, 30, tzinfo=timezone.utc))
    await repo.record_sample(7, now=datetime(2026, 7, 23, 14, 30, tzinfo=timezone.utc))

    peak = await repo.peak_between(
        datetime(2026, 7, 23, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc),
    )
    assert peak["peak_online"] == 11
    assert peak["bucket"] == "2026-07-23T13:00Z"
    assert peak["peak_at"] is not None


async def test_ensure_indexes_creates_ttl(repo):
    await repo.ensure_indexes()
    idx = await repo.collection.index_information()
    ttl = [v for v in idx.values() if v.get("expireAfterSeconds") is not None]
    assert ttl, "expected a TTL index on presence_rollup"
    assert any("bucket_start" in dict(v["key"]) for v in ttl)
