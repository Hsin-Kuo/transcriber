#!/usr/bin/env python3
"""Level 1 本地模擬：排程降級 webhook → settle → DB 端到端驗證。

不接藍新：用 .env 的 NEWEBPAY_HASH_KEY/IV 自己加密假 Notify，
以 httpx ASGITransport in-process 打真實端點 /subscriptions/notify/period，
跑過 form 解析 → decrypt → is_first 判定 → processed_webhooks 冪等 → settle →
真 Mongo repo。驗「我們可控的邏輯」；藍新真實 Notify 序列仍須 sandbox（Level 2）。

前置：
  - 本地 Mongo 起著（single-node replica set；見 CLAUDE.md）
  - .env 有 NEWEBPAY_HASH_KEY / NEWEBPAY_HASH_IV / NEWEBPAY_MERCHANT_ID、MONGODB_URL
執行：
  python scripts/sim_downgrade_webhook.py

會建立/刪除自己的測試資料（email=sim-downgrade@example.test、order 前綴 SIMDWN）。
network（terminate_period_contract）已 stub，不會真的打藍新。
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from src.database.mongodb import get_database, MONGODB_URL, MONGODB_DB_NAME  # noqa: E402
from src.routers import subscriptions  # noqa: E402
from src.utils.newebpay_service import get_newebpay_service  # noqa: E402
from src.models.quota import build_quota_from_tier  # noqa: E402
from src.utils.time_utils import get_utc_timestamp  # noqa: E402

# ── 顏色 / 記分 ──────────────────────────────────────────────────────────────
G, R, Y, C, X = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m"
_score = {"pass": 0, "fail": 0, "warn": 0}


def check(name, cond, warn=False):
    if cond:
        print(f"  {G}✓ PASS{X} {name}")
        _score["pass"] += 1
    elif warn:
        print(f"  {Y}⚠ WARN{X} {name}")
        _score["warn"] += 1
    else:
        print(f"  {R}✗ FAIL{X} {name}")
        _score["fail"] += 1


EMAIL = "sim-downgrade@example.test"
svc = get_newebpay_service()


def encrypt_notify(result: dict, status="SUCCESS", message="OK") -> dict:
    """把 Result dict 包成藍新加密 Notify 的 POST body（{"Period": <hex>}）。"""
    result = {"MerchantID": svc.merchant_id, **result}  # decrypt 會驗 MerchantID
    payload = {"Status": status, "Message": message, "Result": result}
    return {"Period": svc._aes_encrypt(json.dumps(payload))}


def result_contract_created(order_no, period_no, trade_no):
    """建立完成格式：有 AuthTimes、無 AlreadyTimes → is_first_payment=True。"""
    return {"MerchantOrderNo": order_no, "PeriodNo": period_no,
            "TradeNo": trade_no, "AuthTimes": 99}


def result_npa(order_no, period_no, trade_no, already_times):
    """每期授權 NPA-N050 格式：有 AlreadyTimes。"""
    return {"MerchantOrderNo": order_no, "PeriodNo": period_no,
            "TradeNo": trade_no, "AlreadyTimes": already_times, "TotalTimes": 99}


async def main():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[MONGODB_DB_NAME]

    # settle 內部會呼叫藍新 terminate_period_contract（真網路）→ stub 成 no-op
    async def _noop_terminate(*a, **k):
        return (True, "OK (sim, no network)")
    svc.terminate_period_contract = _noop_terminate

    # 最小 app：只掛 subscriptions router，get_database 指到本地 db
    app = FastAPI()
    app.include_router(subscriptions.router)
    app.dependency_overrides[get_database] = lambda: db

    users, orders, webhooks = db.users, db.orders, db.processed_webhooks

    async def cleanup():
        await users.delete_many({"email": EMAIL})
        await orders.delete_many({"merchant_order_no": {"$regex": "^SIMDWN"}})
        await webhooks.delete_many({"_id": {"$regex": ":SIMDWN|SIMDWN"}})
        # processed_webhooks _id = provider:natural_id = "newebpay-period:SIMDWN...:..."
        await webhooks.delete_many({"_id": {"$regex": "SIMDWN"}})

    async def seed_pro_user():
        """建一個 active Pro 使用者，回傳 user_id(str)。"""
        await users.delete_many({"email": EMAIL})
        now = get_utc_timestamp()
        uid = ObjectId()
        await users.insert_one({
            "_id": uid,
            "email": EMAIL,
            "quota": build_quota_from_tier("pro"),
            "subscription": {
                "status": "active", "tier": "pro", "billing_cycle": "monthly",
                "current_period_start": now - 10 * 86400,
                "current_period_end": now + 20 * 86400,
                "cancel_at_period_end": False, "pending_plan_change": {
                    "tier": "basic", "billing_cycle": "monthly",
                    "order_no": "PLACEHOLDER", "scheduled_date": None,
                },
                "payment_provider": "newebpay",
                "active_order_no": "SIMPRO0", "period_no": "P0",
                "created_at": now - 40 * 86400, "updated_at": now,
            },
        })
        return str(uid)

    async def seed_downgrade_order(order_no, user_id, scheduled_date):
        await orders.delete_many({"merchant_order_no": order_no})
        now = get_utc_timestamp()
        await orders.insert_one({
            "merchant_order_no": order_no, "user_id": user_id,
            "type": "downgrade_subscription", "tier": "basic",
            "billing_cycle": "monthly", "amount_twd": 99, "status": "pending",
            "period_no": None, "prev_order_no": "SIMPRO0", "prev_period_no": "P0",
            "scheduled_date": scheduled_date,
            "created_at": now, "updated_at": now,
            "expires_at": now + 40 * 86400,
        })

    async def post_notify(ac, body):
        return await ac.post("/subscriptions/notify/period", data=body)

    async def sub(user_id):
        return (await users.find_one({"_id": ObjectId(user_id)}))["subscription"]

    async def quota_tier(user_id):
        return (await users.find_one({"_id": ObjectId(user_id)}))["quota"]["tier"]

    async def order_status(order_no):
        return (await orders.find_one({"merchant_order_no": order_no}))["status"]

    future = (datetime.utcnow() + timedelta(days=20)).strftime("%Y/%m/%d")
    past = (datetime.utcnow() - timedelta(days=1)).strftime("%Y/%m/%d")

    await cleanup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://sim") as ac:

        # ── S1：建約通知在首扣日之前 → 應延後，不生效 ──
        print(f"\n{C}S1  建約通知（首扣日在未來）→ 期望延後 SCHEDULED{X}")
        uid = await seed_pro_user()
        ono = "SIMDWN_S1"
        await seed_downgrade_order(ono, uid, future)
        await post_notify(ac, encrypt_notify(result_contract_created(ono, "P9", "T1")))
        s = await sub(uid)
        check("tier 仍為 pro（未降）", s["tier"] == "pro")
        check("quota 仍為 pro", await quota_tier(uid) == "pro")
        check("pending_plan_change 保留", s.get("pending_plan_change") is not None)
        check("order 仍 pending（未設 paid）", await order_status(ono) == "pending")
        claimed = await webhooks.find_one({"_id": f"newebpay-period:{ono}:init:T1"})
        check("processed_webhooks 記到 :init:<TradeNo>", claimed is not None)

        # ── S2：期末首扣（NPA 格式，AlreadyTimes=1）→ 應生效 ──
        print(f"\n{C}S2  期末首扣（NPA 格式 AlreadyTimes=1）→ 期望降級 ACTIVATED{X}")
        uid = await seed_pro_user()
        ono = "SIMDWN_S2"
        await seed_downgrade_order(ono, uid, past)
        await post_notify(ac, encrypt_notify(result_npa(ono, "P9", "T2", 1)))
        s = await sub(uid)
        check("tier 降為 basic", s["tier"] == "basic")
        check("quota 降為 basic", await quota_tier(uid) == "basic")
        check("pending_plan_change 清空", s.get("pending_plan_change") is None)
        check("order 標記 paid", await order_status(ono) == "paid")

        # ── S3：期末首扣（建約格式，無 AlreadyTimes）→ 日期 gate 仍應生效 ──
        print(f"\n{C}S3  期末首扣（建約格式，無 AlreadyTimes）→ 日期 gate 期望仍降級{X}")
        uid = await seed_pro_user()
        ono = "SIMDWN_S3"
        await seed_downgrade_order(ono, uid, past)
        await post_notify(ac, encrypt_notify(result_contract_created(ono, "P9", "T3")))
        check("tier 降為 basic（證明判別不依賴欄位格式）", (await sub(uid))["tier"] == "basic")
        check("order 標記 paid", await order_status(ono) == "paid")

        # ── S4：natural_id 防禦 —— 期末若也是建約格式，靠 TradeNo 區分仍能生效 ──
        print(f"\n{C}S4  natural_id 防禦：建約(:init:T4a) 佔位後，期末建約格式(不同 TradeNo)應生效{X}")
        uid = await seed_pro_user()
        ono = "SIMDWN_S4"
        await seed_downgrade_order(ono, uid, future)                 # 首扣日在未來
        await post_notify(ac, encrypt_notify(result_contract_created(ono, "P9", "T4a")))  # 建約→defer
        check("step1 建約後仍 pro（延後）", (await sub(uid))["tier"] == "pro")
        await orders.update_one({"merchant_order_no": ono}, {"$set": {"scheduled_date": past}})  # 模擬時間到期末
        await post_notify(ac, encrypt_notify(result_contract_created(ono, "P9", "T4b")))  # 期末建約格式(不同 TradeNo)
        check("期末建約格式(不同 TradeNo) → 降級生效（natural_id 併入 TradeNo，不再碰撞）",
              (await sub(uid))["tier"] == "basic")
        check("order 標記 paid", await order_status(ono) == "paid")
        # 重送「同一封」（同 TradeNo T4b）→ 仍應被冪等去重、不重複套用
        await post_notify(ac, encrypt_notify(result_contract_created(ono, "P9", "T4b")))
        check("重送同一封(同 TradeNo)被去重，狀態不變", await order_status(ono) == "paid")

        # ── S5：立即降級（scheduled_date=None）→ 即時生效 ──
        print(f"\n{C}S5  立即降級（scheduled_date=None）→ 期望即時 ACTIVATED{X}")
        uid = await seed_pro_user()
        ono = "SIMDWN_S5"
        await seed_downgrade_order(ono, uid, None)
        await post_notify(ac, encrypt_notify(result_contract_created(ono, "P9", "T5")))
        check("tier 立即降為 basic", (await sub(uid))["tier"] == "basic")

    await cleanup()
    client.close()

    print(f"\n{C}── 結果 ──{X}")
    print(f"  {G}PASS {_score['pass']}{X}   {Y}WARN {_score['warn']}{X}   {R}FAIL {_score['fail']}{X}")
    if _score["fail"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
