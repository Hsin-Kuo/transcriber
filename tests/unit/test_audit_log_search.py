"""Audit log 多維篩選：_build_audit_filter（router helper）+ repo.search / distinct_facets。

filter builder 測試不需 Mongo（用 fake db）；repo 測試需 Mongo，連不上則 skip。
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers.admin import (  # noqa: E402
    _build_audit_filter,
    _AUDIT_MAX_SPAN_SECONDS,
    _AUDIT_DEFAULT_SPAN_SECONDS,
)
from src.utils.time_utils import get_utc_timestamp  # noqa: E402


# ---------- _build_audit_filter（不需 Mongo）----------

class _FakeUsers:
    def __init__(self, doc=None):
        self._doc = doc

    async def find_one(self, query):
        if self._doc and query.get("email") == self._doc.get("email"):
            return self._doc
        return None


class _FakeDB:
    def __init__(self, user_doc=None):
        self.users = _FakeUsers(user_doc)


async def test_default_window_is_7_days():
    f, meta = await _build_audit_filter(_FakeDB())
    span = meta["to"] - meta["from"]
    assert abs(span - _AUDIT_DEFAULT_SPAN_SECONDS) <= 2
    assert f["timestamp"]["$gte"] == meta["from"]
    assert f["timestamp"]["$lte"] == meta["to"]


async def test_span_capped_at_90_days():
    now = get_utc_timestamp()
    # 要求跨度 365 天 → 應被夾成 90 天
    f, meta = await _build_audit_filter(_FakeDB(), from_ts=now - 365 * 86400, to_ts=now)
    assert meta["to"] - meta["from"] == _AUDIT_MAX_SPAN_SECONDS


async def test_status_tristate_and_exact_code_precedence():
    f, _ = await _build_audit_filter(_FakeDB(), status="failed")
    assert f["status_code"] == {"$gte": 400}
    f, _ = await _build_audit_filter(_FakeDB(), status="success")
    assert f["status_code"] == {"$lt": 400}
    # 精確碼優先於三態
    f, _ = await _build_audit_filter(_FakeDB(), status="failed", status_code=403)
    assert f["status_code"] == 403


async def test_actor_as_user_id_passthrough():
    f, meta = await _build_audit_filter(_FakeDB(), actor="507f1f77bcf86cd799439011")
    assert f["user_id"] == "507f1f77bcf86cd799439011"
    assert "actor_resolved" not in meta


async def test_actor_email_resolved_to_user_id():
    doc = {"_id": "507f1f77bcf86cd799439011", "email": "alice@x.com"}
    f, meta = await _build_audit_filter(_FakeDB(doc), actor="alice@x.com")
    assert f["user_id"] == "507f1f77bcf86cd799439011"
    assert meta["actor_resolved"] == "507f1f77bcf86cd799439011"


async def test_actor_email_not_found_flags_meta():
    f, meta = await _build_audit_filter(_FakeDB(None), actor="ghost@x.com")
    assert meta.get("actor_not_found") is True
    assert "user_id" not in f  # 不退化成全表查


async def test_log_type_action_ip_combine():
    f, _ = await _build_audit_filter(
        _FakeDB(), log_type="admin", action="change_role", ip="203.0.113.7"
    )
    assert f["log_type"] == "admin"
    assert f["action"] == "change_role"
    assert f["ip_address"] == "203.0.113.7"


# ---------- repo.search / distinct_facets（需 Mongo）----------

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from src.database.repositories.audit_log_repo import AuditLogRepository  # noqa: E402

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


mongo = pytest.mark.skipif(not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}")


@pytest.fixture
async def repo():
    client = AsyncIOMotorClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    db = client[_TEST_DB]
    await db.audit_logs.delete_many({})
    r = AuditLogRepository(db)
    base = get_utc_timestamp()
    # 塞測試資料：3 筆成功 + 2 筆失敗，橫跨時間
    for i, (action, code) in enumerate([
        ("login", 200), ("change_role", 200), ("delete", 200),
        ("login", 401), ("delete", 403),
    ]):
        await db.audit_logs.insert_one({
            "user_id": "u1" if i % 2 == 0 else "u2",
            "log_type": "auth" if action == "login" else "admin",
            "action": action,
            "ip_address": "203.0.113.7",
            "status_code": code,
            "timestamp": base - i,
            "created_at": datetime.now(timezone.utc),
        })
    yield r
    await db.audit_logs.delete_many({})
    client.close()


@mongo
async def test_search_returns_page_and_total(repo):
    now = get_utc_timestamp()
    f = {"timestamp": {"$gte": now - 3600, "$lte": now + 10}}
    items, total = await repo.search(f, sort_desc=True, skip=0, limit=2)
    assert total == 5            # 符合 filter 的總數（非本頁筆數）
    assert len(items) == 2       # 本頁受 limit 限制
    # 預設 desc：timestamp 由大到小
    assert items[0]["timestamp"] >= items[1]["timestamp"]


@mongo
async def test_search_failed_filter(repo):
    now = get_utc_timestamp()
    f = {"timestamp": {"$gte": now - 3600, "$lte": now + 10}, "status_code": {"$gte": 400}}
    items, total = await repo.search(f, limit=50)
    assert total == 2
    assert all(it["status_code"] >= 400 for it in items)


@mongo
async def test_search_sort_asc(repo):
    now = get_utc_timestamp()
    f = {"timestamp": {"$gte": now - 3600, "$lte": now + 10}}
    items, _ = await repo.search(f, sort_desc=False, limit=50)
    assert items[0]["timestamp"] <= items[-1]["timestamp"]


@mongo
async def test_distinct_facets(repo):
    facets = await repo.distinct_facets()
    assert set(facets["actions"]) >= {"login", "change_role", "delete"}
    assert set(facets["log_types"]) >= {"auth", "admin"}
    assert facets["actions"] == sorted(facets["actions"])
