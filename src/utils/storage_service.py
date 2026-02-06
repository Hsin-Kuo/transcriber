"""
檔案儲存服務 — 統一封裝 local / S3 檔案操作

根據 DEPLOY_ENV 環境變數自動切換：
  - local: 使用本地 uploads/ 目錄（現有行為）
  - aws:   使用 AWS S3

使用方式：
    from src.utils.storage_service import storage
    storage.save_audio(task_id, local_path)
"""

import os
import re
import shutil
from pathlib import Path
from typing import Optional


DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "ap-northeast-1")

# Presigned URL 最大有效時間（秒）：1 小時
MAX_PRESIGNED_URL_TTL = 3600

# UUID v4 格式驗證
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _validate_task_id(task_id: str) -> None:
    """驗證 task_id 是合法的 UUID 格式，防止路徑穿越攻擊

    Raises:
        ValueError: task_id 格式不合法
    """
    if not task_id or not _UUID_RE.match(task_id):
        raise ValueError(f"Invalid task_id format: {task_id}")

# Lazy-init S3 client（local 模式不 import boto3）
_s3_client = None


def _get_s3():
    """延遲初始化 S3 client，避免 local 模式也需要 boto3"""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3", region_name=S3_REGION)
    return _s3_client


def _get_s3_client_error():
    """取得 botocore ClientError 類型（lazy import）"""
    from botocore.exceptions import ClientError
    return ClientError


def is_aws() -> bool:
    """是否為 AWS 部署模式"""
    return DEPLOY_ENV == "aws"


# ==================== 音檔操作 ====================

def save_audio(task_id: str, local_path: Path) -> str:
    """儲存音檔（上傳後呼叫）

    Args:
        task_id: 任務 ID
        local_path: 本地暫存的音檔路徑

    Returns:
        儲存後的路徑標識（本地路徑 或 s3:// URI）
    """
    _validate_task_id(task_id)
    if is_aws():
        key = f"uploads/{task_id}.mp3"
        _get_s3().upload_file(str(local_path), S3_BUCKET, key)
        local_path.unlink(missing_ok=True)
        return f"s3://{S3_BUCKET}/{key}"
    else:
        uploads_dir = Path("uploads")
        uploads_dir.mkdir(exist_ok=True)
        dest = uploads_dir / f"{task_id}.mp3"
        shutil.move(str(local_path), str(dest))
        return str(dest)


def get_audio_local_path(task_id: str) -> Optional[Path]:
    """取得音檔的本地路徑（僅 local 模式有效）

    Args:
        task_id: 任務 ID

    Returns:
        本地 Path（如果存在），AWS 模式回傳 None
    """
    _validate_task_id(task_id)
    if is_aws():
        return None
    path = Path("uploads") / f"{task_id}.mp3"
    return path if path.exists() else None


def get_audio_presigned_url(task_id: str, expires_in: int = 3600) -> Optional[str]:
    """取得音檔的 S3 presigned URL（僅 AWS 模式有效）

    Args:
        task_id: 任務 ID
        expires_in: URL 有效時間（秒），預設 1 小時，上限 MAX_PRESIGNED_URL_TTL

    Returns:
        Presigned URL 字串，local 模式回傳 None
    """
    _validate_task_id(task_id)
    if not is_aws():
        return None
    expires_in = min(expires_in, MAX_PRESIGNED_URL_TTL)
    key = f"uploads/{task_id}.mp3"
    return _get_s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def download_audio(task_id: str, dest: Path) -> Path:
    """下載音檔到本機（Worker 用）

    Args:
        task_id: 任務 ID
        dest: 下載目標路徑

    Returns:
        下載後的檔案路徑
    """
    _validate_task_id(task_id)
    if is_aws():
        key = f"uploads/{task_id}.mp3"
        _get_s3().download_file(S3_BUCKET, key, str(dest))
    else:
        src = Path("uploads") / f"{task_id}.mp3"
        shutil.copy2(str(src), str(dest))
    return dest


def delete_audio(task_id: str) -> None:
    """刪除音檔

    Args:
        task_id: 任務 ID
    """
    _validate_task_id(task_id)
    if is_aws():
        key = f"uploads/{task_id}.mp3"
        try:
            _get_s3().delete_object(Bucket=S3_BUCKET, Key=key)
        except _get_s3_client_error() as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "NoSuchKey":
                pass  # 檔案本來就不存在，不需要報錯
            else:
                print(f"⚠️ S3 刪除音檔失敗 ({error_code}): {e}")
                raise
        except Exception as e:
            print(f"⚠️ S3 刪除音檔失敗: {e}")
            raise
    else:
        path = Path("uploads") / f"{task_id}.mp3"
        path.unlink(missing_ok=True)


def audio_exists(task_id: str) -> bool:
    """檢查音檔是否存在

    Args:
        task_id: 任務 ID

    Returns:
        音檔是否存在
    """
    _validate_task_id(task_id)
    if is_aws():
        key = f"uploads/{task_id}.mp3"
        try:
            _get_s3().head_object(Bucket=S3_BUCKET, Key=key)
            return True
        except _get_s3_client_error() as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("404", "NoSuchKey"):
                return False
            raise  # 權限錯誤等非預期異常應上拋
        except Exception:
            return False
    else:
        return (Path("uploads") / f"{task_id}.mp3").exists()


# ==================== 輸出檔案操作 ====================

def _validate_filename(filename: str) -> None:
    """驗證檔案名稱不含路徑穿越字元

    Raises:
        ValueError: 檔案名稱不合法
    """
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError(f"Invalid filename: {filename}")


def save_output(task_id: str, filename: str, local_path: Path) -> str:
    """儲存輸出檔案（轉錄結果 TXT/JSON 等）

    Args:
        task_id: 任務 ID
        filename: 檔案名稱
        local_path: 本地暫存路徑

    Returns:
        儲存後的路徑標識
    """
    _validate_task_id(task_id)
    _validate_filename(filename)
    if is_aws():
        key = f"output/{task_id}/{filename}"
        _get_s3().upload_file(str(local_path), S3_BUCKET, key)
        return f"s3://{S3_BUCKET}/{key}"
    else:
        dest = Path("output") / task_id / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(local_path), str(dest))
        return str(dest)


def get_output_presigned_url(task_id: str, filename: str, expires_in: int = 3600) -> Optional[str]:
    """取得輸出檔案的 S3 presigned URL

    Args:
        task_id: 任務 ID
        filename: 檔案名稱
        expires_in: URL 有效時間（秒），上限 MAX_PRESIGNED_URL_TTL

    Returns:
        Presigned URL 字串，local 模式回傳 None
    """
    _validate_task_id(task_id)
    _validate_filename(filename)
    if not is_aws():
        return None
    expires_in = min(expires_in, MAX_PRESIGNED_URL_TTL)
    key = f"output/{task_id}/{filename}"
    return _get_s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def validate_aws_config() -> None:
    """驗證 AWS 模式必要的設定是否存在

    應在應用程式啟動時呼叫。

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
