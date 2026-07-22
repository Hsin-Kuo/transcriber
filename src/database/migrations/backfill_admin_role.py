"""Backfill admin_role 給既有管理員（RBAC P0-1 Phase 0）。

把所有 role=="admin" 但尚未設定 admin_role 的帳號一律設成 superadmin，
確保 RBAC 導入當天行為完全不變（現有 admin 全開），之後再逐步指派較窄角色。

冪等：重跑只會處理仍缺 admin_role 的帳號，不會覆蓋已指派的角色。

使用方式:
    python -m src.database.migrations.backfill_admin_role
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

from motor.motor_asyncio import AsyncIOMotorClient
from src.auth.rbac import AdminRole
from src.utils.config_loader import get_parameter

MONGODB_URL = get_parameter(
    "/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017"
)
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")


async def backfill():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    query = {"role": "admin", "admin_role": {"$exists": False}}
    pending = await db.users.count_documents(query)
    if pending == 0:
        print("✅ 沒有需要 backfill 的管理員（admin_role 皆已設定）")
        client.close()
        return

    result = await db.users.update_many(
        query, {"$set": {"admin_role": AdminRole.SUPERADMIN.value}}
    )
    print(f"✅ 已將 {result.modified_count} 個管理員 backfill 成 admin_role={AdminRole.SUPERADMIN.value}")

    # 對照顯示目前各角色人數
    for role in AdminRole:
        n = await db.users.count_documents({"role": "admin", "admin_role": role.value})
        print(f"   - {role.value}: {n}")

    client.close()


if __name__ == "__main__":
    asyncio.run(backfill())
