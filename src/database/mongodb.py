"""MongoDB 連接管理"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

from ..utils.config_loader import get_parameter

# 環境變數配置（AWS 從 SSM 讀取，本地從環境變數）
MONGODB_URL = get_parameter("/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")


class MongoDB:
    """MongoDB 連接管理器"""
    client: Optional[AsyncIOMotorClient] = None

    @classmethod
    async def connect(cls):
        """啟動時連接 MongoDB"""
        try:
            # 添加連接參數以提高可靠性
            # 注意：MongoDB Atlas 使用副本集，不能用 directConnection=True
            is_atlas = "mongodb.net" in MONGODB_URL or "mongodb+srv" in MONGODB_URL
            cls.client = AsyncIOMotorClient(
                MONGODB_URL,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                socketTimeoutMS=5000,
                **({"directConnection": True} if not is_atlas else {})
            )
            # 測試連接
            await cls.client.admin.command('ping')
            print(f"✅ 已連接到 MongoDB: {MONGODB_DB_NAME}", flush=True)
        except Exception as e:
            print(f"❌ MongoDB 連接失敗: {e}", flush=True)
            raise

    @classmethod
    async def close(cls):
        """關閉時斷開 MongoDB 連接"""
        if cls.client:
            cls.client.close()
            print("✅ MongoDB 連接已關閉")

    @classmethod
    def get_db(cls):
        """獲取資料庫實例"""
        if not cls.client:
            raise RuntimeError("MongoDB 未連接，請先調用 MongoDB.connect()")
        return cls.client[MONGODB_DB_NAME]


# 依賴注入函數
def get_database():
    """FastAPI 依賴注入：獲取資料庫實例"""
    return MongoDB.get_db()
