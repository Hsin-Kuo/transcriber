"""
設定載入器 — 統一管理環境變數與 AWS SSM Parameter Store

根據 DEPLOY_ENV 自動切換：
  - local: 從 os.getenv 讀取（.env 檔案）
  - aws:   從 AWS SSM Parameter Store 讀取（加密參數）

使用方式：
    from src.utils.config_loader import get_parameter
    jwt_secret = get_parameter("/transcriber/jwt-secret", fallback_env="JWT_SECRET_KEY")
"""

import os
import time
import shutil
import tempfile
from pathlib import Path
from typing import Optional
from functools import lru_cache


DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")

# AWS 上 /tmp 是 tmpfs（記憶體），空間有限，改用磁碟路徑
_TEMP_BASE = Path(os.getenv("TEMP_DIR", "/opt/transcriber/tmp" if DEPLOY_ENV == "aws" else tempfile.gettempdir()))


def get_temp_dir(prefix: str = "") -> Path:
    """建立暫存目錄，AWS 模式使用磁碟路徑避免 tmpfs 空間不足

    Args:
        prefix: 目錄名稱前綴

    Returns:
        暫存目錄路徑
    """
    _TEMP_BASE.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=_TEMP_BASE))


def cleanup_stale_temp_dirs(max_age_hours: int = 2):
    """清理超過指定時間的暫存目錄（服務啟動時呼叫）

    處理伺服器 crash/重啟後殘留的孤兒暫存檔案。

    Args:
        max_age_hours: 超過幾小時視為過期
    """
    if not _TEMP_BASE.exists():
        return

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned = 0

    for entry in _TEMP_BASE.iterdir():
        if not entry.is_dir():
            continue
        try:
            age = now - entry.stat().st_mtime
            if age > max_age_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                cleaned += 1
        except OSError:
            pass

    if cleaned:
        print(f"🧹 啟動清理：移除 {cleaned} 個過期暫存目錄（>{max_age_hours}h）")

# Lazy-init SSM client
_ssm_client = None


def _get_ssm():
    """延遲初始化 SSM client"""
    global _ssm_client
    if _ssm_client is None:
        import boto3
        _ssm_client = boto3.client(
            "ssm",
            region_name=os.getenv("S3_REGION", "ap-northeast-1")
        )
    return _ssm_client


@lru_cache(maxsize=64)
def get_parameter(name: str, fallback_env: Optional[str] = None, default: str = "") -> str:
    """讀取設定參數

    AWS 模式：從 SSM Parameter Store 讀取（帶快取）
    Local 模式：從環境變數讀取

    Args:
        name: SSM 參數名稱（例如 /transcriber/jwt-secret）
        fallback_env: 本地環境變數名稱（例如 JWT_SECRET_KEY）
        default: 預設值

    Returns:
        參數值
    """
    if DEPLOY_ENV == "aws":
        try:
            resp = _get_ssm().get_parameter(Name=name, WithDecryption=True)
            return resp["Parameter"]["Value"]
        except Exception as e:
            print(f"⚠️ SSM 讀取 {name} 失敗: {e}")
            # Fallback 到環境變數
            if fallback_env:
                return os.getenv(fallback_env, default)
            return default
    else:
        # 本地模式：直接讀環境變數
        if fallback_env:
            return os.getenv(fallback_env, default)
        return default
