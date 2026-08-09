"""存量 card_token 加密 migration（金流體檢 P2-10）。

把 `users.subscription.card_token` 與 `orders.card_token` 兩個欄位裡仍是明文
（不以 `v1:` 開頭）的值，改成 AES-256-GCM 密文（`src/utils/card_token_cipher.py`）。

冪等：判斷依據是 `v1:` 前綴，已加密的值重跑不會再處理，可安全重跑。

⚠️ **執行順序前提**：必須先部署「已含 decrypt 明文相容」的程式碼（本次 P2-10
變更本身），才能跑這支 migration——否則 migrate 到一半，讀取端（renewal_service
的 decrypt）還沒上線，會拿到密文當明文用。`decrypt()` 的 v1/明文相容判斷正是為
了讓「新舊資料混存」的過渡期間讀取端能同時處理兩種形態。

使用方式:
    python -m src.database.migrations.encrypt_existing_card_tokens
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# 添加專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# 必須在 import config_loader 之前載入 .env（DEPLOY_ENV 在模組層級讀取）
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from src.utils.card_token_cipher import encrypt  # noqa: E402
from src.utils.config_loader import get_parameter  # noqa: E402

MONGODB_URL = get_parameter(
    "/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017"
)
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")

_PLAINTEXT_CARD_TOKEN_QUERY = {
    "$and": [
        {"card_token": {"$exists": True}},
        {"card_token": {"$nin": [None, ""]}},
        {"card_token": {"$not": {"$regex": "^v1:"}}},
    ]
}

_USER_PLAINTEXT_CARD_TOKEN_QUERY = {
    "$and": [
        {"subscription.card_token": {"$exists": True}},
        {"subscription.card_token": {"$nin": [None, ""]}},
        {"subscription.card_token": {"$not": {"$regex": "^v1:"}}},
    ]
}


async def _encrypt_users(db) -> int:
    cursor = db.users.find(_USER_PLAINTEXT_CARD_TOKEN_QUERY, {"_id": 1, "subscription.card_token": 1})
    processed = 0
    async for doc in cursor:
        token = doc.get("subscription", {}).get("card_token")
        if not token:
            continue
        await db.users.update_one(
            {"_id": doc["_id"]},
            {"$set": {"subscription.card_token": encrypt(str(token))}},
        )
        processed += 1
    return processed


async def _encrypt_orders(db) -> int:
    cursor = db.orders.find(_PLAINTEXT_CARD_TOKEN_QUERY, {"_id": 1, "card_token": 1})
    processed = 0
    async for doc in cursor:
        token = doc.get("card_token")
        if not token:
            continue
        await db.orders.update_one(
            {"_id": doc["_id"]},
            {"$set": {"card_token": encrypt(str(token))}},
        )
        processed += 1
    return processed


async def migrate():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    users_pending = await db.users.count_documents(_USER_PLAINTEXT_CARD_TOKEN_QUERY)
    orders_pending = await db.orders.count_documents(_PLAINTEXT_CARD_TOKEN_QUERY)
    print(f"待加密：users.subscription.card_token={users_pending} 筆、orders.card_token={orders_pending} 筆")

    if users_pending == 0 and orders_pending == 0:
        print("✅ 沒有需要加密的存量 card_token")
        client.close()
        return

    users_done = await _encrypt_users(db)
    orders_done = await _encrypt_orders(db)
    print(f"✅ 已加密 users.subscription.card_token {users_done} 筆、orders.card_token {orders_done} 筆")

    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
