"""建立預設管理員帳號

使用方式:
    python -m src.database.migrations.seed_admin
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from src.auth.password import hash_password
import os

# 從環境變數讀取配置
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")


async def create_admin():
    """建立預設管理員帳號"""
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    admin_email = "admin@example.com"
    admin_password = "Admin@123456"  # 首次登入後應立即修改

    # 檢查是否已存在
    existing = await db.users.find_one({"email": admin_email})
    if existing:
        print(f"⚠️  管理員已存在: {admin_email}")
        client.close()
        return

    # 建立管理員
    admin_user = {
        "email": admin_email,
        "password_hash": hash_password(admin_password),
        "role": "admin",
        "is_active": True,
        "quota": {
            "tier": "enterprise",
            "max_transcriptions": 999999,
            "max_duration_minutes": 999999,
            "max_concurrent_tasks": 10,
            "features": {
                "speaker_diarization": True,
                "punctuation": True,
                "batch_operations": True
            }
        },
        "usage": {
            "transcriptions": 0,
            "duration_minutes": 0,
            "last_reset": datetime.utcnow(),
            "total_transcriptions": 0,
            "total_duration_minutes": 0
        },
        "refresh_tokens": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = await db.users.insert_one(admin_user)

    print("✅ 已建立管理員帳號:")
    print(f"  - Email: {admin_email}")
    print(f"  - 密碼: {admin_password}")
    print(f"  - ID: {result.inserted_id}")
    print(f"\n⚠️  請立即登入並修改密碼!")

    # 建立索引
    await db.users.create_index("email", unique=True)
    print("✅ 已建立 Email 唯一索引")

    client.close()


if __name__ == "__main__":
    asyncio.run(create_admin())
