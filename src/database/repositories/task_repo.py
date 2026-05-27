"""任務資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from bson import ObjectId

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
        """根據 ID 和 user_id 獲取任務（權限檢查）

        支援巢狀結構 (user.user_id) 和扁平結構 (user_id)
        """
        return await self.collection.find_one({
            "_id": task_id,
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ]
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
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ]
        })
        return result.deleted_count > 0

    async def soft_delete(self, task_id: str, user_id: str) -> bool:
        """軟刪除任務（標記為已刪除，保留記錄供統計）"""
        now = get_utc_timestamp()
        result = await self.collection.update_one(
            {
                "_id": task_id,
                "$or": [
                    {"user.user_id": user_id},  # 巢狀格式
                    {"user_id": user_id}  # 扁平格式（向後兼容）
                ]
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

        支援巢狀結構 (user.user_id) 和扁平結構 (user_id)

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

        filters = {
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ]
        }

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
            filters["$and"] = filters.get("$and", [])
            filters["$and"].append({
                "$or": [
                    {"result.audio_file": {"$exists": True, "$ne": None}},
                    {"audio_file": {"$exists": True, "$ne": None}}
                ]
            })

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
        filters = {
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ]
        }

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
            filters["$and"] = filters.get("$and", [])
            filters["$and"].append({
                "$or": [
                    {"result.audio_file": {"$exists": True, "$ne": None}},
                    {"audio_file": {"$exists": True, "$ne": None}}
                ]
            })

        # 默認過濾已刪除的任務
        if not include_deleted:
            filters["deleted"] = {"$ne": True}

        return await self.collection.count_documents(filters)

    async def find_active_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """查詢用戶進行中的任務（記憶體優化：限制最多 20 個）"""
        cursor = self.collection.find({
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ],
            "status": {"$in": ["pending", "processing"]},
            "deleted": {"$ne": True}  # 過濾已刪除的任務
        }).sort("timestamps.created_at", -1).limit(20)
        return await cursor.to_list(length=20)

    async def get_user_total_duration(self, user_id: str, from_date: datetime = None) -> float:
        """計算用戶的總轉錄時長（秒）"""
        filters = {
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式
            ],
            "status": "completed",
            "audio_duration": {"$exists": True}
        }
        if from_date:
            filters["$or"] = [
                {
                    "user.user_id": user_id,
                    "timestamps.created_at": {"$gte": from_date.strftime("%Y-%m-%d %H:%M:%S")}
                },
                {
                    "user_id": user_id,
                    "created_at": {"$gte": from_date.strftime("%Y-%m-%d %H:%M:%S")}
                }
            ]

        pipeline = [
            {"$match": filters},
            {
                "$group": {
                    "_id": None,
                    "total_duration": {"$sum": "$audio_duration"}
                }
            }
        ]

        result = await self.collection.aggregate(pipeline).to_list(1)
        if result:
            return result[0].get("total_duration", 0)
        return 0

    async def count_by_user_since(self, user_id: str, from_date: datetime) -> int:
        """計算用戶從某日期起的任務數量"""
        from_date_str = from_date.strftime("%Y-%m-%d %H:%M:%S")
        return await self.collection.count_documents({
            "$or": [
                {
                    "user.user_id": user_id,
                    "timestamps.created_at": {"$gte": from_date_str}
                },
                {
                    "user_id": user_id,
                    "created_at": {"$gte": from_date_str}
                }
            ]
        })

    async def create_indexes(self):
        """建立索引以提升查詢效能"""
        # task_id 作為 _id，自動有唯一索引
        await self.collection.create_index("user_id")
        await self.collection.create_index([("user_id", 1), ("created_at", -1)])
        await self.collection.create_index([("user_id", 1), ("status", 1)])
        await self.collection.create_index("status")
        await self.collection.create_index("share_token", sparse=True)
        log.info("task.indexes.created")

    async def bulk_update_tags_add(self, task_ids: List[str], user_id: str, tags_to_add: List[str]) -> int:
        """批次添加標籤"""
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "_id": {"$in": task_ids},
                "$or": [
                    {"user.user_id": user_id},  # 巢狀格式
                    {"user_id": user_id}  # 扁平格式（向後兼容）
                ]
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
                "$or": [
                    {"user.user_id": user_id},  # 巢狀格式
                    {"user_id": user_id}  # 扁平格式（向後兼容）
                ]
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
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ],
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
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ],
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
        cursor = self.collection.find({}).sort("created_at", -1).limit(limit)
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

    async def count_by_status(self, user_id: str, status: str) -> int:
        """計算特定狀態的任務數量"""
        return await self.collection.count_documents({
            "user_id": user_id,
            "status": status
        })

    async def count_keep_audio_tasks(self, user_id: str) -> int:
        """計算用戶勾選保留音檔的任務數量"""
        return await self.collection.count_documents({
            "user_id": user_id,
            "keep_audio": True,
            "status": "completed",
            "audio_file": {"$exists": True}
        })

    async def get_all_user_tags(self, user_id: str) -> List[str]:
        """獲取用戶所有使用過的標籤（支援巢狀和扁平結構）"""
        pipeline = [
            {"$match": {
                "$or": [
                    {"user.user_id": user_id},  # 巢狀格式
                    {"user_id": user_id}  # 扁平格式（向後兼容）
                ]
            }},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags"}},
            {"$sort": {"_id": 1}}
        ]
        result = await self.collection.aggregate(pipeline).to_list(length=None)
        return [doc["_id"] for doc in result if doc["_id"]]

    async def find_tasks_with_audio(self, limit: int = 100, user_id: str = None) -> List[Dict[str, Any]]:
        """查詢有音檔的任務（僅返回必要欄位，用於清理音檔）

        記憶體優化：只查詢需要的欄位，不載入 segments、transcript 等大型數據

        Args:
            limit: 查詢數量限制（預設 100）
            user_id: 用戶 ID（如果提供，只查詢該用戶的任務）

        Returns:
            任務列表，每個任務只包含：task_id, audio_file, completed_at, keep_audio, status
        """
        query = {
            "status": "completed",
            "$or": [
                {"result.audio_file": {"$exists": True, "$ne": None}},  # 巢狀格式
                {"audio_file": {"$exists": True, "$ne": None}}  # 扁平格式（向後兼容）
            ]
        }

        # 如果提供了 user_id，添加用戶過濾
        if user_id:
            # 同時匹配字符串和 ObjectId 格式（因為舊資料可能格式不一致）
            from bson import ObjectId
            user_id_conditions = [user_id]

            # 如果 user_id 看起來像 ObjectId，也嘗試 ObjectId 格式
            try:
                if len(user_id) == 24:  # ObjectId 長度
                    user_id_conditions.append(ObjectId(user_id))
            except Exception:
                pass

            user_filter = {
                "$or": [
                    {"user.user_id": {"$in": user_id_conditions}},  # 巢狀格式
                    {"user_id": {"$in": user_id_conditions}}  # 扁平格式（向後兼容）
                ]
            }
            # 合併查詢條件
            query = {
                "$and": [
                    {"status": "completed"},
                    {
                        "$or": [
                            {"result.audio_file": {"$exists": True, "$ne": None}},
                            {"audio_file": {"$exists": True, "$ne": None}}
                        ]
                    },
                    user_filter
                ]
            }

        cursor = self.collection.find(
            query,
            {
                # 只查詢需要的欄位（projection）
                "_id": 1,
                "task_id": 1,
                "audio_file": 1,  # 扁平格式
                "result.audio_file": 1,  # 巢狀格式
                "keep_audio": 1,
                "completed_at": 1,  # 扁平格式
                "timestamps.completed_at": 1,  # 巢狀格式
                "status": 1,
                "user_id": 1,  # 扁平格式
                "user.user_id": 1  # 巢狀格式（用於調試）
            }
        ).sort("timestamps.completed_at", -1).limit(limit)

        tasks = await cursor.to_list(length=limit)

        # 調試日誌
        if user_id:
            sample = [
                {
                    "task_id": task.get("task_id", "unknown")[:8],
                    "user_id": task.get("user", {}).get("user_id") or task.get("user_id", "unknown"),
                }
                for task in tasks[:3]
            ]
            log.debug(
                "task.find_tasks_with_audio",
                user_id=user_id,
                count=len(tasks),
                sample=sample,
            )

        return tasks

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
                "$or": [
                    {"user.user_id": user_id},  # 巢狀格式
                    {"user_id": user_id}  # 扁平格式（向後兼容）
                ]
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
                "$or": [
                    {"user.user_id": user_id},
                    {"user_id": user_id}
                ]
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

    async def clear_audio_files_except_kept(self, user_id: str) -> int:
        """清除未勾選保留的音檔記錄"""
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "user_id": user_id,
                "keep_audio": {"$ne": True},
                "audio_file": {"$exists": True}
            },
            {
                "$unset": {
                    "audio_file": "",
                    "audio_filename": ""
                },
                "$set": {
                    "keep_audio": False,
                    "updated_at": now,
                    "timestamps.updated_at": now  # 同步更新巢狀結構
                }
            }
        )
        return result.modified_count
