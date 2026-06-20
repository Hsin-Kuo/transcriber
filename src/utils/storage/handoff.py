"""Handoff audio 儲存 — Web Server → Worker 的傳遞暫態。

對應 CONTEXT.md「Handoff audio」。Dispatch 把使用者上傳的原始檔放 `handoff/{id}.{ext}`，
Worker 取走 + 轉成 Compact audio 後 DELETE；失敗/取消的孤兒由 sweep 定期清。
Local 模式不適用（temp_dir 直接交給 orchestrator）。
"""
from pathlib import Path

from .backend import (
    S3_BUCKET,
    detect_content_type,
    get_s3,
    get_s3_client_error,
    is_aws,
    log,
    validate_task_id,
)

# 副檔名白名單（防 path injection；對應 audio_validator 允許的格式）
_VALID_HANDOFF_EXTS = {"mp3", "m4a", "wav", "mp4", "aac", "flac", "ogg", "wma", "webm", "opus"}


def _validate_ext(ext: str) -> None:
    """驗證 handoff 副檔名（防 path injection）。"""
    if ext not in _VALID_HANDOFF_EXTS:
        raise ValueError(f"Invalid handoff ext: {ext!r}")


def _handoff_s3_key(task_id: str, ext: str) -> str:
    """產生 handoff 音檔的 S3 key，例如 handoff/{task_id}.wav。"""
    validate_task_id(task_id)
    _validate_ext(ext)
    return f"handoff/{task_id}.{ext}"


def upload_to_handoff(task_id: str, local_path: Path, ext: str) -> str:
    """上傳 handoff 音檔到 S3（dispatch 用）。Local 模式 noop 回 local_path 字串。"""
    validate_task_id(task_id)
    _validate_ext(ext)
    if is_aws():
        content_type = detect_content_type(local_path)
        key = _handoff_s3_key(task_id, ext)
        get_s3().upload_file(
            str(local_path), S3_BUCKET, key,
            ExtraArgs={"ContentType": content_type},
        )
        local_path.unlink(missing_ok=True)
        return f"s3://{S3_BUCKET}/{key}"
    # local 模式：file 已經在本地，無需搬動
    return str(local_path)


def download_from_handoff(task_id: str, ext: str, dest: Path) -> Path:
    """從 S3 handoff/ 下載音檔到本機（Worker 用）。"""
    validate_task_id(task_id)
    _validate_ext(ext)
    if not is_aws():
        raise RuntimeError("download_from_handoff 僅 AWS 模式可用")
    key = _handoff_s3_key(task_id, ext)
    get_s3().download_file(S3_BUCKET, key, str(dest))
    return dest


def delete_handoff(task_id: str, ext: str) -> None:
    """刪除 handoff 音檔（Worker 轉成 Compact audio 並 save_audio 成功後呼叫）。

    NoSuchKey 視為已刪除，不報錯（idempotent）。
    """
    validate_task_id(task_id)
    _validate_ext(ext)
    if not is_aws():
        return
    key = _handoff_s3_key(task_id, ext)
    try:
        get_s3().delete_object(Bucket=S3_BUCKET, Key=key)
    except get_s3_client_error() as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "NoSuchKey":
            return
        log.error("storage.handoff_delete_failed", error_code=error_code, error=str(e))
        raise


def sweep_handoff_orphans(older_than_hours: int = 24) -> int:
    """掃 S3 handoff/ 找超過 N 小時的孤兒並刪除，回刪除的物件數。

    正常情況 Worker 完成後會立即刪除自己的 handoff；殘留代表 dispatch 上傳後 Worker
    沒處理（crash / cancel / SQS lost / Spot 中斷沒恢復等）。24 小時夠久讓 Worker 重啟恢復。
    """
    if not is_aws():
        return 0
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    paginator = get_s3().get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="handoff/"):
        objects = page.get("Contents") or []
        stale_keys = [
            {"Key": obj["Key"]}
            for obj in objects
            if obj["LastModified"] < cutoff
        ]
        if not stale_keys:
            continue
        # S3 delete_objects 一次最多 1000；page size 預設就是 1000，可以直接送
        resp = get_s3().delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": stale_keys, "Quiet": True},
        )
        deleted += len(stale_keys)
        for err in resp.get("Errors") or []:
            log.warning("storage.handoff_sweep_delete_failed", error=str(err))
    return deleted
