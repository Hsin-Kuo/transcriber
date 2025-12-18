"""標籤資料庫操作"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import pytz
import uuid


TZ_UTC8 = pytz.timezone('Asia/Taipei')


def get_current_time() -> str:
    """取得當前時間（UTC+8）"""
    return datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")


class TagRepository:
    """標籤資料庫操作類別"""

    def __init__(self, db):
        self.db = db
        self.collection = db.tags

    async def create(self, user_id: str, name: str, color: Optional[str] = None) -> Dict[str, Any]:
        """建立新標籤

        Args:
            user_id: 使用者 ID
            name: 標籤名稱
            color: 標籤顏色（可選）

        Returns:
            建立的標籤資料
        """
        # 檢查是否已存在同名標籤
        existing = await self.collection.find_one({
            "user_id": user_id,
            "name": name
        })
        if existing:
            raise ValueError(f"標籤 '{name}' 已存在")

        # 獲取當前最大順序
        max_order_tag = await self.collection.find_one(
            {"user_id": user_id},
            sort=[("order", -1)]
        )
        next_order = (max_order_tag["order"] + 1) if max_order_tag else 0

        # 建立標籤
        tag_id = str(uuid.uuid4())
        tag = {
            "tag_id": tag_id,
            "user_id": user_id,
            "name": name,
            "color": color,
            "order": next_order,
            "created_at": get_current_time(),
            "updated_at": None
        }

        result = await self.collection.insert_one(tag)
        tag["_id"] = str(result.inserted_id)

        return tag

    async def get_by_id(self, tag_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """根據 tag_id 獲取標籤（含權限檢查）

        Args:
            tag_id: 標籤 ID
            user_id: 使用者 ID

        Returns:
            標籤資料，若不存在或無權訪問則返回 None
        """
        tag = await self.collection.find_one({
            "tag_id": tag_id,
            "user_id": user_id
        })
        if tag:
            tag["_id"] = str(tag["_id"])
        return tag

    async def get_all_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """獲取使用者的所有標籤（按順序排列）

        Args:
            user_id: 使用者 ID

        Returns:
            標籤列表
        """
        cursor = self.collection.find({"user_id": user_id}).sort("order", 1)
        tags = await cursor.to_list(length=None)

        for tag in tags:
            tag["_id"] = str(tag["_id"])

        return tags

    async def update(self, tag_id: str, user_id: str, name: Optional[str] = None,
                    color: Optional[str] = None) -> bool:
        """更新標籤

        Args:
            tag_id: 標籤 ID
            user_id: 使用者 ID
            name: 新名稱（可選）
            color: 新顏色（可選）

        Returns:
            是否更新成功
        """
        updates = {"updated_at": get_current_time()}

        if name is not None:
            # 檢查新名稱是否與其他標籤衝突
            existing = await self.collection.find_one({
                "user_id": user_id,
                "name": name,
                "tag_id": {"$ne": tag_id}
            })
            if existing:
                raise ValueError(f"標籤 '{name}' 已存在")
            updates["name"] = name

        if color is not None:
            updates["color"] = color

        result = await self.collection.update_one(
            {"tag_id": tag_id, "user_id": user_id},
            {"$set": updates}
        )

        return result.modified_count > 0

    async def delete(self, tag_id: str, user_id: str) -> bool:
        """刪除標籤

        Args:
            tag_id: 標籤 ID
            user_id: 使用者 ID

        Returns:
            是否刪除成功
        """
        result = await self.collection.delete_one({
            "tag_id": tag_id,
            "user_id": user_id
        })

        return result.deleted_count > 0

    async def update_order(self, user_id: str, tag_ids: List[str]) -> int:
        """更新標籤順序

        Args:
            user_id: 使用者 ID
            tag_ids: 標籤 ID 列表（按新順序排列）

        Returns:
            更新的標籤數量
        """
        updated_count = 0
        current_time = get_current_time()

        for index, tag_id in enumerate(tag_ids):
            result = await self.collection.update_one(
                {"tag_id": tag_id, "user_id": user_id},
                {"$set": {"order": index, "updated_at": current_time}}
            )
            updated_count += result.modified_count

        return updated_count

    async def get_by_name(self, user_id: str, name: str) -> Optional[Dict[str, Any]]:
        """根據名稱獲取標籤

        Args:
            user_id: 使用者 ID
            name: 標籤名稱

        Returns:
            標籤資料，若不存在則返回 None
        """
        tag = await self.collection.find_one({
            "user_id": user_id,
            "name": name
        })
        if tag:
            tag["_id"] = str(tag["_id"])
        return tag

    async def rename_tag_in_tasks(self, user_id: str, old_name: str, new_name: str, tasks_collection) -> int:
        """在所有任務中重新命名標籤

        Args:
            user_id: 使用者 ID
            old_name: 舊標籤名稱
            new_name: 新標籤名稱
            tasks_collection: tasks collection

        Returns:
            更新的任務數量
        """
        # 找到所有包含舊標籤的任務
        result = await tasks_collection.update_many(
            {
                "user_id": user_id,
                "tags": old_name
            },
            {
                "$set": {"tags.$[elem]": new_name, "updated_at": get_current_time()}
            },
            array_filters=[{"elem": old_name}]
        )

        return result.modified_count

    async def remove_tag_from_tasks(self, user_id: str, tag_name: str, tasks_collection) -> int:
        """從所有任務中移除標籤

        Args:
            user_id: 使用者 ID
            tag_name: 標籤名稱
            tasks_collection: tasks collection

        Returns:
            更新的任務數量
        """
        result = await tasks_collection.update_many(
            {
                "user_id": user_id,
                "tags": tag_name
            },
            {
                "$pull": {"tags": tag_name},
                "$set": {"updated_at": get_current_time()}
            }
        )

        return result.modified_count
