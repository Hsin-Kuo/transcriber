"""
執行時任務資源容器（記憶體，不持久化）。

進度狀態已搬到 src.services.progress_store.ProgressStore。
這裡剩下的是 orchestration 用的資源：取消標記、臨時目錄、diarization 子進程。
"""

from threading import Lock
from pathlib import Path
from typing import Any, Dict, Optional


class TaskStateStore:
    """執行時任務資源的容器。

    所有寫入操作需持有 lock，外部可透過 `with store.lock:` 使用。
    """

    def __init__(self) -> None:
        self.lock = Lock()

        # 任務的臨時目錄路徑
        self.temp_dirs: Dict[str, Path] = {}

        # 任務取消標記
        self.cancelled: Dict[str, bool] = {}

        # 任務的 Diarization 子進程
        self.diarization_processes: Dict[str, Any] = {}

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
