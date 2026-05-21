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
from .services.summary_service import SummaryService


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


def get_summary_service(db=Depends(get_database)) -> SummaryService:
    """獲取 SummaryService 實例（每請求建立；無狀態）"""
    return SummaryService(db)


# ========== TaskService 單例 ==========
# TaskService 持有執行期狀態（取消標記 / temp_dir / diarization 進程），
# 必須是單例——main.py startup 呼叫 init_task_service() 建立，routers 透過
# Depends(get_task_service) 取同一實例。

_task_service_singleton: TaskService = None


def init_task_service(db, progress_store, state_store=None) -> TaskService:
    """初始化全域 TaskService 單例（main.py startup 呼叫一次）。

    Args:
        db: 資料庫實例
        progress_store: ProgressStore 實例（進度的單一介面）
        state_store: TaskStateStore 實例（未提供時使用模組級單例）
    """
    global _task_service_singleton
    from .utils.shared_state import store as _default_store
    _task_service_singleton = TaskService(
        TaskRepository(db),
        progress_store=progress_store,
        state_store=state_store or _default_store,
    )
    return _task_service_singleton


def get_task_service() -> TaskService:
    """依賴注入：獲取 TaskService 單例（確保執行期狀態共享）。

    Raises:
        RuntimeError: 若尚未 init（main.py startup 應呼叫 init_task_service()）
    """
    if _task_service_singleton is None:
        raise RuntimeError("TaskService 尚未初始化，請先調用 init_task_service()")
    return _task_service_singleton
