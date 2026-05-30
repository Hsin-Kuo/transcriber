"""分片上傳 metadata persistence。

取代原本 `src/routers/uploads.py` 的 module-level `_active_uploads` dict，
讓多 worker / 重啟仍能保留進行中的上傳狀態。

設計重點：
- `received` 用 `$addToSet` 原子更新，避免兩個並發 chunk 寫入造成 lost update
- `consume`（給 transcriptions router 接手用）是 atomic `findOneAndDelete`，
  避免「兩個請求同時搶同一個 completed upload」的 race
- 過期清理用 `last_activity_at` 而非 `created_at`，讓慢速大檔上傳不會中途被清掉
- temp_dir 仍存本機 EBS：同一 upload 的所有 chunk 必須打到同一台 EC2（多 EC2 時須 sticky）
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from src.utils.logger import get_logger

log = get_logger(__name__)


class ChunkUploadRepository:
    """Chunk upload metadata CRUD"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.chunk_uploads

    async def create_indexes(self):
        await self.collection.create_index("last_activity_at")
        await self.collection.create_index("user_id")
        log.info("chunk_upload.indexes.created")

    async def init_upload(
        self,
        upload_id: str,
        user_id: str,
        filename: str,
        total_size: int,
        total_chunks: int,
        temp_dir: Path,
    ) -> None:
        now = datetime.now(timezone.utc)
        await self.collection.insert_one({
            "_id": upload_id,
            "user_id": user_id,
            "filename": filename,
            "total_size": total_size,
            "total_chunks": total_chunks,
            "received": [],
            "temp_dir": str(temp_dir),
            "status": "uploading",
            "assembled_path": None,
            "created_at": now,
            "last_activity_at": now,
        })

    async def get(self, upload_id: str) -> Optional[dict]:
        return await self.collection.find_one({"_id": upload_id})

    async def add_chunk(
        self, upload_id: str, user_id: str, chunk_index: int
    ) -> Optional[dict]:
        """Atomic $addToSet：回傳更新後的 doc；不存在或非該 user 則回 None。"""
        return await self.collection.find_one_and_update(
            {"_id": upload_id, "user_id": user_id},
            {
                "$addToSet": {"received": chunk_index},
                "$set": {"last_activity_at": datetime.now(timezone.utc)},
            },
            return_document=ReturnDocument.AFTER,
        )

    async def mark_completed(self, upload_id: str, assembled_path: Path) -> None:
        now = datetime.now(timezone.utc)
        await self.collection.update_one(
            {"_id": upload_id},
            {"$set": {
                "status": "completed",
                "assembled_path": str(assembled_path),
                "completed_at": now,
                "last_activity_at": now,
            }},
        )

    async def consume(self, upload_id: str, user_id: str) -> Optional[dict]:
        """Atomic findOneAndDelete，給 transcriptions router 接手用。

        只有 status=completed 且屬於該 user 才會被消費；其他情況回 None。
        Caller 拿到 doc 後須負責清 temp_dir。
        """
        return await self.collection.find_one_and_delete({
            "_id": upload_id,
            "user_id": user_id,
            "status": "completed",
        })

    async def delete(self, upload_id: str) -> None:
        """強制刪除（驗證失敗等清理情境用）"""
        await self.collection.delete_one({"_id": upload_id})

    async def sweep_expired(self, grace_seconds: int) -> List[dict]:
        """找出 last_activity_at 早於 grace_seconds 前的 doc，刪 doc 並回傳被刪 docs。

        Caller 用回傳的 temp_dir 清磁碟。

        以 find_one_and_delete 逐個處理而非 delete_many：
        - find 與 delete 之間若有 add_chunk 更新 last_activity_at，delete_many 不會
          重新驗證會誤砍剛活躍的 upload
        - 同時也避免回傳「找到但未刪」的 doc 導致 caller 誤刪 temp_dir
        N+1 query 在小批量過期 doc + 5 分鐘間隔下完全可接受。
        """
        cutoff_dt = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)
        expired = await self.collection.find(
            {"last_activity_at": {"$lt": cutoff_dt}}
        ).to_list(length=None)

        deleted: List[dict] = []
        for doc in expired:
            confirmed = await self.collection.find_one_and_delete({
                "_id": doc["_id"],
                "last_activity_at": {"$lt": cutoff_dt},
            })
            if confirmed is not None:
                deleted.append(confirmed)
        return deleted
