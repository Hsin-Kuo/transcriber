"""任務資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any, List

from ...utils.time_utils import get_utc_timestamp
from src.utils.logger import get_logger

log = get_logger(__name__)


# 允許的查詢參數值（白名單）
ALLOWED_STATUSES = {"pending", "processing", "completed", "failed", "cancelled"}
ALLOWED_TASK_TYPES = {"paragraph", "subtitle"}


def _validate_status(status: Optional[str]) -> Optional[str]:
    """驗證 status 參數在白名單內"""
    if status is None:
        return None
    if status not in ALLOWED_STATUSES:
        return None  # 無效值視為不篩選
    return status


def _validate_task_type(task_type: Optional[str]) -> Optional[str]:
    """驗證 task_type 參數在白名單內"""
    if task_type is None:
        return None
    if task_type not in ALLOWED_TASK_TYPES:
        return None  # 無效值視為不篩選
    return task_type


class TaskRepository:
    """任務資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.tasks

    @staticmethod
    def owned_by(user_id: str) -> Dict[str, Any]:
        """一筆 Task 屬於某 user 的查詢條件（單一真實來源）。

        tasks collection 一律巢狀 `user.user_id`；create path（intake_service）
        只寫巢狀，2026-06 probe 確認 prod 136 筆全巢狀、0 筆扁平，故舊扁平
        `user_id` 相容分支已移除。所有 ownership 查詢都應拼接此條件，不要在
        呼叫端手寫 `user.user_id`。
        """
        return {"user.user_id": user_id}

    async def create(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立新任務"""
        result = await self.collection.insert_one(task_data)
        task_data["_id"] = result.inserted_id
        return task_data

    async def get_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根據 ID 獲取任務"""
        return await self.collection.find_one({"_id": task_id})

    async def count_all_by_status(self, status: str) -> int:
        """計算全系統指定 status 的任務數量（LocalDispatch 並發閘門用）。"""
        return await self.collection.count_documents({"status": status})

    async def get_oldest_pending(self) -> Optional[Dict[str, Any]]:
        """取最舊的 pending 任務（依建立時間升序）；無則回 None。"""
        return await self.collection.find_one(
            {"status": "pending"},
            sort=[("timestamps.created_at", 1)],
        )

    async def get_by_id_and_user(self, task_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """根據 ID 和 user_id 獲取任務（權限檢查）"""
        return await self.collection.find_one({
            "_id": task_id,
            **self.owned_by(user_id),
        })

    async def update(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """更新任務資料"""
        now = get_utc_timestamp()
        updates["updated_at"] = now
        updates["timestamps.updated_at"] = now  # 同步更新巢狀結構
        result = await self.collection.update_one(
            {"_id": task_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def delete(self, task_id: str, user_id: str) -> bool:
        """刪除任務（權限檢查）- 真正刪除記錄"""
        result = await self.collection.delete_one({
            "_id": task_id,
            **self.owned_by(user_id),
        })
        return result.deleted_count > 0

    async def soft_delete(self, task_id: str, user_id: str) -> bool:
        """軟刪除任務（標記為已刪除，保留記錄供統計）"""
        now = get_utc_timestamp()
        result = await self.collection.update_one(
            {
                "_id": task_id,
                **self.owned_by(user_id),
            },
            {
                "$set": {
                    "deleted": True,
                    "deleted_at": now,
                    "updated_at": now,
                    "timestamps.updated_at": now  # 同步更新巢狀結構
                }
            }
        )
        return result.modified_count > 0

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        status_nin: Optional[List[str]] = None,
        task_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        sort: List[tuple] = None,
        include_deleted: bool = False,
        has_audio: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """查詢用戶的任務列表

        Args:
            status_nin: 排除指定 status 列表（白名單驗證；status 已指定時忽略）
            include_deleted: 是否包含已刪除的任務（默認 False，過濾已刪除）
            task_type: 過濾任務類型（可選：paragraph, subtitle）
            tags: 過濾標籤列表（AND 邏輯，任務必須包含所有指定的標籤）
            has_audio: 過濾是否有音檔（可選：True 只顯示有音檔的任務）
        """
        if sort is None:
            # 巢狀格式的排序欄位
            sort = [("timestamps.created_at", -1)]

        filters = dict(self.owned_by(user_id))

        # 驗證並應用 status 篩選（白名單）；status 與 status_nin 互斥，status 優先
        validated_status = _validate_status(status)
        if validated_status:
            filters["status"] = validated_status
        elif status_nin:
            validated_nin = [s for s in status_nin if s in ALLOWED_STATUSES]
            if validated_nin:
                filters["status"] = {"$nin": validated_nin}

        # 驗證並應用 task_type 篩選（白名單）
        validated_task_type = _validate_task_type(task_type)
        if validated_task_type:
            filters["task_type"] = validated_task_type

        # 標籤篩選（AND 邏輯：任務必須包含所有指定的標籤）
        if tags and len(tags) > 0:
            filters["tags"] = {"$all": tags}

        # 音檔篩選
        if has_audio is True:
            filters["result.audio_file"] = {"$exists": True, "$ne": None}

        # 默認過濾已刪除的任務
        if not include_deleted:
            filters["deleted"] = {"$ne": True}

        cursor = self.collection.find(filters).skip(skip).limit(limit).sort(sort)
        return await cursor.to_list(length=limit)

    async def count_by_user(self, user_id: str, status: Optional[str] = None, task_type: Optional[str] = None, tags: Optional[List[str]] = None, include_deleted: bool = False, has_audio: Optional[bool] = None) -> int:
        """計算用戶的任務數量

        Args:
            include_deleted: 是否包含已刪除的任務（默認 False，過濾已刪除）
            task_type: 過濾任務類型（可選：paragraph, subtitle）
            tags: 過濾標籤列表（AND 邏輯，任務必須包含所有指定的標籤）
            has_audio: 過濾是否有音檔（可選：True 只顯示有音檔的任務）
        """
        filters = dict(self.owned_by(user_id))

        # 驗證並應用 status 篩選（白名單）
        validated_status = _validate_status(status)
        if validated_status:
            filters["status"] = validated_status

        # 驗證並應用 task_type 篩選（白名單）
        validated_task_type = _validate_task_type(task_type)
        if validated_task_type:
            filters["task_type"] = validated_task_type

        # 標籤篩選（AND 邏輯：任務必須包含所有指定的標籤）
        if tags and len(tags) > 0:
            filters["tags"] = {"$all": tags}

        # 音檔篩選
        if has_audio is True:
            filters["result.audio_file"] = {"$exists": True, "$ne": None}

        # 默認過濾已刪除的任務
        if not include_deleted:
            filters["deleted"] = {"$ne": True}

        return await self.collection.count_documents(filters)

    async def find_active_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """查詢用戶進行中的任務（記憶體優化：限制最多 20 個）"""
        cursor = self.collection.find({
            **self.owned_by(user_id),
            "status": {"$in": ["pending", "processing"]},
            "deleted": {"$ne": True}  # 過濾已刪除的任務
        }).sort("timestamps.created_at", -1).limit(20)
        return await cursor.to_list(length=20)

    async def count_active_by_user(self, user_id: str) -> int:
        """計算用戶進行中（pending / processing）的任務數量。"""
        return await self.collection.count_documents({
            **self.owned_by(user_id),
            "status": {"$in": ["pending", "processing"]},
            "deleted": {"$ne": True},
        })

    async def count_by_user_since(self, user_id: str, from_date: datetime) -> int:
        """計算用戶從某日期起的任務數量"""
        from_date_str = from_date.strftime("%Y-%m-%d %H:%M:%S")
        return await self.collection.count_documents({
            **self.owned_by(user_id),
            "timestamps.created_at": {"$gte": from_date_str},
        })

    async def create_indexes(self):
        """建立索引以提升查詢效能

        索引欄位對齊實際查詢路徑（巢狀）：ownership 用 `user.user_id`、
        排序用 `timestamps.created_at`。舊的扁平 `user_id` / `created_at`
        索引已無查詢命中，可由 ops 手動 dropIndex 清掉（本層不自動刪）。
        """
        # task_id 作為 _id，自動有唯一索引
        await self.collection.create_index("user.user_id")
        await self.collection.create_index([("user.user_id", 1), ("timestamps.created_at", -1)])
        await self.collection.create_index([("user.user_id", 1), ("status", 1)])
        await self.collection.create_index("status")
        await self.collection.create_index("share_token", sparse=True)
        log.info("task.indexes.created")

    async def bulk_update_tags_add(self, task_ids: List[str], user_id: str, tags_to_add: List[str]) -> int:
        """批次添加標籤"""
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "_id": {"$in": task_ids},
                **self.owned_by(user_id),
            },
            {
                "$addToSet": {"tags": {"$each": tags_to_add}},
                "$set": {
                    "updated_at": now,
                    "timestamps.updated_at": now  # 同步更新巢狀結構
                }
            }
        )
        return result.modified_count

    async def bulk_update_tags_remove(self, task_ids: List[str], user_id: str, tags_to_remove: List[str]) -> int:
        """批次移除標籤"""
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "_id": {"$in": task_ids},
                **self.owned_by(user_id),
            },
            {
                "$pullAll": {"tags": tags_to_remove},
                "$set": {
                    "updated_at": now,
                    "timestamps.updated_at": now  # 同步更新巢狀結構
                }
            }
        )
        return result.modified_count

    async def bulk_delete(self, task_ids: List[str], user_id: str) -> tuple[int, List[str]]:
        """批次刪除任務（不刪除進行中的任務）- 真正刪除記錄"""
        # 先檢查哪些任務可以刪除
        deletable = await self.collection.find({
            "_id": {"$in": task_ids},
            **self.owned_by(user_id),
            "status": {"$nin": ["pending", "processing"]}
        }).to_list(length=None)

        deletable_ids = [task["_id"] for task in deletable]

        if deletable_ids:
            result = await self.collection.delete_many({
                "_id": {"$in": deletable_ids}
            })
            return result.deleted_count, deletable_ids
        return 0, []

    async def bulk_soft_delete(self, task_ids: List[str], user_id: str) -> tuple[int, List[str]]:
        """批次軟刪除任務（標記為已刪除，不刪除進行中的任務）"""
        # 先檢查哪些任務可以刪除
        deletable = await self.collection.find({
            "_id": {"$in": task_ids},
            **self.owned_by(user_id),
            "status": {"$nin": ["pending", "processing"]},
            "deleted": {"$ne": True}  # 排除已刪除的任務
        }).to_list(length=None)

        deletable_ids = [task["_id"] for task in deletable]

        if deletable_ids:
            now = get_utc_timestamp()
            result = await self.collection.update_many(
                {"_id": {"$in": deletable_ids}},
                {
                    "$set": {
                        "deleted": True,
                        "deleted_at": now,
                        "updated_at": now,
                        "timestamps.updated_at": now  # 同步更新巢狀結構
                    }
                }
            )
            return result.modified_count, deletable_ids
        return 0, []

    async def get_all_tasks(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """獲取所有任務（管理員用）"""
        cursor = self.collection.find({}).sort("timestamps.created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def insert_many(self, tasks: List[Dict[str, Any]]) -> int:
        """批次插入任務（用於遷移）"""
        if not tasks:
            return 0
        result = await self.collection.insert_many(tasks, ordered=False)
        return len(result.inserted_ids)

    # ========== 已移除的業務邏輯方法 ==========
    # 以下方法已移至 TaskService，以符合三層架構原則：
    # - update_content() -> TaskService.update_transcription_content()
    # - update_metadata() -> TaskService.update_task_metadata()
    # - update_tags() -> TaskService.update_task_tags()
    # - update_keep_audio() -> TaskService.update_keep_audio()
    # - mark_as_cancelled() -> TaskService.mark_task_as_cancelled()
    #
    # Repository 層現在只負責純資料存取操作，不包含業務邏輯（如驗證、計算、轉換）

    async def get_audio_refs_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """取得用戶所有任務的音檔引用（帳號刪除清理音檔用）。

        只投影 _id 與音檔路徑，不載入轉錄/segments 等大型欄位。
        """
        return await self.collection.find(
            self.owned_by(user_id),
            {"_id": 1, "result.audio_file": 1},
        ).to_list(length=None)

    async def delete_all_for_user(self, user_id: str) -> int:
        """硬刪除某 user 的所有任務。回傳刪除筆數。"""
        result = await self.collection.delete_many(self.owned_by(user_id))
        return result.deleted_count

    async def anonymize_all_for_user(self, user_id: str, *, now: int) -> int:
        """帳號刪除：把某 user 的所有任務去識別化保留（供統計/稽核）。

        清除 PII 與內容參照（email / 自訂名 / 標籤 / 檔名 / 音檔參照），
        保留統計所需的非個資欄位（user_id 假名鍵、status、task_type、
        models、stats、timestamps、字數統計、config）。實際逐字內容
        （transcriptions/segments/summaries）與音檔另由呼叫端硬刪。
        回傳更新筆數。
        """
        result = await self.collection.update_many(
            self.owned_by(user_id),
            {
                "$set": {
                    "user.user_email": None,
                    "custom_name": None,
                    "tags": [],
                    "file.filename": None,
                    "result.audio_file": None,
                    "result.audio_filename": None,
                    "anonymized_at": now,
                    "updated_at": now,
                }
            },
        )
        return result.modified_count

    async def get_all_user_tags(self, user_id: str) -> List[str]:
        """獲取用戶所有使用過的標籤"""
        pipeline = [
            {"$match": self.owned_by(user_id)},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags"}},
            {"$sort": {"_id": 1}}
        ]
        result = await self.collection.aggregate(pipeline).to_list(length=None)
        return [doc["_id"] for doc in result if doc["_id"]]

    async def remove_tag_from_all_user_tasks(self, user_id: str, tag_name: str) -> int:
        """從用戶所有任務中移除指定標籤（單次原子操作）

        使用 $pull 一次性從所有符合條件的 task.tags 陣列移除該值，
        相較於 find 後逐筆 update，避免 N+1 查詢且具原子性。

        Args:
            user_id: 用戶 ID
            tag_name: 要移除的標籤名稱

        Returns:
            被更新的任務數量
        """
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "tags": tag_name,
                **self.owned_by(user_id),
            },
            {
                "$pull": {"tags": tag_name},
                "$set": {
                    "updated_at": now,
                    "timestamps.updated_at": now
                }
            }
        )
        return result.modified_count

    async def rename_tag_in_all_user_tasks(
        self,
        user_id: str,
        old_name: str,
        new_name: str
    ) -> int:
        """重新命名用戶所有任務中的指定標籤（單次原子操作）

        使用 aggregation pipeline 在 update_many 內單步完成：
        過濾掉 old_name，再用 $setUnion 加入 new_name（自動去重）。
        需要 MongoDB 4.2+。

        Args:
            user_id: 用戶 ID
            old_name: 舊標籤名稱
            new_name: 新標籤名稱

        Returns:
            被更新的任務數量
        """
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "tags": old_name,
                **self.owned_by(user_id),
            },
            [
                {
                    "$set": {
                        "tags": {
                            "$setUnion": [
                                {
                                    "$filter": {
                                        "input": "$tags",
                                        "cond": {"$ne": ["$$this", old_name]}
                                    }
                                },
                                [new_name]
                            ]
                        },
                        "updated_at": now,
                        "timestamps.updated_at": now
                    }
                }
            ]
        )
        return result.modified_count
