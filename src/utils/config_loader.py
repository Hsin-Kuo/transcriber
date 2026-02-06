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
from typing import Optional
from functools import lru_cache


DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")

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
