"""MongoDB 連接管理"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

from ..utils.config_loader import get_parameter
from src.utils.logger import get_logger

log = get_logger(__name__)

# 環境變數配置（AWS 從 SSM 讀取，本地從環境變數）
MONGODB_URL = get_parameter("/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")

# 不安全 TLS 參數黑名單（生產環境若出現代表 MITM 風險被開啟）
_INSECURE_TLS_PARAMS = (
    "tlsinsecure=true",
    "tlsallowinvalidcertificates=true",
    "tlsallowinvalidhostnames=true",
    "ssl_cert_reqs=cert_none",
)


def _validate_mongodb_url(url: str) -> None:
    """拒絕含不安全 TLS 參數的連線字串"""
    url_lower = url.lower()
    for bad in _INSECURE_TLS_PARAMS:
        if bad in url_lower:
            raise RuntimeError(
                f"MONGODB_URL 含不安全 TLS 參數 '{bad}'，拒絕啟動。\n"
                f"生產環境必須驗證憑證以防中間人攻擊。"
            )


class MongoDB:
    """MongoDB 連接管理器"""
    client: Optional[AsyncIOMotorClient] = None

    @classmethod
    async def connect(cls):
        """啟動時連接 MongoDB"""
        try:
            _validate_mongodb_url(MONGODB_URL)
            # 注意：MongoDB Atlas 使用副本集，不能用 directConnection=True
            is_atlas = "mongodb.net" in MONGODB_URL or "mongodb+srv" in MONGODB_URL
            # Atlas 強制 TLS 並驗證憑證；本地 docker mongo 不啟用 TLS
            tls_opts = (
                {"tls": True, "tlsAllowInvalidCertificates": False}
                if is_atlas
                else {}
            )
            cls.client = AsyncIOMotorClient(
                MONGODB_URL,
                maxPoolSize=20,
                minPoolSize=2,
                waitQueueTimeoutMS=5000,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                # 30s 涵蓋 admin 報表 aggregation 與冷快取場景；
                # 一般 CRUD 用不到，長 query 建議改用 maxTimeMS() per-op。
                socketTimeoutMS=30000,
                **({"directConnection": True} if not is_atlas else {}),
                **tls_opts,
            )
            # 測試連接
            await cls.client.admin.command('ping')
            log.info("db.connected", db_name=MONGODB_DB_NAME, tls=is_atlas)
        except Exception as e:
            log.error("db.connect.failed", error=str(e), exc_info=True)
            raise

    @classmethod
    async def close(cls):
        """關閉時斷開 MongoDB 連接"""
        if cls.client:
            cls.client.close()
            log.info("db.closed")

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
