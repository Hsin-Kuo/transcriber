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

from src.utils.logger import get_logger

log = get_logger(__name__)


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


def temp_free_bytes() -> int:
    """回傳暫存所在檔案系統（_TEMP_BASE）目前的可用空間 bytes。

    分片上傳、轉錄 working copy 都落在這個檔案系統，上傳前用它做容量守門。
    """
    _TEMP_BASE.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(_TEMP_BASE).free


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
        log.info("config.stale_temp_cleaned", count=cleaned, max_age_hours=max_age_hours)

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


_param_cache: dict[tuple, str] = {}


def get_parameter(
    name: str,
    fallback_env: Optional[str] = None,
    default: str = "",
    required: bool = False,
) -> str:
    """讀取設定參數

    AWS 模式：從 SSM Parameter Store 讀取
    Local 模式：從環境變數讀取

    Cache 政策：**只 cache 非空回傳值** — 避免「server 啟動時 SSM 暫時不通
    導致回空 → lru_cache 鎖死空值 → 之後永遠回 500」這種 poison 情境。
    secrets 為空一定是錯，重打 SSM 比 cache 錯誤值好。

    APP_ENV 路由：APP_ENV=staging 時把 `/transcriber/` 前綴改寫成 `/transcriber-staging/`，
    讓 staging 環境讀自己那組 SSM secret（與 prod 完全隔離）。所有 19 處 SSM 讀取都經過本
    函式，故路由集中在此單點。在呼叫時讀 APP_ENV（而非 module 全域）以避開 import 時序疑慮。

    `required` 語意（金流體檢 P1-6）：某些憑證（91APP / SmilePay API key）一旦靜默
    fallback 到 env 殘留的範例值，後果是真客戶資料打到公開測試帳號，比「服務打不開」
    更糟。required=True 時：
      - AWS 模式：SSM 讀取失敗（拋例外）或回空值 → **不 fallback 到 env**，直接
        `raise RuntimeError`。只 log 參數名稱，絕不 log 值。
      - 非 AWS 模式：讀 env 後仍是空值 → 同樣 raise（本地要跑金流也不該無憑證靜默）。
      - required=False（預設）：行為完全不變，維持既有 fallback。
    raise 前不寫入 cache（維持「只 cache 非空值」的既有語意）。

    Args:
        name: SSM 參數名稱（例如 /transcriber/jwt-secret）
        fallback_env: 本地環境變數名稱（例如 JWT_SECRET_KEY）
        default: 預設值
        required: True 時關閉 SSM 失敗 fallback env 的行為，空值直接 raise

    Returns:
        參數值

    Raises:
        RuntimeError: required=True 且無法取得非空值
    """
    if os.getenv("APP_ENV", "prod") == "staging" and name.startswith("/transcriber/"):
        name = name.replace("/transcriber/", "/transcriber-staging/", 1)

    # cache key 含 required（第二意見審查 F2）：同名參數若同時存在 required=False 的
    # 呼叫端，其 env fallback 值不得被 required=True 的讀取命中——那正是 required 要
    # 擋的靜默降級。兩種讀法各自成 cache 條目。
    cache_key = (name, fallback_env, default, required)
    cached = _param_cache.get(cache_key)
    if cached:
        return cached

    # 即時讀 env 而非 module 級 DEPLOY_ENV 常數（第二意見審查 F1）：required 的
    # 「aws 上只認 SSM」保證不可建立在 import 時序上——常數若在 env 就緒前凍結成
    # local，required 會走本地分支直接吃殘留 .env 的範例憑證，第二層防護空轉。
    if os.getenv("DEPLOY_ENV", "local") == "aws":
        try:
            resp = _get_ssm().get_parameter(Name=name, WithDecryption=True)
            value = resp["Parameter"]["Value"]
        except Exception as e:
            if required:
                log.error("config.required_parameter_unavailable", parameter=name, reason="ssm_read_failed")
                raise RuntimeError(f"required parameter {name} unavailable from SSM") from e
            log.warning("config.ssm_read_failed", parameter=name, error=str(e))
            # Fallback 到環境變數
            value = os.getenv(fallback_env, default) if fallback_env else default
        else:
            if required and not value:
                log.error("config.required_parameter_unavailable", parameter=name, reason="ssm_empty_value")
                raise RuntimeError(f"required parameter {name} unavailable from SSM")
    else:
        # 本地模式：直接讀環境變數
        value = os.getenv(fallback_env, default) if fallback_env else default
        if required and not value:
            log.error("config.required_parameter_unavailable", parameter=name, reason="env_empty_value")
            raise RuntimeError(f"required parameter {name} unavailable")

    if value:
        _param_cache[cache_key] = value
    return value


def is_prod_aws() -> bool:
    """正式生產環境判定：DEPLOY_ENV=aws 且 APP_ENV 非 staging。

    ⚠️ 必須即時讀 os.getenv，不可用 module 級 DEPLOY_ENV 常數（import 時定型，
    測試與動態環境會失準）。APP_ENV 在 prod 是「未設 → 預設 prod」（deploy/.env.aws
    全檔無此行），staging 顯式 APP_ENV=staging（deploy/.env.aws.staging:12），所以
    條件寫「!= staging」而非「== prod」。
    """
    return os.getenv("DEPLOY_ENV", "local") == "aws" and os.getenv("APP_ENV", "prod") != "staging"


def validate_payment_env() -> None:
    """啟動時檢查金流環境變數是否為三態之一（金流體檢 P1-6，只在 prod-aws 檢查）。

    三態語意（刻意分級，不是單純「非 production 就炸」）：
      - 值 == "production"：OK，正常上線狀態。
      - 未設（None）：警告但不 crash——金流可能還沒 seed SSM/env（尚未上線的
        預期狀態），無條件 crash 會把還沒排上金流的 prod 服務整個打掛；
        service __init__ 的 fail-closed 硬擋（P1-6 規格 C）已經兜底，
        確保「沒設」不會誤用測試帳號跑真實操作。
      - 顯式設成非 production 的值（例如殘留 test/sandbox）：這是主動設定錯誤，
        必須擋下啟動，避免真客戶資料打到公開測試帳號。

    staging 環境不受此檢查約束（staging 本來就該打 sandbox/test）。
    """
    if not is_prod_aws():
        return

    for var_name in ("PAYMENTS91_ENV", "SMILEPAY_ENV"):
        value = os.getenv(var_name)
        if value is None:
            log.warning("payment.env.not_configured", var=var_name)
        elif value != "production":
            raise RuntimeError(
                f"{var_name} is set to a non-production value on prod (P1-6 fail-fast)"
            )
