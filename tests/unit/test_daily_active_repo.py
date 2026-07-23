"""DailyActiveRepository 測試。

需要連得到的 MongoDB（MONGODB_URL 或 localhost:27020），連不上整組 skip。

覆蓋重點：
- mark_active 以 date:user_id 為 _id → 同一人一天多次只算一筆（去重）
- count_active 只算指定日；跨日不互相汙染
- rollup_day 用 $max 冪等（重跑/多 worker 重入不變）
- dau_between 依日期正序、範圍過濾
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

from src.database.repositories.daily_active_repo import DailyActiveRepository  # noqa: E402

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
    await db.daily_active.delete_many({})
    await db.dau_daily.delete_many({})
    yield DailyActiveRepository(db)
    await db.daily_active.delete_many({})
    await db.dau_daily.delete_many({})
    client.close()


_D1 = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
_D2 = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)


async def test_mark_dedups_same_user_same_day(repo):
    """同一 user 同一天多次 mark 只留一筆。"""
    for _ in range(5):
        await repo.mark_active("user-a", now=_D2)
    assert await repo.count_active("2026-07-23") == 1


async def test_count_is_per_day(repo):
    """跨日不互相計入。"""
    await repo.mark_active("user-a", now=_D1)
    await repo.mark_active("user-b", now=_D1)
    await repo.mark_active("user-a", now=_D2)  # 同一人隔天再活躍 → 各日各算
    assert await repo.count_active("2026-07-22") == 2
    assert await repo.count_active("2026-07-23") == 1


async def test_rollup_day_is_idempotent(repo):
    await repo.mark_active("user-a", now=_D2)
    await repo.mark_active("user-b", now=_D2)
    assert await repo.rollup_day("2026-07-23") == 2
    # 重跑不改變（$max 冪等）
    assert await repo.rollup_day("2026-07-23") == 2
    doc = await repo.rollup.find_one({"_id": "2026-07-23"})
    assert doc["dau"] == 2


async def test_rollup_max_never_regresses(repo):
    """先 rollup 到較高值，之後原始集若變少（例如 TTL 清掉），rollup 不倒退。"""
    for u in ("a", "b", "c"):
        await repo.mark_active(u, now=_D2)
    assert await repo.rollup_day("2026-07-23") == 3
    await repo.raw.delete_many({})  # 模擬 TTL 清空
    await repo.rollup_day("2026-07-23")  # 現在 count=0，但 $max 保住 3
    doc = await repo.rollup.find_one({"_id": "2026-07-23"})
    assert doc["dau"] == 3


async def test_dau_between_orders_and_filters(repo):
    await repo.mark_active("user-a", now=_D1)
    await repo.mark_active("user-a", now=_D2)
    await repo.rollup_day("2026-07-22")
    await repo.rollup_day("2026-07-23")

    series = await repo.dau_between(
        datetime(2026, 7, 22, tzinfo=timezone.utc),
        datetime(2026, 7, 23, 23, 59, tzinfo=timezone.utc),
    )
    assert [s["date"] for s in series] == ["2026-07-22", "2026-07-23"]
    assert all(s["dau"] == 1 for s in series)


async def test_ensure_indexes_creates_ttl_on_both(repo):
    await repo.ensure_indexes()
    for coll in (repo.raw, repo.rollup):
        idx = await coll.index_information()
        ttl = [v for v in idx.values() if v.get("expireAfterSeconds") is not None]
        assert ttl, f"expected a TTL index on {coll.name}"
        assert any("day_start" in dict(v["key"]) for v in ttl)
