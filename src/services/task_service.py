"""
TaskService - 任務狀態管理服務
職責：
- 任務 CRUD 操作
- 封裝全域狀態（記憶體中的運行時狀態）
- 權限驗證
- 取消任務邏輯
- 清理任務記憶體
- 完整刪除 workflow（soft-delete + 關聯文件/文檔清理）
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime, timezone, timedelta
import shutil
import asyncio
import gc
import os

from src.database.repositories.task_repo import TaskRepository
from src.utils.time_utils import get_current_time, get_utc_timestamp
from src.utils.shared_state import TaskStateStore
from src.services.progress_store import Phase, ProgressStore
from src.utils.logger import get_logger

log = get_logger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    log.warning("task.psutil.unavailable")

# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))


class TaskService:
    """任務狀態管理服務 — DB CRUD + ProgressStore 進度 + 取消/temp/diarization process 資源管理"""

    def __init__(
        self,
        task_repo: TaskRepository,
        progress_store: ProgressStore,
        state_store: TaskStateStore = None,
    ):
        """初始化 TaskService

        Args:
            task_repo: TaskRepository 實例
            progress_store: ProgressStore（進度寫入/讀出的單一介面）
            state_store: TaskStateStore 實例（持有取消標記/臨時目錄/diarization 進程；未提供時建立新的）
        """
        self.task_repo = task_repo
        self.progress_store = progress_store
        self._store = state_store if state_store is not None else TaskStateStore()

        # orchestration 用資源（不是 progress；保留在 _store）
        self._cancelled_tasks = self._store.cancelled
        self._temp_dirs = self._store.temp_dirs
        self._diarization_processes = self._store.diarization_processes
        self._lock = self._store.lock

    async def create_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立新任務"""
        task = await self.task_repo.create(task_data)
        task_id = str(task["task_id"])
        self.progress_store.set_phase(
            task_id, Phase.PREPARATION, 0.0, message="初始化中..."
        )
        return task

    async def get_task(self, task_id: str, user_id: str = None) -> Optional[Dict[str, Any]]:
        """獲取任務（DB 內容 + ProgressStore snapshot 合併）"""
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            return None

        if user_id:
            task_user_id = self._get_task_user_id(task)
            if task_user_id != user_id:
                return None

        # 包 run_in_executor 避免 MongoProgressStore 的 pymongo 阻塞 event loop。
        # InMemoryProgressStore 的 dict lookup 走同條路 overhead 可忽略。
        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(
            None, self.progress_store.get, task_id
        )
        if snapshot is not None:
            if snapshot.message:
                task["progress"] = snapshot.message
            task["progress_percentage"] = snapshot.overall_percentage
            task["phase"] = snapshot.phase.value
            if snapshot.details:
                task.update(snapshot.details)

        return task

    async def update_task_status(
        self,
        task_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """更新任務的 DB 欄位（進度欄位請走 progress_store.set_phase）"""
        if not updates:
            return True
        return await self.task_repo.update(task_id, updates)

    def cancel_task(self, task_id: str) -> None:
        """取消任務（設置取消標記）

        Args:
            task_id: 任務 ID
        """
        with self._lock:
            self._cancelled_tasks[task_id] = True

    def is_cancelled(self, task_id: str) -> bool:
        """檢查任務是否已取消

        Args:
            task_id: 任務 ID

        Returns:
            是否已取消
        """
        with self._lock:
            return self._cancelled_tasks.get(task_id, False)

    async def delete_task(self, task_id: str, user_id: str = None) -> bool:
        """刪除任務（包含記憶體和資料庫）

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（用於權限驗證）

        Returns:
            是否刪除成功
        """
        # 權限驗證
        if user_id:
            task = await self.get_task(task_id, user_id)
            if not task:
                return False

        # 清理記憶體狀態
        self.cleanup_task_memory(task_id)

        # 從資料庫刪除
        success = await self.task_repo.delete(task_id)
        return success

    async def soft_delete_full(self, task: Dict[str, Any], task_id: str) -> List[str]:
        """完整軟刪除：物理刪除檔案/關聯文檔 + DB 標記 deleted。

        這是 delete_task route 和 batch_delete_tasks 的共用邏輯。
        呼叫者須先做權限驗證和前置檢查（status、已刪除等）。

        Returns:
            被刪除的檔案名稱列表
        """
        from src.database.repositories.transcription_repo import TranscriptionRepository
        from src.database.repositories.segment_repo import SegmentRepository
        from src.utils.storage_service import is_aws, delete_audio_by_path as storage_delete_audio_by_path
        from .task_query_helpers import get_task_field

        deleted_files = []

        # 物理刪除結果檔案（僅本地模式）
        if not is_aws():
            allowed_output_dir = Path("output").resolve()

            result_file_path = get_task_field(task, "result_file")
            if result_file_path:
                try:
                    resolved = Path(result_file_path).resolve()
                    resolved.relative_to(allowed_output_dir)
                    if resolved.exists():
                        resolved.unlink()
                        deleted_files.append(resolved.name)
                except (ValueError, Exception) as e:
                    log.warning("task.delete.result_file_failed", task_id=task_id, error=str(e))

            segments_file_path = get_task_field(task, "segments_file")
            if segments_file_path:
                try:
                    resolved = Path(segments_file_path).resolve()
                    resolved.relative_to(allowed_output_dir)
                    if resolved.exists():
                        resolved.unlink()
                        deleted_files.append(resolved.name)
                except (ValueError, Exception) as e:
                    log.warning("task.delete.segments_file_failed", task_id=task_id, error=str(e))

        # 物理刪除音檔
        try:
            audio_file_path = task.get("result", {}).get("audio_file")
            if audio_file_path:
                storage_delete_audio_by_path(audio_file_path)
            deleted_files.append(f"{task_id}.mp3")
        except Exception as e:
            log.warning("task.delete.audio_failed", task_id=task_id, error=str(e))

        # 清理記憶體
        self.cleanup_task_memory(task_id)

        # 刪除 transcription 文檔
        db = self.task_repo.db
        transcription_repo = TranscriptionRepository(db)
        try:
            await transcription_repo.delete(task_id)
        except Exception as e:
            log.warning("task.delete.transcription_doc_failed", task_id=task_id, error=str(e))

        # 刪除 segment 文檔
        segment_repo = SegmentRepository(db)
        try:
            await segment_repo.delete(task_id)
        except Exception as e:
            log.warning("task.delete.segment_doc_failed", task_id=task_id, error=str(e))

        # 軟刪除 task
        await self.task_repo.update(task_id, {
            "deleted": True,
            "deleted_at": datetime.utcnow()
        })

        log.info("task.deleted", task_id=task_id)
        return deleted_files

    def cleanup_task_memory(self, task_id: str) -> None:
        """清理任務的執行期資源（progress snapshot、取消標記、臨時目錄、diarization 進程）"""
        self.progress_store.clear(task_id)

        with self._lock:
            self._cancelled_tasks.pop(task_id, None)
            temp_dir = self._temp_dirs.pop(task_id, None)
            if temp_dir is not None:
                self._cleanup_temp_dir(temp_dir)
            self._diarization_processes.pop(task_id, None)

    def set_temp_dir(self, task_id: str, temp_dir: Path) -> None:
        """設置任務的臨時目錄

        Args:
            task_id: 任務 ID
            temp_dir: 臨時目錄路徑
        """
        with self._lock:
            self._temp_dirs[task_id] = temp_dir

    def get_temp_dir(self, task_id: str) -> Optional[Path]:
        """獲取任務的臨時目錄

        Args:
            task_id: 任務 ID

        Returns:
            臨時目錄路徑，如果不存在則返回 None
        """
        with self._lock:
            return self._temp_dirs.get(task_id)

    def set_diarization_process(self, task_id: str, process: Any) -> None:
        """設置任務的 diarization 進程

        Args:
            task_id: 任務 ID
            process: Diarization 進程
        """
        with self._lock:
            self._diarization_processes[task_id] = process

    def get_diarization_process(self, task_id: str) -> Any:
        """獲取任務的 diarization 進程

        Args:
            task_id: 任務 ID

        Returns:
            Diarization 進程，如果不存在則返回 None
        """
        with self._lock:
            return self._diarization_processes.get(task_id)

    # ========== 業務邏輯方法 ==========

    async def update_transcription_content(self, task_id: str, user_id: str, content: str) -> bool:
        """更新任務的轉錄內容（含業務邏輯：計算文字長度）

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（權限驗證）
            content: 轉錄內容

        Returns:
            是否更新成功
        """
        # 權限驗證
        task = await self.get_task(task_id, user_id)
        if not task:
            return False

        # 計算文字長度（業務邏輯）
        text_length = len(content)

        # 更新資料庫
        updates = {
            "text_length": text_length
            # updated_at 由 task_repo.update() 自動設置
        }
        return await self.task_repo.update(task_id, updates)

    async def update_task_metadata(
        self,
        task_id: str,
        user_id: str,
        custom_name: Optional[str] = None
    ) -> bool:
        """更新任務的元數據（含業務邏輯：檔名驗證與清理）

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（權限驗證）
            custom_name: 自訂檔名

        Returns:
            是否更新成功
        """
        # 權限驗證
        task = await self.get_task(task_id, user_id)
        if not task:
            return False

        updates = {}

        # 驗證檔名（業務邏輯：移除非法字符）
        if custom_name is not None:
            import re
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', custom_name)
            updates["custom_name"] = safe_name

        # updated_at 由 task_repo.update() 自動設置
        return await self.task_repo.update(task_id, updates)

    async def update_task_tags(self, task_id: str, user_id: str, tags: List[str]) -> bool:
        """更新任務的標籤

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（權限驗證）
            tags: 標籤列表

        Returns:
            是否更新成功
        """
        # 權限驗證
        task = await self.get_task(task_id, user_id)
        if not task:
            return False

        updates = {
            "tags": tags
            # updated_at 由 task_repo.update() 自動設置
        }
        return await self.task_repo.update(task_id, updates)

    async def update_keep_audio(self, task_id: str, user_id: str, keep_audio: bool) -> bool:
        """更新任務的音檔保留狀態

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（權限驗證）
            keep_audio: 是否保留音檔

        Returns:
            是否更新成功
        """
        # 權限驗證
        task = await self.get_task(task_id, user_id)
        if not task:
            return False

        updates = {
            "keep_audio": keep_audio
            # updated_at 由 task_repo.update() 自動設置
        }
        return await self.task_repo.update(task_id, updates)

    async def mark_task_as_cancelled(self, task_id: str, user_id: str = None) -> bool:
        """標記任務為已取消（同時更新記憶體標記和資料庫狀態）

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（權限驗證，可選）

        Returns:
            是否更新成功
        """
        # 權限驗證（如果提供 user_id）
        if user_id:
            task = await self.get_task(task_id, user_id)
            if not task:
                return False

        # 設置記憶體取消標記
        self.cancel_task(task_id)

        # 更新資料庫狀態
        updates = {
            "status": "cancelled"
            # updated_at 由 task_repo.update() 自動設置
        }
        return await self.task_repo.update(task_id, updates)

    # ========== 私有輔助方法 ==========

    def _get_task_user_id(self, task: Dict[str, Any]) -> str:
        """安全獲取任務的 user_id（支援巢狀與扁平格式）

        Args:
            task: 任務資料

        Returns:
            用戶 ID
        """
        # 嘗試巢狀格式
        if "user" in task and isinstance(task["user"], dict):
            return str(task["user"].get("user_id", ""))

        # 嘗試扁平格式
        return str(task.get("user_id", ""))

    def _cleanup_temp_dir(self, temp_dir: Path) -> None:
        """清理臨時目錄

        Args:
            temp_dir: 臨時目錄路徑
        """
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                log.debug("task.temp_dir.cleaned", temp_dir=temp_dir.name)
        except Exception as e:
            log.warning("task.temp_dir.cleanup_failed", error=str(e))

    # ========== 背景清理任務 ==========

    async def periodic_memory_cleanup(self) -> None:
        """定期清理記憶體中的孤立資料（背景任務）

        每 10 分鐘執行一次，清理不在進行中的任務的記憶體狀態
        """
        while True:
            try:
                # 每 10 分鐘執行一次
                await asyncio.sleep(600)

                log.debug("task.memory_cleanup.started")

                # 從資料庫查詢所有進行中的任務
                # 記憶體優化：減少查詢數量（100 → 20）並只查詢 task_id
                active_task_ids = set()
                active_tasks = await self.task_repo.collection.find(
                    {"status": {"$in": ["pending", "processing"]}},
                    {"task_id": 1}  # 只查詢 task_id
                ).limit(20).to_list(length=20)

                active_task_ids = {task["task_id"] for task in active_tasks if "task_id" in task}

                # 清理不在進行中列表的記憶體資料
                with self._lock:
                    orphaned_temp_dirs = [tid for tid in self._temp_dirs if tid not in active_task_ids]
                    for tid in orphaned_temp_dirs:
                        self._temp_dirs.pop(tid, None)

                    for tid in list(self._cancelled_tasks.keys()):
                        if tid not in active_task_ids:
                            self._cancelled_tasks.pop(tid, None)

                    for tid in list(self._diarization_processes.keys()):
                        if tid not in active_task_ids:
                            self._diarization_processes.pop(tid, None)

                # 強制垃圾回收
                gc.collect()

                if orphaned_temp_dirs:
                    log.info("task.memory_cleanup.done", orphaned_temp_dirs=len(orphaned_temp_dirs))
                else:
                    log.info("task.memory_cleanup.done", orphaned_temp_dirs=0)

            except Exception as e:
                log.error("task.memory_cleanup.failed", error=str(e), exc_info=True)

    async def cleanup_orphaned_tasks(self) -> None:
        """清理異常中斷的任務（Web Server 啟動時執行）

        AWS 模式下 Web Server 跟 GPU Worker 是不同進程不同機器，
        Web Server 重啟（例如 deploy 時）不該影響 Worker 正在跑的任務。
        以前一律標 failed 的做法會誤殺 active task，導致「Worker 跑完寫
        status=completed 但 error 欄位殘留 SERVER_RESTART」的詭異狀態。

        改用 task_progress collection 的 updated_at 當 Worker liveness signal：
        active Worker 每幾秒會更新 task_progress。如果 task 對應的
        task_progress 在最近 5 分鐘內有寫入 → Worker 還活著，跳過；
        否則才標 failed（適用 Worker crash / Spot 中斷後沒接手的情境）。
        """
        from datetime import timedelta
        try:
            orphaned_tasks = await self.task_repo.collection.find(
                {"status": {"$in": ["pending", "processing"]}},
                {"_id": 1, "task_id": 1, "status": 1, "timestamps": 1}
            ).limit(50).to_list(length=50)

            if not orphaned_tasks:
                log.debug("task.orphan.none_found")
                return

            # MongoProgressStore 寫入 updated_at=datetime.now(timezone.utc)，
            # BSON 儲存後讀出是 naive UTC，用 utcnow() 比較。
            liveness_threshold = datetime.utcnow() - timedelta(minutes=5)
            progress_coll = self.task_repo.collection.database.task_progress

            truly_orphaned = []
            alive_task_ids = []
            for task in orphaned_tasks:
                tp = await progress_coll.find_one(
                    {"_id": task["_id"]},
                    {"updated_at": 1}
                )
                if tp and tp.get("updated_at") and tp["updated_at"] > liveness_threshold:
                    alive_task_ids.append(task.get("task_id"))
                else:
                    truly_orphaned.append(task)

            if alive_task_ids:
                log.info("task.orphan.skipped_alive", alive_count=len(alive_task_ids), task_ids=alive_task_ids[:5])

            if not truly_orphaned:
                log.debug("task.orphan.none_truly_orphaned")
                return

            log.info("task.orphan.sweep_started", orphan_count=len(truly_orphaned))

            current_time = get_current_time()
            for task in truly_orphaned:
                task_id = task.get("task_id", "unknown")

                update_data = {
                    "status": "failed",
                    "progress": "伺服器重啟，任務已中斷",
                    "error": {"code": "SERVER_RESTART", "message": "任務執行期間伺服器重啟，任務已被標記為失敗"},
                    "updated_at": current_time,
                    "completed_at": current_time,
                    "timestamps.updated_at": current_time,
                    "timestamps.completed_at": current_time
                }

                await self.task_repo.collection.update_one(
                    {"_id": task["_id"]},
                    {"$set": update_data}
                )
                log.debug("task.orphan.marked_failed", task_id=task_id)

            log.info("task.orphan.swept", orphan_count=len(truly_orphaned))

        except Exception as e:
            log.error("task.orphan.sweep_failed", error=str(e), exc_info=True)

    async def cleanup_orphaned_processes(self) -> None:
        """清理孤立的 multiprocessing worker 進程

        檢測並終止沒有對應活動任務的 worker 進程
        """
        if not PSUTIL_AVAILABLE:
            return

        try:
            current_pid = os.getpid()
            current_process = psutil.Process(current_pid)

            # 查找所有子進程（包括遞歸子進程）
            children = current_process.children(recursive=True)

            if not children:
                return

            # 查找所有處於活動狀態的任務
            active_tasks = await self.task_repo.collection.find(
                {"status": {"$in": ["pending", "processing"]}},
                {"task_id": 1}
            ).to_list(length=100)

            active_task_count = len(active_tasks)

            # 找出 multiprocessing worker 進程
            orphaned_workers = []
            for child in children:
                try:
                    cmdline = " ".join(child.cmdline())
                    # 檢測是否為 multiprocessing worker
                    if "multiprocessing" in cmdline and "spawn_main" in cmdline:
                        # 如果沒有活動任務，這些 worker 就是孤立的
                        if active_task_count == 0:
                            orphaned_workers.append(child)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if orphaned_workers:
                log.warning("task.orphan_process.found", worker_count=len(orphaned_workers))

                for worker in orphaned_workers:
                    try:
                        pid = worker.pid
                        cpu_percent = worker.cpu_percent()
                        memory_mb = worker.memory_info().rss / 1024 / 1024

                        log.debug("task.orphan_process.terminating", pid=pid, cpu_percent=cpu_percent, memory_mb=memory_mb)

                        # 先嘗試優雅終止
                        worker.terminate()

                        # 等待最多 3 秒
                        try:
                            worker.wait(timeout=3)
                            log.debug("task.orphan_process.terminated", pid=pid)
                        except psutil.TimeoutExpired:
                            # 強制殺掉
                            log.warning("task.orphan_process.unresponsive", pid=pid)
                            worker.kill()
                            worker.wait(timeout=1)
                            log.debug("task.orphan_process.killed", pid=pid)

                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        log.warning("task.orphan_process.terminate_failed", pid=worker.pid, error=str(e))

                log.info("task.orphan_process.swept", worker_count=len(orphaned_workers))

        except Exception as e:
            log.error("task.orphan_process.sweep_failed", error=str(e), exc_info=True)

    async def periodic_orphaned_process_cleanup(self) -> None:
        """定期清理孤立的 worker 進程（背景任務）

        每 5 分鐘執行一次
        """
        if not PSUTIL_AVAILABLE:
            log.warning("task.orphan_process.cleanup_skipped_no_psutil")
            return

        log.info("task.orphan_process.cleaner_started")

        while True:
            try:
                # 每 5 分鐘執行一次
                await asyncio.sleep(300)

                log.debug("task.orphan_process.cleanup_tick")
                await self.cleanup_orphaned_processes()

            except Exception as e:
                log.error("task.orphan_process.periodic_cleanup_failed", error=str(e), exc_info=True)
