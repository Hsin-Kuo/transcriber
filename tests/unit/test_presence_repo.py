"""PresenceRepository 測試。

需要連得到的 MongoDB（MONGODB_URL 或 localhost:27020），連不上整組 skip。

覆蓋重點：
- touch 以 user_id 為 _id → 同一人多次/多裝置只算一筆（去重）
- count_online 用時間窗過濾，排除超過 window 的閒置使用者（不依賴 TTL 掃描時機）
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

from src.database.repositories.presence_repo import PresenceRepository  # noqa: E402

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
    await db.user_presence.delete_many({})
    yield PresenceRepository(db)
    await db.user_presence.delete_many({})
    client.close()


async def test_touch_dedups_same_user(repo):
    """同一 user 多次 touch（多分頁/多裝置）只留一筆，計數為 1。"""
    for _ in range(5):
        await repo.touch("user-a")
    assert await repo.count_online() == 1


async def test_count_counts_distinct_users(repo):
    await repo.touch("user-a")
    await repo.touch("user-b")
    await repo.touch("user-c")
    assert await repo.count_online() == 3


async def test_count_window_excludes_idle(repo):
    """last_seen 早於時間窗的使用者不計入（不靠 TTL 掃描）。"""
    await repo.touch("fresh-user")
    # 手動塞一筆 5 分鐘前的紀錄，模擬尚未被 TTL sweep 清掉的殘留
    await repo.collection.update_one(
        {"_id": "stale-user"},
        {"$set": {"last_seen": datetime.now(timezone.utc) - timedelta(minutes=5)}},
        upsert=True,
    )
    # 預設窗（120s）只算 fresh-user
    assert await repo.count_online() == 1
    # 放寬到 10 分鐘窗則兩者都算
    assert await repo.count_online(window_seconds=600) == 2


async def test_ensure_indexes_creates_ttl(repo):
    await repo.ensure_indexes()
    idx = await repo.collection.index_information()
    ttl = [v for v in idx.values() if v.get("expireAfterSeconds") is not None]
    assert ttl, "expected a TTL index on user_presence"
    assert any("last_seen" in dict(v["key"]) for v in ttl)
