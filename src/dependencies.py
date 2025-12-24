"""
統一依賴注入模組
提供所有服務和資料庫的依賴注入
"""

from fastapi import Depends
from pathlib import Path

from .database.mongodb import get_database
from .database.repositories.task_repo import TaskRepository
from .database.repositories.tag_repo import TagRepository
from .database.repositories.user_repo import UserRepository
from .services.task_service import TaskService
from .services.tag_service import TagService
from .services.audio_service import AudioService


# ========== Repository 依賴注入 ==========

def get_task_repository(db=Depends(get_database)) -> TaskRepository:
    """獲取 TaskRepository 實例

    Args:
        db: 資料庫實例

    Returns:
        TaskRepository 實例
    """
    return TaskRepository(db)


def get_tag_repository(db=Depends(get_database)) -> TagRepository:
    """獲取 TagRepository 實例

    Args:
        db: 資料庫實例

    Returns:
        TagRepository 實例
    """
    return TagRepository(db)


def get_user_repository(db=Depends(get_database)) -> UserRepository:
    """獲取 UserRepository 實例

    Args:
        db: 資料庫實例

    Returns:
        UserRepository 實例
    """
    return UserRepository(db)


# ========== Service 依賴注入 ==========

def get_tag_service(
    tag_repo: TagRepository = Depends(get_tag_repository),
    task_repo: TaskRepository = Depends(get_task_repository)
) -> TagService:
    """獲取 TagService 實例

    Args:
        tag_repo: TagRepository 實例
        task_repo: TaskRepository 實例

    Returns:
        TagService 實例
    """
    return TagService(tag_repo, task_repo)


def get_audio_service() -> AudioService:
    """獲取 AudioService 實例

    Returns:
        AudioService 實例
    """
    # 使用預設的輸出目錄
    output_dir = Path(__file__).parent.parent / "output"
    return AudioService(output_dir)
