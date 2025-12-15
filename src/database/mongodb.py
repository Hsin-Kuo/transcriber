"""MongoDB 連接管理"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

# 環境變數配置
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")


class MongoDB:
    """MongoDB 連接管理器"""
    client: Optional[AsyncIOMotorClient] = None

    @classmethod
    async def connect(cls):
        """啟動時連接 MongoDB"""
        try:
            cls.client = AsyncIOMotorClient(MONGODB_URL)
            # 測試連接
            await cls.client.admin.command('ping')
            print(f"✅ 已連接到 MongoDB: {MONGODB_DB_NAME}")
        except Exception as e:
            print(f"❌ MongoDB 連接失敗: {e}")
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
