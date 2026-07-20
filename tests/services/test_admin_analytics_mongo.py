"""AdminAnalytics 整合測試（需 MongoDB；連不上整組 skip）。

純函式（merge/derive）已在 test_admin_analytics.py 用 fake 資料覆蓋；這裡驗證
pipeline 本身（$group / $lookup / $dateToString 30 天窗）對真 Mongo 算得對，
並確認 full_report() 把 pipeline 結果正確餵進純函式組成回應。
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from src.services.admin_analytics import AdminAnalytics  # noqa: E402

_MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")
_TEST_DB = f"admin_analytics_test_{uuid.uuid4().hex[:8]}"


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


pytestmark = pytest.mark.skipif(not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}")


def _task(_id, user_id, status, *, total=None, duration=None, created=None):
    doc = {
        "_id": _id,
        "user": {"user_id": user_id},
        "status": status,
        "models": {"punctuation": "gemini", "transcription": "whisper-medium", "diarization": "pyannote"},
        "config": {"punct_provider": "gemini"},
        "timestamps": {"created_at": created or int(time.time())},
        "stats": {},
    }
    if total is not None:
        doc["stats"]["token_usage"] = {"total": total, "prompt": total * 6 // 10, "completion": total * 4 // 10}
    if duration is not None:
        doc["stats"]["duration_seconds"] = duration
    return doc


@pytest.fixture
async def seeded_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB]
    now = int(time.time())
    await db.tasks.insert_many([
        _task("A", "u1", "completed", total=100, duration=30, created=now),
        _task("B", "u1", "completed", total=50, duration=10, created=now),
        _task("C", "u2", "failed", created=now),
    ])
    # 摘要統計來源是 summary_logs（非 summaries）——見 D2。故意只 seed summary_logs：
    # 若統計誤讀 summaries，下列 top_users / daily 的 summary token 斷言會失敗。
    await db.summary_logs.insert_one({
        "task_id": "A", "user_id": "u1", "status": "completed", "model": "gemini-2.0",
        "token_usage": {"total": 20, "prompt": 12, "completion": 8}, "created_at": now,
    })
    await db.users.insert_many([
        {"_id": "u1", "is_active": True},
        {"_id": "u2", "is_active": False},
    ])
    try:
        yield db
    finally:
        await client.drop_database(_TEST_DB)
        client.close()


async def test_full_report_against_real_mongo(seeded_db):
    report = await AdminAnalytics(seeded_db).full_report()

    ov = report["overview"]
    assert ov["total_tasks"] == 3 and ov["completed_tasks"] == 2 and ov["failed_tasks"] == 1
    assert ov["success_rate"] == 66.67           # 2/3
    assert ov["total_users"] == 2 and ov["active_users"] == 1

    # full_report 不再回全期間 token_usage（成本統計移到 /admin/cost）
    assert "token_usage" not in report

    # summary_logs.user_id 直接歸戶：u1 的 summary token 20 併入 punct 150
    top = {u["user_id"]: u for u in report["top_users"]}
    assert top["u1"]["total_tokens"] == 170          # 150 punct + 20 summary
    assert report["top_users"][0]["user_id"] == "u1"  # 依 total_tokens 排序

    # performance：只計 completed 的 duration → (30+10)/2
    assert report["performance"]["avg_duration_seconds"] == 20.0

    # daily：補零後涵蓋完整日期窗（無資料日補 0）；有資料的僅今天那筆 3 tasks / 1 summary
    non_empty = [d for d in report["daily_stats"] if d["tasks_count"] > 0]
    assert len(non_empty) == 1
    assert non_empty[0]["tasks_count"] == 3
    assert non_empty[0]["total_tokens"] == 170
    # 其餘日期一律補 0
    assert all(d["total_tokens"] == 0 for d in report["daily_stats"] if d["date"] != non_empty[0]["date"])

    assert report["model_usage"]["transcription"][0]["model"] == "whisper-medium"
    # 摘要模型分布來自 summary_logs（seed 的 model=gemini-2.0）
    assert report["model_usage"]["summary"][0]["model"] == "gemini-2.0"
    assert report["punct_provider_usage"][0]["provider"] == "gemini"


@pytest.fixture
async def seeded_revenue_db():
    from bson import ObjectId
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    db = client[_TEST_DB + "_rev"]
    now = int(time.time())
    u1, u2, u3 = ObjectId(), ObjectId(), ObjectId()
    await db.users.insert_many([
        {"_id": u1, "email": "a@x.com",
         "subscription": {"status": "active", "tier": "basic", "billing_cycle": "monthly", "cancel_at_period_end": False}},
        {"_id": u2, "email": "b@x.com",
         "subscription": {"status": "active", "tier": "pro", "billing_cycle": "yearly", "cancel_at_period_end": False}},
        {"_id": u3, "email": "c@x.com",
         "subscription": {"status": "active", "tier": "basic", "billing_cycle": "monthly", "cancel_at_period_end": True}},
    ])
    await db.orders.insert_many([
        {"merchant_order_no": "O1", "status": "paid", "amount_twd": 300, "type": "subscription", "tier": "pro", "user_id": str(u1), "paid_at": now},
        {"merchant_order_no": "O2", "status": "paid", "amount_twd": 100, "type": "extra_quota", "user_id": str(u1), "paid_at": now},
        {"merchant_order_no": "O3", "status": "pending", "amount_twd": 999, "type": "subscription", "user_id": str(u2), "paid_at": now},
    ])
    try:
        yield db
    finally:
        await client.drop_database(_TEST_DB + "_rev")
        client.close()


async def test_revenue_against_real_mongo(seeded_revenue_db):
    rev = await AdminAnalytics(seeded_revenue_db).revenue()

    # subscriber_count 不依賴定價
    assert rev["subscriber_count"]["basic_monthly"] == 2  # u1 + u3
    assert rev["subscriber_count"]["pro_yearly"] == 1

    # 只計 paid 訂單（O3 pending 不算）
    assert rev["total_revenue"] == 400        # 300 + 100
    assert rev["extra_quota_revenue"] == 100
    assert isinstance(rev["mrr"], int) and rev["mrr"] >= 0

    # 近 6 月：本月一筆 400
    assert rev["monthly_revenue"][0]["amount"] == 400

    # 近期訂單 join email（O1/O2 都屬 u1）
    assert {o["order_no"] for o in rev["recent_orders"]} == {"O1", "O2"}
    assert all(o["user_email"] == "a@x.com" for o in rev["recent_orders"])

    # 流失：u3 cancel_at_period_end=True → pending_cancel 1
    assert rev["churn"]["pending_cancel"] == 1
