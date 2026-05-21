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
from src.utils.logger import get_logger

log = get_logger(__name__)


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
        """建立標籤（idempotent：已存在則回傳既有那筆，不再 raise）。

        改 idempotent 的理由：呼叫者的意圖永遠是「確保這個標籤存在」 —
        系統會自動在 PUT /tasks/.../tags 等地方建標籤，跟前端手動建立會 race，
        此時「已存在」不該對使用者是錯誤。內部 caller 早已 try/except 忽略
        ValueError，這裡 explicit 把那個語義反映到介面上。
        """
        existing_tag = await self.tag_repo.get_by_name(user_id, name)
        if existing_tag:
            return existing_tag

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

        自動同步：若任務中有標籤但 tags 集合缺少對應記錄，會自動補建。

        Args:
            user_id: 用戶 ID

        Returns:
            標籤列表
        """
        tags = await self.tag_repo.get_all_by_user(user_id)

        # 自動同步：補建任務中存在但 tags 集合缺少的標籤
        try:
            task_tags = await self.task_repo.get_all_user_tags(user_id)
            existing_names = {tag["name"] for tag in tags}
            missing = [t for t in task_tags if t not in existing_names]

            if missing:
                for name in missing:
                    try:
                        await self.tag_repo.create(user_id, name)
                    except (ValueError, Exception):
                        pass
                tags = await self.tag_repo.get_all_by_user(user_id)
        except Exception:
            pass

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
        success = await self.tag_repo.update(
            tag_id=tag_id,
            user_id=user_id,
            name=name,
            color=color
        )

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
        success = await self.tag_repo.delete(tag_id, user_id)
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
        log.debug("tag.update_order_start", user_id=user_id, tag_ids=tag_ids)

        # 驗證所有標籤都屬於該用戶
        for tag_id in tag_ids:
            tag = await self.get_tag(user_id, tag_id)
            log.debug("tag.update_order_verify", tag_id=tag_id, found=tag is not None)
            if not tag:
                raise ValueError(f"標籤 {tag_id} 不存在或無權訪問")

        # 更新順序（使用 repository 的 update_order 方法）
        updated_count = await self.tag_repo.update_order(user_id, tag_ids)
        log.debug("tag.update_order_done", updated_count=updated_count)

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
        """重命名所有任務中的標籤（單次原子操作）"""
        await self.task_repo.rename_tag_in_all_user_tasks(user_id, old_name, new_name)

    async def _remove_tag_from_all_tasks(
        self,
        user_id: str,
        tag_name: str
    ) -> None:
        """從所有任務中移除指定標籤（單次原子操作）"""
        await self.task_repo.remove_tag_from_all_user_tasks(user_id, tag_name)
