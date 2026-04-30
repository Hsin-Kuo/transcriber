"""
Worker 設定常數
從環境變數與 SSM Parameter Store 讀取，在啟動時載入一次。
"""

import os
from src.utils.config_loader import get_parameter

SQS_QUEUE_URL: str = os.getenv("SQS_QUEUE_URL", "")
S3_REGION: str = os.getenv("S3_REGION", "ap-northeast-1")
S3_BUCKET: str = os.getenv("S3_BUCKET", "")
MONGODB_URL: str = get_parameter(
    "/transcriber/mongodb-url",
    fallback_env="MONGODB_URL",
    default="mongodb://localhost:27017",
)
MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
DEFAULT_MODEL: str = os.getenv("WHISPER_MODEL", "medium")
WORKER_SECRET: str = get_parameter(
    "/transcriber/worker-secret",
    fallback_env="WORKER_SECRET",
    default="",
)
AUTO_SHUTDOWN_IDLE_MINUTES: int = int(os.getenv("AUTO_SHUTDOWN_IDLE_MINUTES", "5"))

# SQS 行為
SQS_LONG_POLL_SECONDS: int = 20          # receive_message WaitTimeSeconds
SQS_VISIBILITY_TIMEOUT_SECONDS: int = 600  # 10 分鐘，單個任務最長處理時間

# Spot 中斷監控
SPOT_CHECK_INTERVAL_SECONDS: int = 30
SPOT_INTERRUPT_VISIBILITY_TIMEOUT: int = 30  # 中斷後縮短 SQS 可見時間，讓其他 Worker 接手

# MongoDB（Worker 同步連線）
MONGODB_POOL_SIZE: int = 5
MONGODB_TIMEOUT_MS: int = 5000

# 從 SSM 載入 Gemini API keys 並注入環境變數，讓 PunctuationProcessor 可以讀取
_google_api_key_1 = get_parameter(
    "/transcriber/google-api-key-1", fallback_env="GOOGLE_API_KEY_1", default=""
)
_google_api_key_2 = get_parameter(
    "/transcriber/google-api-key-2", fallback_env="GOOGLE_API_KEY_2", default=""
)
if _google_api_key_1:
    os.environ["GOOGLE_API_KEY_1"] = _google_api_key_1
if _google_api_key_2:
    os.environ["GOOGLE_API_KEY_2"] = _google_api_key_2
