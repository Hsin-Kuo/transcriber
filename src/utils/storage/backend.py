"""儲存後端核心 — local / S3 切換、S3 client、共用驗證。

`is_aws()` 決定 local（`uploads/` 目錄）還是 AWS S3。Compact audio 與 Handoff audio
兩個 store 都建立在這層之上；它不認得任何單一音檔形態的語意（tier / 副檔名白名單等
分別住在 compact / handoff）。
"""
import os
import re
from pathlib import Path

from src.utils.logger import get_logger

log = get_logger(__name__)


DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "ap-northeast-1")

# Presigned URL 最大有效時間（秒）：1 小時
MAX_PRESIGNED_URL_TTL = 3600

# UUID v4 格式驗證
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def validate_task_id(task_id: str) -> None:
    """驗證 task_id 是合法的 UUID 格式，防止路徑穿越攻擊。

    Raises:
        ValueError: task_id 格式不合法
    """
    if not task_id or not _UUID_RE.match(task_id):
        raise ValueError(f"Invalid task_id format: {task_id}")


# Lazy-init S3 client（local 模式不 import boto3）
_s3_client = None


def get_s3():
    """延遲初始化 S3 client，避免 local 模式也需要 boto3。"""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3", region_name=S3_REGION)
    return _s3_client


def get_s3_client_error():
    """取得 botocore ClientError 類型（lazy import）。"""
    from botocore.exceptions import ClientError
    return ClientError


def is_aws() -> bool:
    """是否為 AWS 部署模式。"""
    return DEPLOY_ENV == "aws"


_AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
    ".webm": "audio/webm",
}


def detect_content_type(local_path: Path) -> str:
    """從檔案前幾個位元組偵測實際 MIME type。"""
    try:
        with open(local_path, "rb") as f:
            header = f.read(12)
        if header[4:8] == b"ftyp":
            return "audio/mp4"
        if header[:3] == b"ID3" or (header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
            return "audio/mpeg"
        if header[:4] == b"OggS":
            return "audio/ogg"
        if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
            return "audio/wav"
        if header[:4] == b"fLaC":
            return "audio/flac"
    except Exception:
        pass
    return _AUDIO_MIME_TYPES.get(local_path.suffix.lower(), "audio/mpeg")


def parse_s3_key(uri: str):
    """從 `s3://{bucket}/{key}` 取出 key；非 s3 uri 或格式錯誤回 None。"""
    if not uri or not uri.startswith("s3://"):
        return None
    parts = uri.split("/", 3)  # ['s3:', '', 'bucket', 'key...']
    return parts[3] if len(parts) >= 4 else None


def validate_aws_config() -> None:
    """驗證 AWS 模式必要的設定是否存在（應在應用程式啟動時呼叫）。

    Raises:
        RuntimeError: 缺少必要的 AWS 設定
    """
    if not is_aws():
        return

    missing = []
    if not S3_BUCKET:
        missing.append("S3_BUCKET")
    if not os.getenv("SQS_QUEUE_URL"):
        missing.append("SQS_QUEUE_URL")
    if missing:
        raise RuntimeError(
            f"AWS mode requires the following environment variables: {', '.join(missing)}"
        )
