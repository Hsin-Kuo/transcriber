"""
全局狀態管理
職責：提供運行時任務狀態追蹤的全局變數

TaskStateStore 封裝四個 dict + lock，讓呼叫端不需要直接操作全域變數，
也方便在測試中替換為 mock 實例。
"""

from threading import Lock
from pathlib import Path
from typing import Any, Dict, Optional


class TaskStateStore:
    """執行時任務狀態的容器（記憶體，不持久化）

    所有寫入操作需持有 lock，外部可透過 `with store.lock:` 使用。
    """

    def __init__(self) -> None:
        self.lock = Lock()

        # 任務的完整狀態（包含進度、chunks 等運行時資訊）
        self.tasks: Dict[str, Any] = {}

        # 任務的臨時目錄路徑
        self.temp_dirs: Dict[str, Path] = {}

        # 任務取消標記
        self.cancelled: Dict[str, bool] = {}

        # 任務的 Diarization 子進程
        self.diarization_processes: Dict[str, Any] = {}

    # ---- tasks ----

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.tasks.get(task_id)

    def set_task(self, task_id: str, data: Dict[str, Any]) -> None:
        with self.lock:
            self.tasks[task_id] = data

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> None:
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id].update(updates)
            else:
                self.tasks[task_id] = updates

    def delete_task(self, task_id: str) -> None:
        with self.lock:
            self.tasks.pop(task_id, None)

    def has_task(self, task_id: str) -> bool:
        return task_id in self.tasks

    # ---- cancelled ----

    def is_cancelled(self, task_id: str) -> bool:
        return self.cancelled.get(task_id, False)

    def mark_cancelled(self, task_id: str) -> None:
        with self.lock:
            self.cancelled[task_id] = True

    def clear_cancelled(self, task_id: str) -> None:
        with self.lock:
            self.cancelled.pop(task_id, None)

    # ---- temp_dirs ----

    def get_temp_dir(self, task_id: str) -> Optional[Path]:
        return self.temp_dirs.get(task_id)

    def set_temp_dir(self, task_id: str, path: Path) -> None:
        with self.lock:
            self.temp_dirs[task_id] = path

    def clear_temp_dir(self, task_id: str) -> None:
        with self.lock:
            self.temp_dirs.pop(task_id, None)

    # ---- diarization_processes ----

    def get_diarization_process(self, task_id: str) -> Optional[Any]:
        return self.diarization_processes.get(task_id)

    def set_diarization_process(self, task_id: str, proc: Any) -> None:
        with self.lock:
            self.diarization_processes[task_id] = proc

    def clear_diarization_process(self, task_id: str) -> None:
        with self.lock:
            self.diarization_processes.pop(task_id, None)


# ==================== 模組級單例 ====================
store = TaskStateStore()
