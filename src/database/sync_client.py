"""同步 MongoDB seam（給背景 task / executor 內呼叫 / Web Server 同進程 Worker）。

設計：
- pymongo MongoClient thread-safe 且內建 connection pool；singleton 重用
- 套用跟 async mongodb.py 同套 TLS 黑名單檢查（B4），不留繞過後門
- lazy init：第一次 get_sync_db() 才連，避免 import 時打 Atlas

非用途：
- 跨 process 不可共用 client（每個 process 自己 lazy init）
- Worker process（src/worker_core/db.py）有自己的 sync DB seam，不混
"""
import os
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database

from ..utils.config_loader import get_parameter

_MONGODB_URL = get_parameter(
    "/transcriber/mongodb-url",
    fallback_env="MONGODB_URL",
    default="mongodb://localhost:27017",
)
_MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")

# 跟 async mongodb.py 同步的黑名單
_INSECURE_TLS_PARAMS = (
    "tlsinsecure=true",
    "tlsallowinvalidcertificates=true",
    "tlsallowinvalidhostnames=true",
    "ssl_cert_reqs=cert_none",
)


def _validate_url(url: str) -> None:
    url_lower = url.lower()
    for bad in _INSECURE_TLS_PARAMS:
        if bad in url_lower:
            raise RuntimeError(
                f"MONGODB_URL 含不安全 TLS 參數 '{bad}'，拒絕啟動。"
            )


_validate_url(_MONGODB_URL)


_client: Optional[MongoClient] = None


def get_sync_client() -> MongoClient:
    """取得 process-wide 共用的同步 MongoClient。

    第一次呼叫時 lazy connect；之後 N 次呼叫重用同個 client（pymongo 內部
    thread pool 處理併發）。**不要在 caller 內呼叫 client.close()**——
    那會殺掉整個 process 共用的 pool。
    """
    global _client
    if _client is None:
        is_atlas = "mongodb.net" in _MONGODB_URL or "mongodb+srv" in _MONGODB_URL
        tls_opts = (
            {"tls": True, "tlsAllowInvalidCertificates": False}
            if is_atlas
            else {}
        )
        _client = MongoClient(
            _MONGODB_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            **({"directConnection": True} if not is_atlas else {}),
            **tls_opts,
        )
    return _client


def get_sync_db() -> Database:
    """取得 process-wide 共用的同步 Database 實例。"""
    return get_sync_client()[_MONGODB_DB_NAME]
