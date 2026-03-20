"""
檔案儲存服務 — 統一封裝 local / S3 檔案操作

根據 DEPLOY_ENV 環境變數自動切換：
  - local: 使用本地 uploads/ 目錄（現有行為）
  - aws:   使用 AWS S3

AWS 音檔路徑結構（依方案分資料夾，搭配 S3 Lifecycle Rule 自動過期）：
  - uploads/free/{task_id}.mp3    → 3 天後自動刪除
  - uploads/basic/{task_id}.mp3   → 7 天後自動刪除
  - uploads/pro/{task_id}.mp3     → 7 天後自動刪除
  - uploads/kept/{task_id}.mp3    → 不自動刪除（用戶手動保留）

使用方式：
    from src.utils.storage_service import storage
    storage.save_audio(task_id, local_path, tier="free")
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

# 允許的 tier 值（防止路徑注入）
_VALID_TIERS = {"free", "basic", "pro", "enterprise", "kept"}


def _validate_task_id(task_id: str) -> None:
    """驗證 task_id 是合法的 UUID 格式，防止路徑穿越攻擊

    Raises:
        ValueError: task_id 格式不合法
    """
    if not task_id or not _UUID_RE.match(task_id):
        raise ValueError(f"Invalid task_id format: {task_id}")


def _validate_tier(tier: str) -> None:
    """驗證 tier 是合法值，防止路徑注入

    Raises:
        ValueError: tier 不合法
    """
    if tier not in _VALID_TIERS:
        raise ValueError(f"Invalid tier: {tier}")


def _audio_s3_key(task_id: str, tier: str = "free") -> str:
    """產生音檔的 S3 key

    Args:
        task_id: 任務 ID
        tier: 用戶方案（free/basic/pro/enterprise/kept）

    Returns:
        S3 object key，例如 uploads/free/{task_id}.mp3
    """
    _validate_tier(tier)
    return f"uploads/{tier}/{task_id}.mp3"


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

def save_audio(task_id: str, local_path: Path, tier: str = "free") -> str:
    """儲存音檔（上傳後呼叫）

    Args:
        task_id: 任務 ID
        local_path: 本地暫存的音檔路徑
        tier: 用戶方案（決定 S3 存放資料夾）

    Returns:
        儲存後的路徑標識（本地路徑 或 s3:// URI）
    """
    _validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
        _get_s3().upload_file(
            str(local_path), S3_BUCKET, key,
            ExtraArgs={"ContentType": "audio/mpeg"}
        )
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


def get_audio_presigned_url(task_id: str, expires_in: int = 3600, tier: str = "free") -> Optional[str]:
    """取得音檔的 S3 presigned URL（僅 AWS 模式有效）

    Args:
        task_id: 任務 ID
        expires_in: URL 有效時間（秒），預設 1 小時，上限 MAX_PRESIGNED_URL_TTL
        tier: 用戶方案（決定 S3 資料夾）

    Returns:
        Presigned URL 字串，local 模式回傳 None
    """
    _validate_task_id(task_id)
    if not is_aws():
        return None
    expires_in = min(expires_in, MAX_PRESIGNED_URL_TTL)
    key = _audio_s3_key(task_id, tier)
    return _get_s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": key,
            "ResponseContentType": "audio/mpeg",
        },
        ExpiresIn=expires_in,
    )


def download_audio(task_id: str, dest: Path, tier: str = "free") -> Path:
    """下載音檔到本機（Worker 用）

    Args:
        task_id: 任務 ID
        dest: 下載目標路徑
        tier: 用戶方案（決定 S3 資料夾）

    Returns:
        下載後的檔案路徑
    """
    _validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
        _get_s3().download_file(S3_BUCKET, key, str(dest))
    else:
        src = Path("uploads") / f"{task_id}.mp3"
        shutil.copy2(str(src), str(dest))
    return dest


def delete_audio(task_id: str, tier: str = "free") -> None:
    """刪除音檔

    Args:
        task_id: 任務 ID
        tier: 用戶方案（決定 S3 資料夾）
    """
    _validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
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


def delete_audio_by_path(audio_file_path: str) -> None:
    """根據儲存的完整路徑刪除音檔（用於不確定 tier 的場景）

    Args:
        audio_file_path: 儲存在 DB 中的路徑（s3://... 或本地路徑）
    """
    if not audio_file_path:
        return
    if is_aws() and audio_file_path.startswith("s3://"):
        # 從 s3://bucket/uploads/tier/task_id.mp3 提取 key
        # 格式: s3://{bucket}/{key}
        parts = audio_file_path.split("/", 3)  # ['s3:', '', 'bucket', 'key...']
        if len(parts) >= 4:
            key = parts[3]
            try:
                _get_s3().delete_object(Bucket=S3_BUCKET, Key=key)
            except Exception as e:
                print(f"⚠️ S3 刪除音檔失敗: {e}")
    else:
        path = Path(audio_file_path)
        path.unlink(missing_ok=True)


def audio_exists(task_id: str, tier: str = "free") -> bool:
    """檢查音檔是否存在

    Args:
        task_id: 任務 ID
        tier: 用戶方案（決定 S3 資料夾）

    Returns:
        音檔是否存在
    """
    _validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
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


def audio_exists_by_path(audio_file_path: str) -> bool:
    """根據儲存的完整路徑檢查音檔是否存在

    Args:
        audio_file_path: 儲存在 DB 中的路徑（s3://... 或本地路徑）

    Returns:
        音檔是否存在
    """
    if not audio_file_path:
        return False
    if is_aws() and audio_file_path.startswith("s3://"):
        parts = audio_file_path.split("/", 3)
        if len(parts) >= 4:
            key = parts[3]
            try:
                _get_s3().head_object(Bucket=S3_BUCKET, Key=key)
                return True
            except Exception:
                return False
        return False
    else:
        return Path(audio_file_path).exists()


def get_presigned_url_by_path(audio_file_path: str, expires_in: int = 3600) -> Optional[str]:
    """根據儲存的完整路徑產生 presigned URL

    Args:
        audio_file_path: 儲存在 DB 中的路徑（s3://...）
        expires_in: URL 有效時間（秒）

    Returns:
        Presigned URL 字串，非 AWS 或格式錯誤回傳 None
    """
    if not audio_file_path or not is_aws() or not audio_file_path.startswith("s3://"):
        return None
    parts = audio_file_path.split("/", 3)
    if len(parts) < 4:
        return None
    key = parts[3]
    expires_in = min(expires_in, MAX_PRESIGNED_URL_TTL)
    return _get_s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": key,
            "ResponseContentType": "audio/mpeg",
        },
        ExpiresIn=expires_in,
    )


def move_audio(task_id: str, from_tier: str, to_tier: str) -> str:
    """在 S3 上搬移音檔（用於 keep_audio 切換時）

    Args:
        task_id: 任務 ID
        from_tier: 來源 tier
        to_tier: 目標 tier

    Returns:
        搬移後的新路徑（s3:// URI 或本地路徑）
    """
    _validate_task_id(task_id)
    if from_tier == to_tier:
        return f"s3://{S3_BUCKET}/{_audio_s3_key(task_id, from_tier)}" if is_aws() else str(Path("uploads") / f"{task_id}.mp3")

    if is_aws():
        src_key = _audio_s3_key(task_id, from_tier)
        dst_key = _audio_s3_key(task_id, to_tier)
        s3 = _get_s3()
        # S3 copy + delete
        s3.copy_object(
            Bucket=S3_BUCKET,
            CopySource={"Bucket": S3_BUCKET, "Key": src_key},
            Key=dst_key,
        )
        s3.delete_object(Bucket=S3_BUCKET, Key=src_key)
        print(f"📦 音檔已搬移: {src_key} → {dst_key}")
        return f"s3://{S3_BUCKET}/{dst_key}"
    else:
        # local 模式不分資料夾
        path = Path("uploads") / f"{task_id}.mp3"
        return str(path)


def extract_tier_from_path(audio_file_path: str) -> Optional[str]:
    """從儲存的路徑中提取 tier

    Args:
        audio_file_path: 儲存在 DB 中的路徑，例如 s3://bucket/uploads/free/task_id.mp3

    Returns:
        tier 字串（free/basic/pro/enterprise/kept），無法解析時回傳 None
    """
    if not audio_file_path:
        return None
    if audio_file_path.startswith("s3://"):
        # s3://bucket/uploads/{tier}/{task_id}.mp3
        parts = audio_file_path.split("/")
        # ['s3:', '', 'bucket', 'uploads', 'tier', 'task_id.mp3']
        if len(parts) >= 6 and parts[3] == "uploads" and parts[4] in _VALID_TIERS:
            return parts[4]
    return None


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
