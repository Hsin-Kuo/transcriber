"""Compact audio 儲存 — 使用者下載「這個 task 的音檔」拿到的永久檔。

對應 CONTEXT.md「Compact audio」。AWS 路徑依方案分資料夾（搭配 S3 Lifecycle Rule 過期）：
  uploads/free/{id}.mp3 (3d) / uploads/basic|pro/{id}.mp3 (7d) / uploads/kept/{id}.mp3 (不過期)
Local 模式不分 tier：uploads/{id}.mp3。
"""
import shutil
from pathlib import Path
from typing import Optional

from .backend import (
    MAX_PRESIGNED_URL_TTL,
    S3_BUCKET,
    detect_content_type,
    get_s3,
    get_s3_client_error,
    is_aws,
    log,
    parse_s3_key,
    validate_task_id,
)

# 允許的 tier 值（防止路徑注入）— tier 是 Compact audio 的儲存分區概念
_VALID_TIERS = {"free", "basic", "pro", "enterprise", "kept"}


def _validate_tier(tier: str) -> None:
    if tier not in _VALID_TIERS:
        raise ValueError(f"Invalid tier: {tier}")


def _audio_s3_key(task_id: str, tier: str = "free") -> str:
    """產生音檔的 S3 key，例如 uploads/free/{task_id}.mp3。"""
    _validate_tier(tier)
    return f"uploads/{tier}/{task_id}.mp3"


def save_audio(task_id: str, local_path: Path, tier: str = "free") -> str:
    """儲存音檔（上傳後呼叫）。回儲存後的路徑標識（本地路徑 或 s3:// URI）。"""
    validate_task_id(task_id)
    if is_aws():
        content_type = detect_content_type(local_path)
        key = _audio_s3_key(task_id, tier)
        get_s3().upload_file(
            str(local_path), S3_BUCKET, key,
            ExtraArgs={"ContentType": content_type},
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
    """取得音檔的本地路徑（僅 local 模式有效；AWS 回 None）。"""
    validate_task_id(task_id)
    if is_aws():
        return None
    path = Path("uploads") / f"{task_id}.mp3"
    return path if path.exists() else None


def get_audio_presigned_url(task_id: str, expires_in: int = 3600, tier: str = "free") -> Optional[str]:
    """取得音檔的 S3 presigned URL（僅 AWS 模式有效；local 回 None）。"""
    validate_task_id(task_id)
    if not is_aws():
        return None
    expires_in = min(expires_in, MAX_PRESIGNED_URL_TTL)
    key = _audio_s3_key(task_id, tier)
    return get_s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": key,
            # Compact audio 契約保證 container=mp3（見 CONTEXT.md）；固定覆寫回應
            # header，避免未來若同 bucket 混入其他 content-type 就被瀏覽器當
            # HTML inline 解析（stored XSS）。filename 用固定字串，不拼使用者
            # 可控值，避免 header injection。
            "ResponseContentType": "audio/mpeg",
            "ResponseContentDisposition": "inline; filename=audio.mp3",
        },
        ExpiresIn=expires_in,
    )


def download_audio(task_id: str, dest: Path, tier: str = "free") -> Path:
    """下載音檔到本機（Worker 用）。"""
    validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
        get_s3().download_file(S3_BUCKET, key, str(dest))
    else:
        src = Path("uploads") / f"{task_id}.mp3"
        shutil.copy2(str(src), str(dest))
    return dest


def delete_audio(task_id: str, tier: str = "free") -> None:
    """刪除音檔。"""
    validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
        try:
            get_s3().delete_object(Bucket=S3_BUCKET, Key=key)
        except get_s3_client_error() as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "NoSuchKey":
                pass  # 檔案本來就不存在，不需要報錯
            else:
                log.error("storage.audio_delete_failed", error_code=error_code, error=str(e))
                raise
        except Exception as e:
            log.error("storage.audio_delete_failed", error=str(e))
            raise
    else:
        path = Path("uploads") / f"{task_id}.mp3"
        path.unlink(missing_ok=True)


def delete_audio_by_path(audio_file_path: str) -> None:
    """根據儲存的完整路徑刪除音檔（用於不確定 tier 的場景）。"""
    if not audio_file_path:
        return
    if is_aws() and audio_file_path.startswith("s3://"):
        key = parse_s3_key(audio_file_path)
        if key:
            try:
                get_s3().delete_object(Bucket=S3_BUCKET, Key=key)
            except Exception as e:
                log.error("storage.audio_delete_failed", error=str(e))
    else:
        Path(audio_file_path).unlink(missing_ok=True)


def audio_exists(task_id: str, tier: str = "free") -> bool:
    """檢查音檔是否存在。"""
    validate_task_id(task_id)
    if is_aws():
        key = _audio_s3_key(task_id, tier)
        try:
            get_s3().head_object(Bucket=S3_BUCKET, Key=key)
            return True
        except get_s3_client_error() as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("404", "NoSuchKey"):
                return False
            raise  # 權限錯誤等非預期異常應上拋
        except Exception:
            return False
    else:
        return (Path("uploads") / f"{task_id}.mp3").exists()


def audio_exists_by_path(audio_file_path: str) -> bool:
    """根據儲存的完整路徑檢查音檔是否存在。"""
    if not audio_file_path:
        return False
    if is_aws() and audio_file_path.startswith("s3://"):
        key = parse_s3_key(audio_file_path)
        if key:
            try:
                get_s3().head_object(Bucket=S3_BUCKET, Key=key)
                return True
            except Exception:
                return False
        return False
    else:
        return Path(audio_file_path).exists()


def get_presigned_url_by_path(audio_file_path: str, expires_in: int = 3600) -> Optional[str]:
    """根據儲存的完整路徑產生 presigned URL（非 AWS 或格式錯誤回 None）。"""
    if not audio_file_path or not is_aws() or not audio_file_path.startswith("s3://"):
        return None
    key = parse_s3_key(audio_file_path)
    if not key:
        return None
    expires_in = min(expires_in, MAX_PRESIGNED_URL_TTL)
    return get_s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": S3_BUCKET,
            "Key": key,
            # 同上：Compact audio 契約保證 container=mp3，固定覆寫回應 header。
            "ResponseContentType": "audio/mpeg",
            "ResponseContentDisposition": "inline; filename=audio.mp3",
        },
        ExpiresIn=expires_in,
    )


def move_audio(task_id: str, from_tier: str, to_tier: str) -> str:
    """在 S3 上搬移音檔（用於 keep_audio 切換時）。回搬移後的新路徑。"""
    validate_task_id(task_id)
    if from_tier == to_tier:
        return f"s3://{S3_BUCKET}/{_audio_s3_key(task_id, from_tier)}" if is_aws() else str(Path("uploads") / f"{task_id}.mp3")

    if is_aws():
        src_key = _audio_s3_key(task_id, from_tier)
        dst_key = _audio_s3_key(task_id, to_tier)
        s3 = get_s3()
        s3.copy_object(
            Bucket=S3_BUCKET,
            CopySource={"Bucket": S3_BUCKET, "Key": src_key},
            Key=dst_key,
        )
        s3.delete_object(Bucket=S3_BUCKET, Key=src_key)
        log.info("storage.audio_moved", src_key=src_key, dst_key=dst_key)
        return f"s3://{S3_BUCKET}/{dst_key}"
    else:
        # local 模式不分資料夾
        path = Path("uploads") / f"{task_id}.mp3"
        return str(path)


def extract_tier_from_path(audio_file_path: str) -> Optional[str]:
    """從儲存的路徑中提取 tier，例如 s3://bucket/uploads/free/task_id.mp3 → free。"""
    if not audio_file_path:
        return None
    if audio_file_path.startswith("s3://"):
        parts = audio_file_path.split("/")
        # ['s3:', '', 'bucket', 'uploads', 'tier', 'task_id.mp3']
        if len(parts) >= 6 and parts[3] == "uploads" and parts[4] in _VALID_TIERS:
            return parts[4]
    return None
