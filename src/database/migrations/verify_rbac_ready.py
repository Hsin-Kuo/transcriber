"""RBAC Phase 3 部署前 readiness 檢查（唯讀）。

Phase 3 移除了「無 admin_role → superadmin」的相容後門。部署那版程式**之前**，
必須確認：
  1. 每個 role=="admin" 的帳號都有合法的 admin_role（否則部署後會被鎖在門外）。
  2. 系統至少還有 1 個 superadmin（否則沒人能再指派角色）。

用法:
    python -m src.database.migrations.verify_rbac_ready
    # ready → exit 0；not ready → exit 1（可接進 CI/部署腳本當 gate）

正確部署順序：先跑 backfill_admin_role → 跑本檢查（綠）→ 才 deploy Phase 3 程式。
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient
from src.auth.rbac import AdminRole
from src.utils.config_loader import get_parameter

MONGODB_URL = get_parameter(
    "/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017"
)
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")

VALID = [r.value for r in AdminRole]


async def check() -> bool:
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    total_admins = await db.users.count_documents({"role": "admin"})
    # 未 migrate 或值非法：role=admin 但 admin_role 不在白名單（含缺欄位）
    unmigrated = await db.users.count_documents(
        {"role": "admin", "admin_role": {"$nin": VALID}})
    superadmins = await db.users.count_documents(
        {"role": "admin", "admin_role": AdminRole.SUPERADMIN.value})

    print(f"admin 帳號總數：{total_admins}")
    print(f"superadmin 數：{superadmins}")
    print(f"未 migrate / 非法 admin_role 數：{unmigrated}")

    ready = True
    if unmigrated > 0:
        print(f"❌ 有 {unmigrated} 個 admin 沒有合法 admin_role——部署 Phase 3 會把他們鎖在門外。"
              f"請先跑 `python -m src.database.migrations.backfill_admin_role`。")
        ready = False
    if superadmins < 1:
        print("❌ 系統沒有任何 superadmin——部署後將無人能指派角色。")
        ready = False

    if ready:
        print("✅ READY：可安全部署 Phase 3。")
    client.close()
    return ready


if __name__ == "__main__":
    ok = asyncio.run(check())
    sys.exit(0 if ok else 1)
