"""任務資料存取層"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from bson import ObjectId


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
        updates["updated_at"] = datetime.utcnow()
        result = await self.collection.update_one(
            {"_id": task_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def delete(self, task_id: str, user_id: str) -> bool:
        """刪除任務（權限檢查）"""
        result = await self.collection.delete_one({
            "_id": task_id,
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ]
        })
        return result.deleted_count > 0

    async def find_by_user(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
        status: Optional[str] = None,
        sort: List[tuple] = None
    ) -> List[Dict[str, Any]]:
        """查詢用戶的任務列表

        支援巢狀結構 (user.user_id) 和扁平結構 (user_id)
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
        if status:
            filters["status"] = status

        cursor = self.collection.find(filters).skip(skip).limit(limit).sort(sort)
        return await cursor.to_list(length=limit)

    async def count_by_user(self, user_id: str, status: Optional[str] = None) -> int:
        """計算用戶的任務數量"""
        filters = {
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ]
        }
        if status:
            filters["status"] = status
        return await self.collection.count_documents(filters)

    async def find_active_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """查詢用戶進行中的任務（記憶體優化：限制最多 20 個）"""
        cursor = self.collection.find({
            "$or": [
                {"user.user_id": user_id},  # 巢狀格式
                {"user_id": user_id}  # 扁平格式（向後兼容）
            ],
            "status": {"$in": ["pending", "processing"]}
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
        print("✅ 任務索引已建立")

    async def bulk_update_tags_add(self, task_ids: List[str], user_id: str, tags_to_add: List[str]) -> int:
        """批次添加標籤"""
        result = await self.collection.update_many(
            {
                "_id": {"$in": task_ids},
                "user_id": user_id
            },
            {
                "$addToSet": {"tags": {"$each": tags_to_add}},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return result.modified_count

    async def bulk_update_tags_remove(self, task_ids: List[str], user_id: str, tags_to_remove: List[str]) -> int:
        """批次移除標籤"""
        result = await self.collection.update_many(
            {
                "_id": {"$in": task_ids},
                "user_id": user_id
            },
            {
                "$pullAll": {"tags": tags_to_remove},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        return result.modified_count

    async def bulk_delete(self, task_ids: List[str], user_id: str) -> tuple[int, List[str]]:
        """批次刪除任務（不刪除進行中的任務）"""
        # 先檢查哪些任務可以刪除
        deletable = await self.collection.find({
            "_id": {"$in": task_ids},
            "user_id": user_id,
            "status": {"$nin": ["pending", "processing"]}
        }).to_list(length=None)

        deletable_ids = [task["_id"] for task in deletable]

        if deletable_ids:
            result = await self.collection.delete_many({
                "_id": {"$in": deletable_ids}
            })
            return result.deleted_count, deletable_ids
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

    async def update_content(self, task_id: str, user_id: str, content: str) -> bool:
        """更新任務的轉錄內容（需要權限檢查）"""
        result = await self.collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {"$set": {
                "text_length": len(content),
                "updated_at": datetime.utcnow()
            }}
        )
        return result.modified_count > 0

    async def update_metadata(self, task_id: str, user_id: str, custom_name: Optional[str] = None) -> bool:
        """更新任務的元數據"""
        updates = {"updated_at": datetime.utcnow()}
        if custom_name is not None:
            # 驗證檔名（移除非法字符）
            import re
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', custom_name)
            updates["custom_name"] = safe_name

        result = await self.collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def update_tags(self, task_id: str, user_id: str, tags: List[str]) -> bool:
        """更新任務的標籤"""
        result = await self.collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {"$set": {
                "tags": tags,
                "updated_at": datetime.utcnow()
            }}
        )
        return result.modified_count > 0

    async def update_keep_audio(self, task_id: str, user_id: str, keep_audio: bool) -> bool:
        """更新任務的音檔保留狀態"""
        result = await self.collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {"$set": {
                "keep_audio": keep_audio,
                "updated_at": datetime.utcnow()
            }}
        )
        return result.modified_count > 0

    async def mark_as_cancelled(self, task_id: str, user_id: str) -> bool:
        """標記任務為已取消"""
        result = await self.collection.update_one(
            {"_id": task_id, "user_id": user_id},
            {"$set": {
                "status": "cancelled",
                "updated_at": datetime.utcnow()
            }}
        )
        return result.modified_count > 0

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
        """獲取用戶所有使用過的標籤"""
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags"}},
            {"$sort": {"_id": 1}}
        ]
        result = await self.collection.aggregate(pipeline).to_list(length=None)
        return [doc["_id"] for doc in result if doc["_id"]]

    async def find_tasks_with_audio(self, limit: int = 100) -> List[Dict[str, Any]]:
        """查詢有音檔的任務（僅返回必要欄位，用於清理音檔）

        記憶體優化：只查詢需要的欄位，不載入 segments、transcript 等大型數據

        Args:
            limit: 查詢數量限制（預設 100）

        Returns:
            任務列表，每個任務只包含：task_id, audio_file, completed_at, keep_audio, status
        """
        cursor = self.collection.find(
            {
                "status": "completed",
                "$or": [
                    {"result.audio_file": {"$exists": True, "$ne": None}},  # 巢狀格式
                    {"audio_file": {"$exists": True, "$ne": None}}  # 扁平格式（向後兼容）
                ]
            },
            {
                # 只查詢需要的欄位（projection）
                "_id": 1,
                "task_id": 1,
                "audio_file": 1,  # 扁平格式
                "result.audio_file": 1,  # 巢狀格式
                "keep_audio": 1,
                "completed_at": 1,  # 扁平格式
                "timestamps.completed_at": 1,  # 巢狀格式
                "status": 1
            }
        ).sort("timestamps.completed_at", -1).limit(limit)

        return await cursor.to_list(length=limit)

    async def clear_audio_files_except_kept(self, user_id: str) -> int:
        """清除未勾選保留的音檔記錄"""
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
                    "updated_at": datetime.utcnow()
                }
            }
        )
        return result.modified_count
