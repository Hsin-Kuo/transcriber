"""分片上傳路由 — 解決 Cloudflare 100MB 上傳限制"""
import uuid
import asyncio
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from ..auth.dependencies import get_current_user
from ..utils.config_loader import get_temp_dir

router = APIRouter(prefix="/uploads", tags=["Uploads"])

# 進行中的上傳 (upload_id → metadata)
_active_uploads: dict[str, dict] = {}

# 清理任務是否已啟動
_cleanup_started = False

CHUNK_SIZE = 90 * 1024 * 1024  # 90 MB — 單片上限
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB — 單檔上限
UPLOAD_EXPIRY_SECONDS = 3600  # 1 小時未完成即清理


@router.post("/init")
async def init_upload(
    filename: str,
    total_size: int,
    current_user: dict = Depends(get_current_user),
):
    """初始化分片上傳，回傳 upload_id 和 total_chunks"""
    if total_size <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "檔案大小無效")
    if total_size > MAX_UPLOAD_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "檔案超過 500MB 上限")

    total_chunks = (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    upload_id = str(uuid.uuid4())
    temp_dir = get_temp_dir(prefix="chunk_")

    _active_uploads[upload_id] = {
        "user_id": str(current_user["_id"]),
        "filename": filename,
        "total_size": total_size,
        "total_chunks": total_chunks,
        "received": set(),
        "temp_dir": temp_dir,
        "created_at": datetime.now(timezone.utc),
    }

    _ensure_cleanup_task()

    return {
        "upload_id": upload_id,
        "total_chunks": total_chunks,
        "chunk_size": CHUNK_SIZE,
    }


@router.post("/{upload_id}/chunks/{chunk_index}")
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上傳單個 chunk"""
    meta = _active_uploads.get(upload_id)
    if not meta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload_id 不存在或已過期")

    if meta["user_id"] != str(current_user["_id"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "無權操作此上傳")

    if chunk_index < 0 or chunk_index >= meta["total_chunks"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"chunk_index 超出範圍 (0-{meta['total_chunks'] - 1})")

    # 寫入 chunk 檔案
    chunk_path = meta["temp_dir"] / f"chunk_{chunk_index:04d}"
    content = await file.read()
    chunk_path.write_bytes(content)

    meta["received"].add(chunk_index)

    return {
        "chunk_index": chunk_index,
        "received": len(meta["received"]),
        "total_chunks": meta["total_chunks"],
    }


@router.post("/{upload_id}/complete")
async def complete_upload(
    upload_id: str,
    current_user: dict = Depends(get_current_user),
):
    """驗證所有 chunk 到齊，組裝成完整檔案"""
    meta = _active_uploads.get(upload_id)
    if not meta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload_id 不存在或已過期")

    if meta["user_id"] != str(current_user["_id"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "無權操作此上傳")

    missing = set(range(meta["total_chunks"])) - meta["received"]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"缺少 {len(missing)} 個 chunk: {sorted(missing)[:10]}",
        )

    # 組裝完整檔案
    assembled_path = meta["temp_dir"] / meta["filename"]
    with assembled_path.open("wb") as out:
        for i in range(meta["total_chunks"]):
            chunk_path = meta["temp_dir"] / f"chunk_{i:04d}"
            out.write(chunk_path.read_bytes())
            chunk_path.unlink()  # 刪除 chunk 釋放空間

    meta["assembled_path"] = assembled_path
    meta["completed"] = True

    return {
        "status": "assembled",
        "upload_id": upload_id,
        "filename": meta["filename"],
        "size": assembled_path.stat().st_size,
    }


# ── 內部工具 ──────────────────────────────────────────

def get_upload_meta(upload_id: str) -> Optional[dict]:
    """供 transcriptions router 讀取已完成的上傳資訊"""
    meta = _active_uploads.get(upload_id)
    if meta and meta.get("completed"):
        return meta
    return None


def remove_upload(upload_id: str):
    """清除上傳記錄（transcriptions router 接手後呼叫）"""
    meta = _active_uploads.pop(upload_id, None)
    # 不刪 temp_dir — 由 transcriptions router 負責清理
    return meta


def _ensure_cleanup_task():
    """確保背景清理任務已啟動"""
    global _cleanup_started
    if not _cleanup_started:
        _cleanup_started = True
        asyncio.get_event_loop().create_task(_cleanup_expired_uploads())


async def _cleanup_expired_uploads():
    """定時清理超過 1 小時未完成的上傳"""
    while True:
        await asyncio.sleep(300)  # 每 5 分鐘檢查
        now = datetime.now(timezone.utc)
        expired = [
            uid for uid, meta in _active_uploads.items()
            if (now - meta["created_at"]).total_seconds() > UPLOAD_EXPIRY_SECONDS
            and not meta.get("completed")
        ]
        for uid in expired:
            meta = _active_uploads.pop(uid, None)
            if meta and meta["temp_dir"].exists():
                shutil.rmtree(meta["temp_dir"], ignore_errors=True)
                print(f"🧹 清理過期分片上傳: {uid}")
