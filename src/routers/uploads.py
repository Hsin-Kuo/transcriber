"""分片上傳路由 — 解決 Cloudflare 100MB 上傳限制。

metadata 存於 MongoDB `chunk_uploads` collection（透過 ChunkUploadRepository）。
chunk 檔案仍存本機 EBS（temp_dir）：同一 upload 的所有 chunk 必須打到同一台
EC2，多 EC2 部署時要做 sticky session（依 upload_id）。
"""
import os
import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from ..auth.dependencies import get_current_user
from ..database.mongodb import MongoDB
from ..database.repositories.chunk_upload_repo import ChunkUploadRepository
from ..services.utils.audio_validator import (
    validate_filename_extension,
    validate_magic_bytes,
)
from ..utils.config_loader import get_temp_dir
from ..utils.logger import get_logger

router = APIRouter(prefix="/uploads", tags=["Uploads"])
log = get_logger(__name__)

CHUNK_SIZE = 90 * 1024 * 1024  # 90 MB — 單片上限
# 單檔上限：以環境變數 MAX_UPLOAD_SIZE_MB 設定（預設 3072 MB = 3 GB）
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "3072"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
UPLOAD_EXPIRY_SECONDS = 10800  # 3 小時無活動即清理（大檔上傳較慢）
CLEANUP_INTERVAL_SECONDS = 300  # 每 5 分鐘掃一次

# 同一 user 最多同時 N 條 chunk 在後端寫磁碟。
# 對齊前端建議的並行度（Phase 2.1：3 條），避免 disk I/O / RAM 被單一 user 吃滿。
# 多 worker 模式下每 worker 各有獨立字典 → 實際總並行 = N × workers（可接受）。
USER_CHUNK_CONCURRENCY = 3
_user_chunk_semaphores: dict[str, asyncio.Semaphore] = {}

# 整台機器（單一 process）最多同時 N 條 chunk 在寫磁碟。
# t3.small EBS gp3 baseline 125 MB/s，每條 streaming 約 30-60 MB/s 上限，
# 取 10 留 headroom 給其他磁碟 I/O（log、Mongo、組裝完整檔案）。
# 多 worker 模式下總並行 = N × workers，要嚴格全域控制只能上 Redis。
GLOBAL_CHUNK_CONCURRENCY = 10
_global_chunk_semaphore = asyncio.Semaphore(GLOBAL_CHUNK_CONCURRENCY)


def _get_user_chunk_semaphore(user_id: str) -> asyncio.Semaphore:
    """Lazy-init per-user semaphore。

    asyncio 是 cooperative，這段純同步（無 await 切點），不會 race。
    字典 entries 不主動回收：物件極小，單 instance 累積上限就是 unique user 數。
    """
    sem = _user_chunk_semaphores.get(user_id)
    if sem is None:
        sem = asyncio.Semaphore(USER_CHUNK_CONCURRENCY)
        _user_chunk_semaphores[user_id] = sem
    return sem


def _repo() -> ChunkUploadRepository:
    return ChunkUploadRepository(MongoDB.get_db())


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
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"檔案超過 {MAX_UPLOAD_SIZE_MB}MB 上限",
        )

    validate_filename_extension(filename)

    total_chunks = (total_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    upload_id = str(uuid.uuid4())
    temp_dir = get_temp_dir(prefix="chunk_")

    await _repo().init_upload(
        upload_id=upload_id,
        user_id=str(current_user["_id"]),
        filename=filename,
        total_size=total_size,
        total_chunks=total_chunks,
        temp_dir=temp_dir,
    )

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
    repo = _repo()
    user_id = str(current_user["_id"])
    meta = await repo.get(upload_id)
    if not meta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload_id 不存在或已過期")

    if meta["user_id"] != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "無權操作此上傳")

    if chunk_index < 0 or chunk_index >= meta["total_chunks"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"chunk_index 超出範圍 (0-{meta['total_chunks'] - 1})",
        )

    # 驗證通過才搶 semaphore：4xx 不消耗配額，能快速回客戶端。
    # 雙層 semaphore：
    #   外層 user — 同 user 卡這層時不占整機名額（user 11 的第 1 條不會被 user 1 的第 4 條擋）
    #   內層 global — 整機 disk I/O 上限，防多用戶突發流量沖垮磁碟
    async with _get_user_chunk_semaphore(user_id):
        async with _global_chunk_semaphore:
            # 寫入 chunk 檔案
            # streaming 1MB-per-iter，避免 90MB 一次進 RAM + sync write_bytes 卡 event loop
            chunk_path = Path(meta["temp_dir"]) / f"chunk_{chunk_index:04d}"
            async with aiofiles.open(chunk_path, "wb") as out:
                while True:
                    buf = await file.read(1024 * 1024)
                    if not buf:
                        break
                    await out.write(buf)

            # 原子 $addToSet 寫入 received，回傳更新後的 doc
            updated = await repo.add_chunk(upload_id, user_id, chunk_index)
            received_count = len(updated["received"]) if updated else 0

    return {
        "chunk_index": chunk_index,
        "received": received_count,
        "total_chunks": meta["total_chunks"],
    }


@router.post("/{upload_id}/complete")
async def complete_upload(
    upload_id: str,
    current_user: dict = Depends(get_current_user),
):
    """驗證所有 chunk 到齊，組裝成完整檔案"""
    repo = _repo()
    meta = await repo.get(upload_id)
    if not meta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload_id 不存在或已過期")

    if meta["user_id"] != str(current_user["_id"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "無權操作此上傳")

    received = set(meta.get("received") or [])
    missing = set(range(meta["total_chunks"])) - received
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"缺少 {len(missing)} 個 chunk: {sorted(missing)[:10]}",
        )

    temp_dir = Path(meta["temp_dir"])
    assembled_path = temp_dir / meta["filename"]

    # 組裝：sync I/O 在 threadpool 跑，避免卡 event loop
    await asyncio.to_thread(_assemble_chunks, temp_dir, assembled_path, meta["total_chunks"])

    # 組裝完成後驗證 magic bytes（防止上傳偽造副檔名的非音檔）
    try:
        validate_magic_bytes(assembled_path)
    except HTTPException:
        # 驗證失敗：清理已組裝檔案與整個 upload，讓使用者重傳
        if assembled_path.exists():
            assembled_path.unlink()
        shutil.rmtree(temp_dir, ignore_errors=True)
        await repo.delete(upload_id)
        raise

    await repo.mark_completed(upload_id, assembled_path)

    return {
        "status": "assembled",
        "upload_id": upload_id,
        "filename": meta["filename"],
        "size": assembled_path.stat().st_size,
    }


def _assemble_chunks(temp_dir: Path, assembled_path: Path, total_chunks: int) -> None:
    """把 N 個 chunk 串接成完整檔。Sync I/O，由 to_thread 包覆。"""
    with assembled_path.open("wb") as out:
        for i in range(total_chunks):
            chunk_path = temp_dir / f"chunk_{i:04d}"
            out.write(chunk_path.read_bytes())
            chunk_path.unlink()


# ── 給其他 router 用的 API ─────────────────────────────

async def consume_upload(upload_id: str, user_id: str) -> Optional[dict]:
    """Atomic：取走已完成的上傳並從 DB 刪除，回傳 meta 或 None。

    比舊版 `get_upload_meta + remove_upload` 安全：findOneAndDelete 是原子操作，
    兩個並發請求不會雙重 consume 同一個 upload。

    回傳 dict 內含：
        - user_id (str)
        - filename (str)
        - temp_dir (Path)
        - assembled_path (Path)
    Caller 拿到非 None 後，須負責清 temp_dir。
    """
    doc = await ChunkUploadRepository(MongoDB.get_db()).consume(upload_id, user_id)
    if not doc:
        return None
    return {
        "user_id": doc["user_id"],
        "filename": doc["filename"],
        "temp_dir": Path(doc["temp_dir"]),
        "assembled_path": Path(doc["assembled_path"]),
    }


# ── 背景清理任務 ─────────────────────────────

async def periodic_chunk_upload_cleanup(
    db,
    interval_seconds: int = CLEANUP_INTERVAL_SECONDS,
    grace_seconds: int = UPLOAD_EXPIRY_SECONDS,
) -> None:
    """清掃超過 grace_seconds 無活動的 chunk uploads（含完成未消費的）。

    與舊版差異：
    - 舊版只清未完成的 → completed-but-never-consumed 會永遠留 temp_dir
    - 新版以 last_activity_at 為準，3 小時無活動就清，不論是否 completed
    - rmtree 跑 threadpool（避免阻塞 event loop）
    """
    repo = ChunkUploadRepository(db)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            expired = await repo.sweep_expired(grace_seconds)
            for doc in expired:
                td = Path(doc.get("temp_dir", ""))
                if td.exists():
                    await asyncio.to_thread(shutil.rmtree, td, ignore_errors=True)
            if expired:
                log.info("chunk_upload.sweep.completed", count=len(expired))
        except Exception as e:
            log.error("chunk_upload.sweep.failed", error=str(e), exc_info=True)
