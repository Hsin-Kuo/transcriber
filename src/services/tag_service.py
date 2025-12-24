"""
TagService - 標籤管理服務
職責：
- 標籤 CRUD 操作
- 標籤順序管理
- 標籤顏色管理
- 批次標籤操作
"""

from typing import List, Optional, Dict, Any
from datetime import datetime

from src.database.repositories.tag_repo import TagRepository
from src.database.repositories.task_repo import TaskRepository


class TagService:
    """標籤管理服務

    處理標籤的業務邏輯
    """

    def __init__(self, tag_repo: TagRepository, task_repo: TaskRepository):
        """初始化 TagService

        Args:
            tag_repo: TagRepository 實例
            task_repo: TaskRepository 實例
        """
        self.tag_repo = tag_repo
        self.task_repo = task_repo

    async def create_tag(
        self,
        user_id: str,
        name: str,
        color: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """建立新標籤

        Args:
            user_id: 用戶 ID
            name: 標籤名稱
            color: 顏色（可選）
            description: 描述（可選）

        Returns:
            建立的標籤資料

        Raises:
            ValueError: 標籤已存在
        """
        # 檢查標籤是否已存在
        existing_tag = await self.tag_repo.get_by_name(user_id, name)
        if existing_tag:
            raise ValueError(f"標籤 '{name}' 已存在")

        # 建立標籤
        tag = await self.tag_repo.create(user_id, name, color, description)
        return tag

    async def get_tag(self, user_id: str, tag_id: str) -> Optional[Dict[str, Any]]:
        """獲取標籤

        Args:
            user_id: 用戶 ID
            tag_id: 標籤 ID

        Returns:
            標籤資料，不存在則返回 None
        """
        tag = await self.tag_repo.get_by_id(tag_id, user_id)
        return tag

    async def get_all_tags(self, user_id: str) -> List[Dict[str, Any]]:
        """獲取用戶的所有標籤（按順序排序）

        Args:
            user_id: 用戶 ID

        Returns:
            標籤列表
        """
        tags = await self.tag_repo.get_all_by_user(user_id)
        return tags

    async def update_tag(
        self,
        user_id: str,
        tag_id: str,
        name: Optional[str] = None,
        color: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """更新標籤

        Args:
            user_id: 用戶 ID
            tag_id: 標籤 ID
            name: 新名稱（可選）
            color: 新顏色（可選）
            description: 新描述（可選）

        Returns:
            更新後的標籤資料

        Raises:
            ValueError: 標籤不存在或無權訪問
        """
        # 權限驗證
        tag = await self.get_tag(user_id, tag_id)
        if not tag:
            raise ValueError("標籤不存在或無權訪問")

        # 如果要重命名，需要更新所有使用此標籤的任務
        old_name = tag.get("name")
        if name and name != old_name:
            # 檢查新名稱是否已存在
            existing = await self.tag_repo.get_by_name(user_id, name)
            if existing and str(existing.get("tag_id")) != tag_id:
                raise ValueError(f"標籤 '{name}' 已存在")

            # 更新所有任務中的標籤
            await self._rename_tag_in_tasks(user_id, old_name, name)

        # 更新標籤
        updates = {}
        if name is not None:
            updates["name"] = name
        if color is not None:
            updates["color"] = color
        if description is not None:
            updates["description"] = description

        if updates:
            updates["updated_at"] = datetime.utcnow()
            success = await self.tag_repo.update(tag_id, updates)
            if success:
                return await self.tag_repo.get_by_id(tag_id, user_id)

        return tag

    async def delete_tag(self, user_id: str, tag_id: str) -> bool:
        """刪除標籤

        Args:
            user_id: 用戶 ID
            tag_id: 標籤 ID

        Returns:
            是否刪除成功

        Raises:
            ValueError: 標籤不存在或無權訪問
        """
        # 權限驗證
        tag = await self.get_tag(user_id, tag_id)
        if not tag:
            raise ValueError("標籤不存在或無權訪問")

        # 從所有任務中移除此標籤
        tag_name = tag.get("name")
        await self._remove_tag_from_all_tasks(user_id, tag_name)

        # 刪除標籤
        success = await self.tag_repo.delete(tag_id)
        return success

    async def update_tag_order(
        self,
        user_id: str,
        tag_ids: List[str]
    ) -> bool:
        """更新標籤順序

        Args:
            user_id: 用戶 ID
            tag_ids: 標籤 ID 列表（按新順序）

        Returns:
            是否更新成功
        """
        # 驗證所有標籤都屬於該用戶
        for tag_id in tag_ids:
            tag = await self.get_tag(user_id, tag_id)
            if not tag:
                raise ValueError(f"標籤 {tag_id} 不存在或無權訪問")

        # 更新順序（使用 repository 的 update_order 方法）
        updated_count = await self.tag_repo.update_order(user_id, tag_ids)

        return updated_count > 0

    async def add_tags_to_tasks(
        self,
        user_id: str,
        task_ids: List[str],
        tag_names: List[str]
    ) -> int:
        """批次為任務添加標籤

        Args:
            user_id: 用戶 ID
            task_ids: 任務 ID 列表
            tag_names: 標籤名稱列表

        Returns:
            成功更新的任務數量
        """
        updated_count = 0

        for task_id in task_ids:
            # 權限驗證
            task = await self.task_repo.get_by_id_and_user(task_id, user_id)
            if not task:
                continue

            # 獲取現有標籤
            current_tags = task.get("tags", [])

            # 添加新標籤（去重）
            new_tags = list(set(current_tags + tag_names))

            # 更新任務
            success = await self.task_repo.update(task_id, {"tags": new_tags})
            if success:
                updated_count += 1

        return updated_count

    async def remove_tags_from_tasks(
        self,
        user_id: str,
        task_ids: List[str],
        tag_names: List[str]
    ) -> int:
        """批次從任務移除標籤

        Args:
            user_id: 用戶 ID
            task_ids: 任務 ID 列表
            tag_names: 標籤名稱列表

        Returns:
            成功更新的任務數量
        """
        updated_count = 0

        for task_id in task_ids:
            # 權限驗證
            task = await self.task_repo.get_by_id_and_user(task_id, user_id)
            if not task:
                continue

            # 獲取現有標籤
            current_tags = task.get("tags", [])

            # 移除指定標籤
            new_tags = [tag for tag in current_tags if tag not in tag_names]

            # 更新任務
            success = await self.task_repo.update(task_id, {"tags": new_tags})
            if success:
                updated_count += 1

        return updated_count

    async def get_tag_statistics(self, user_id: str) -> List[Dict[str, Any]]:
        """獲取標籤統計資訊

        Args:
            user_id: 用戶 ID

        Returns:
            標籤統計列表，包含每個標籤的使用次數
        """
        # 獲取所有標籤
        tags = await self.get_all_tags(user_id)

        # 統計每個標籤的使用次數
        stats = []
        for tag in tags:
            tag_name = tag.get("name")
            count = await self.task_repo.count_tasks_by_tag(user_id, tag_name)
            stats.append({
                **tag,
                "usage_count": count
            })

        return stats

    # ========== 私有輔助方法 ==========

    async def _rename_tag_in_tasks(
        self,
        user_id: str,
        old_name: str,
        new_name: str
    ) -> None:
        """重命名所有任務中的標籤

        Args:
            user_id: 用戶 ID
            old_name: 舊標籤名稱
            new_name: 新標籤名稱
        """
        # 獲取所有包含此標籤的任務
        tasks = await self.task_repo.find_by_tag(user_id, old_name)

        for task in tasks:
            task_id = str(task.get("_id") or task.get("task_id"))
            current_tags = task.get("tags", [])

            # 替換標籤名稱
            new_tags = [new_name if tag == old_name else tag for tag in current_tags]

            # 更新任務
            await self.task_repo.update(task_id, {"tags": new_tags})

    async def _remove_tag_from_all_tasks(
        self,
        user_id: str,
        tag_name: str
    ) -> None:
        """從所有任務中移除指定標籤

        Args:
            user_id: 用戶 ID
            tag_name: 標籤名稱
        """
        # 獲取所有包含此標籤的任務
        tasks = await self.task_repo.find_by_tag(user_id, tag_name)

        for task in tasks:
            task_id = str(task.get("_id") or task.get("task_id"))
            current_tags = task.get("tags", [])

            # 移除標籤
            new_tags = [tag for tag in current_tags if tag != tag_name]

            # 更新任務
            await self.task_repo.update(task_id, {"tags": new_tags})
