"""
TaskService - 任務狀態管理服務
職責：
- 任務 CRUD 操作
- 封裝全域狀態（記憶體中的運行時狀態）
- 權限驗證
- 取消任務邏輯
- 清理任務記憶體
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

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("⚠️ psutil 未安裝，孤立進程清理功能不可用")

# 定義只需存在記憶體中的欄位（執行期間才有用，完成後無意義）
MEMORY_ONLY_FIELDS = {
    # 即時進度資訊
    "progress",  # 進度文字描述（如 "正在轉錄 chunk 3/10..."）
    "progress_percentage",  # 進度百分比（可從狀態即時計算）

    # 分塊執行細節
    "chunks",  # 每個 chunk 的詳細狀態陣列（超大物件，頻繁更新）
    "total_chunks",  # 總分塊數（可從 chunks 長度計算）
    "completed_chunks",  # 已完成分塊數（可從 chunks 計算）
    "processing_chunks",  # 正在處理中的 chunk 數量（用於進度計算）
    "chunks_created",  # 分塊是否已建立旗標
    "estimated_completion_time",  # 預估完成時間（執行期間的估算值）

    # 標點符號處理中間狀態
    "punctuation_started",  # 標點處理是否已開始
    "punctuation_current_chunk",  # 當前處理的標點段數
    "punctuation_total_chunks",  # 標點處理總段數
    "punctuation_completed",  # 標點處理是否完成

    # 說話者辨識中間狀態
    "diarization_started",  # 說話者辨識是否已開始
    "diarization_completed",  # 說話者辨識是否完成
    "diarization_status",  # 說話者辨識即時狀態

    # 其他中間處理旗標
    "audio_converted",  # 音檔是否已轉換
}

# 進度階段權重（固定分配，總和 100%）
PROGRESS_WEIGHTS = {
    "audio_conversion": 5.0,      # 音訊轉檔：5%
    "audio_chunking": 5.0,        # 音訊切分：5%（僅分段模式）
    "transcription": 77.0,        # 轉錄：77%（分段模式）或 82%（非分段模式）
    "punctuation": 13.0,          # 加標點：13%
}

# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))


class TaskService:
    """任務狀態管理服務

    封裝全域狀態並提供任務管理的業務邏輯

    注意：在漸進式重構期間，此服務使用與 whisper_server.py 共享的全域字典，
    以確保新舊代碼能夠看到相同的狀態。
    """

    def __init__(
        self,
        task_repo: TaskRepository,
        state_store: TaskStateStore = None,
    ):
        """初始化 TaskService

        Args:
            task_repo: TaskRepository 實例
            state_store: TaskStateStore 實例（可選，未提供時建立新的）
        """
        self.task_repo = task_repo
        self._store = state_store if state_store is not None else TaskStateStore()

        # 保留內部屬性別名，維持其餘方法不需改動
        self._memory_tasks = self._store.tasks
        self._cancelled_tasks = self._store.cancelled
        self._temp_dirs = self._store.temp_dirs
        self._diarization_processes = self._store.diarization_processes
        self._lock = self._store.lock

    async def create_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立新任務

        Args:
            task_data: 任務資料

        Returns:
            建立的任務資料（含 task_id）
        """
        # 在資料庫中建立任務
        task = await self.task_repo.create(task_data)

        # 初始化記憶體狀態
        task_id = str(task["task_id"])
        with self._lock:
            self._memory_tasks[task_id] = {
                "progress": "初始化中...",
                "progress_percentage": 0.0,
            }

        return task

    async def get_task(self, task_id: str, user_id: str = None) -> Optional[Dict[str, Any]]:
        """獲取任務（合併 DB + 記憶體狀態）

        Args:
            task_id: 任務 ID
            user_id: 用戶 ID（用於權限驗證）

        Returns:
            任務資料（DB + 記憶體狀態合併），如果不存在或無權限則返回 None
        """
        # 從資料庫獲取任務
        task = await self.task_repo.get_by_id(task_id)

        if not task:
            return None

        # 權限驗證：檢查 user_id
        if user_id:
            task_user_id = self._get_task_user_id(task)
            if task_user_id != user_id:
                return None

        # 合併記憶體狀態
        with self._lock:
            if task_id in self._memory_tasks:
                memory_state = self._memory_tasks[task_id]
                task.update(memory_state)

                # 計算進度百分比
                task["progress_percentage"] = self._calculate_progress_percentage(task)

        return task

    async def update_task_status(
        self,
        task_id: str,
        updates: Dict[str, Any],
        memory_only: bool = False
    ) -> bool:
        """更新任務狀態（區分記憶體/DB 欄位）

        Args:
            task_id: 任務 ID
            updates: 要更新的欄位
            memory_only: 是否僅更新記憶體狀態（不寫入 DB）

        Returns:
            是否更新成功
        """
        # 分離記憶體欄位和 DB 欄位
        memory_updates = {}
        db_updates = {}

        for key, value in updates.items():
            if key in MEMORY_ONLY_FIELDS:
                memory_updates[key] = value
            else:
                db_updates[key] = value

        # 更新記憶體狀態
        if memory_updates:
            with self._lock:
                if task_id not in self._memory_tasks:
                    self._memory_tasks[task_id] = {}
                self._memory_tasks[task_id].update(memory_updates)

        # 更新資料庫（如果有 DB 欄位且非僅記憶體模式）
        if db_updates and not memory_only:
            success = await self.task_repo.update(task_id, db_updates)
            return success

        return True

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

    def cleanup_task_memory(self, task_id: str) -> None:
        """清理任務的記憶體狀態

        Args:
            task_id: 任務 ID
        """
        with self._lock:
            # 清理記憶體任務狀態
            if task_id in self._memory_tasks:
                del self._memory_tasks[task_id]

            # 清理取消標記
            if task_id in self._cancelled_tasks:
                del self._cancelled_tasks[task_id]

            # 清理臨時目錄
            if task_id in self._temp_dirs:
                temp_dir = self._temp_dirs[task_id]
                self._cleanup_temp_dir(temp_dir)
                del self._temp_dirs[task_id]

            # 清理 diarization 進程
            if task_id in self._diarization_processes:
                del self._diarization_processes[task_id]

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

    def get_memory_state(self, task_id: str) -> Dict[str, Any]:
        """獲取任務的記憶體狀態

        Args:
            task_id: 任務 ID

        Returns:
            記憶體狀態字典
        """
        with self._lock:
            return self._memory_tasks.get(task_id, {}).copy()

    def update_memory_state(self, task_id: str, updates: Dict[str, Any]) -> None:
        """更新任務的記憶體狀態

        Args:
            task_id: 任務 ID
            updates: 要更新的欄位
        """
        with self._lock:
            if task_id not in self._memory_tasks:
                self._memory_tasks[task_id] = {}
            self._memory_tasks[task_id].update(updates)

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

    def _calculate_progress_percentage(self, task_data: Dict[str, Any]) -> float:
        """根據任務狀態動態計算進度百分比

        Args:
            task_data: 任務資料（含記憶體狀態）

        Returns:
            進度百分比（0-100）
        """
        # 如果任務已完成，直接返回 100%
        if task_data.get("status") == "completed":
            return 100.0

        progress = 0.0

        # 判斷是否為分段模式：優先檢查 total_chunks，其次檢查 chunks 陣列，最後檢查配置
        total_chunks = task_data.get("total_chunks", 0)
        completed_chunks_count = task_data.get("completed_chunks", 0)
        processing_chunks_count = task_data.get("processing_chunks", 0)
        chunks = task_data.get("chunks", [])

        # 分段模式判斷：
        # 1. 有 total_chunks 或 chunks 陣列不為空
        # 2. 或者配置中啟用了分段模式（config.chunk_audio = true）
        config = task_data.get("config", {})
        chunk_audio = config.get("chunk_audio", False)
        is_chunked = total_chunks > 0 or len(chunks) > 0 or chunk_audio

        # 1. 音訊轉檔完成：5%
        if task_data.get("audio_converted", False):
            progress += PROGRESS_WEIGHTS["audio_conversion"]

        # 2. 轉錄階段
        if is_chunked:
            # 分段模式：audio_chunking(5%) + transcription(77%)

            # 音訊切分完成（分段模式特有階段）
            # 當開始轉錄時（有 completed_chunks 或 chunks 資訊），代表切分已完成
            if completed_chunks_count > 0 or len(chunks) > 0 or task_data.get("chunks_created", False):
                progress += PROGRESS_WEIGHTS["audio_chunking"]

            # 根據實際 chunks 數量分配轉錄進度
            if total_chunks > 0:
                # 使用 total_chunks 和 completed_chunks 計算（新的分段模式）
                chunk_weight = PROGRESS_WEIGHTS["transcription"] / total_chunks
                # 已完成的 chunk 貢獻 100% 的權重
                progress += completed_chunks_count * chunk_weight
                # 正在處理中的 chunk 貢獻 50% 的權重
                progress += processing_chunks_count * (chunk_weight * 0.5)
            elif len(chunks) > 0:
                # 使用 chunks 陣列計算（舊的分段模式，如果有的話）
                num_chunks = len(chunks)
                completed_chunks = sum(1 for c in chunks if c.get("status") == "completed")
                processing_chunks = sum(1 for c in chunks if c.get("status") == "processing")

                chunk_weight = PROGRESS_WEIGHTS["transcription"] / num_chunks
                progress += completed_chunks * chunk_weight
                progress += processing_chunks * (chunk_weight * 0.5)
            elif task_data.get("audio_converted", False):
                # 分段模式但還沒有 chunk 資訊（轉錄剛開始）
                # 給予音訊切分階段的完成進度 + 轉錄開始的初始進度
                progress += PROGRESS_WEIGHTS["audio_chunking"]
                # 轉錄剛開始，給予 10% 的轉錄進度
                progress += PROGRESS_WEIGHTS["transcription"] * 0.1
        else:
            # 非分段模式：transcription(82%) = audio_chunking(5%) + transcription(77%)
            # 簡單判斷：如果已經開始標點，說明轉錄完成
            if task_data.get("punctuation_started", False) or task_data.get("punctuation_completed", False):
                progress += PROGRESS_WEIGHTS["audio_chunking"] + PROGRESS_WEIGHTS["transcription"]
            elif task_data.get("audio_converted", False):
                # 轉錄中，給予 50% 的轉錄進度
                progress += (PROGRESS_WEIGHTS["audio_chunking"] + PROGRESS_WEIGHTS["transcription"]) * 0.5

        # 3. 標點處理：13%
        if task_data.get("punctuation_completed", False):
            progress += PROGRESS_WEIGHTS["punctuation"]
        elif task_data.get("punctuation_started", False):
            # 標點處理中，根據段數計算進度
            punct_current = task_data.get("punctuation_current_chunk", 0)
            punct_total = task_data.get("punctuation_total_chunks", 1)
            punct_progress = (punct_current / punct_total) * PROGRESS_WEIGHTS["punctuation"]
            progress += punct_progress

        return min(progress, 100.0)

    def _cleanup_temp_dir(self, temp_dir: Path) -> None:
        """清理臨時目錄

        Args:
            temp_dir: 臨時目錄路徑
        """
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                print(f"🗑️ 已清理臨時目錄：{temp_dir.name}")
        except Exception as e:
            print(f"⚠️ 清理臨時目錄失敗：{e}")

    # ========== 背景清理任務 ==========

    async def periodic_memory_cleanup(self) -> None:
        """定期清理記憶體中的孤立資料（背景任務）

        每 10 分鐘執行一次，清理不在進行中的任務的記憶體狀態
        """
        while True:
            try:
                # 每 10 分鐘執行一次
                await asyncio.sleep(600)

                print("🧹 執行定期記憶體清理...")

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
                    # 清理 transcription_tasks
                    orphaned_tasks = [tid for tid in self._memory_tasks.keys() if tid not in active_task_ids]
                    for tid in orphaned_tasks:
                        self._memory_tasks.pop(tid, None)
                        print(f"  🗑️  清理孤立任務記憶體: {tid}")

                    # 清理其他字典
                    for tid in list(self._temp_dirs.keys()):
                        if tid not in active_task_ids:
                            self._temp_dirs.pop(tid, None)

                    for tid in list(self._cancelled_tasks.keys()):
                        if tid not in active_task_ids:
                            self._cancelled_tasks.pop(tid, None)

                    for tid in list(self._diarization_processes.keys()):
                        if tid not in active_task_ids:
                            self._diarization_processes.pop(tid, None)

                # 強制垃圾回收
                gc.collect()

                if orphaned_tasks:
                    print(f"✅ 記憶體清理完成，清除 {len(orphaned_tasks)} 個孤立任務")
                else:
                    print("✅ 記憶體清理完成，無孤立資料")

            except Exception as e:
                print(f"⚠️  定期記憶體清理失敗: {e}")

    async def cleanup_orphaned_tasks(self) -> None:
        """清理異常中斷的任務（程式重啟時執行）

        將所有處於 pending 或 processing 狀態的任務標記為失敗
        """
        try:
            # 查找所有處於 pending 或 processing 狀態的任務
            # 記憶體優化：限制數量並只查詢需要的欄位
            orphaned_tasks = await self.task_repo.collection.find(
                {"status": {"$in": ["pending", "processing"]}},
                {"_id": 1, "task_id": 1, "status": 1, "timestamps": 1}  # 只查詢需要的欄位
            ).limit(50).to_list(length=50)  # 限制最多 50 個

            if not orphaned_tasks:
                print("✅ 沒有發現異常中斷的任務")
                return

            print(f"⚠️  發現 {len(orphaned_tasks)} 個異常中斷的任務，正在清理...")

            # 將這些任務標記為失敗
            current_time = get_current_time()
            for task in orphaned_tasks:
                task_id = task.get("task_id", "unknown")

                # 更新任務狀態（同步更新根層級和巢狀結構的時間戳）
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
                print(f"   ✓ 任務 {task_id} 已標記為失敗")

            print(f"✅ 清理完成，共處理 {len(orphaned_tasks)} 個任務")

        except Exception as e:
            print(f"⚠️  清理孤立任務失敗: {e}")

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
                print(f"⚠️  發現 {len(orphaned_workers)} 個孤立的 worker 進程（無活動任務）")

                for worker in orphaned_workers:
                    try:
                        pid = worker.pid
                        cpu_percent = worker.cpu_percent()
                        memory_mb = worker.memory_info().rss / 1024 / 1024

                        print(f"   🗑️  終止孤立 worker: PID {pid} (CPU: {cpu_percent:.1f}%, Memory: {memory_mb:.1f}MB)")

                        # 先嘗試優雅終止
                        worker.terminate()

                        # 等待最多 3 秒
                        try:
                            worker.wait(timeout=3)
                            print(f"   ✓ Worker {pid} 已終止")
                        except psutil.TimeoutExpired:
                            # 強制殺掉
                            print(f"   ⚠️  Worker {pid} 未響應，強制終止...")
                            worker.kill()
                            worker.wait(timeout=1)
                            print(f"   ✓ Worker {pid} 已強制終止")

                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        print(f"   ⚠️  無法終止進程 {worker.pid}: {e}")

                print(f"✅ 孤立進程清理完成，共終止 {len(orphaned_workers)} 個 worker")

        except Exception as e:
            print(f"⚠️  清理孤立進程失敗: {e}")

    async def periodic_orphaned_process_cleanup(self) -> None:
        """定期清理孤立的 worker 進程（背景任務）

        每 5 分鐘執行一次
        """
        if not PSUTIL_AVAILABLE:
            print("⚠️  psutil 不可用，跳過孤立進程清理")
            return

        print("🚀 啟動孤立進程定期清理器...")

        while True:
            try:
                # 每 5 分鐘執行一次
                await asyncio.sleep(300)

                print("🧹 執行定期孤立進程清理...")
                await self.cleanup_orphaned_processes()

            except Exception as e:
                print(f"⚠️  定期孤立進程清理失敗: {e}")

    # ========== 任務隊列管理 ==========

    async def count_processing_tasks(self) -> int:
        """計算當前正在處理的任務數量

        Returns:
            正在處理的任務數量
        """
        try:
            count = await self.task_repo.collection.count_documents(
                {"status": "processing"}
            )
            return count
        except Exception as e:
            print(f"⚠️  計算處理中任務數量失敗: {e}")
            return 0

    async def count_pending_tasks(self) -> int:
        """計算當前等待中的任務數量

        Returns:
            等待中的任務數量
        """
        try:
            count = await self.task_repo.collection.count_documents(
                {"status": "pending"}
            )
            return count
        except Exception as e:
            print(f"⚠️  計算等待中任務數量失敗: {e}")
            return 0

    async def get_next_pending_task(self) -> Optional[Dict[str, Any]]:
        """獲取下一個等待處理的任務（按創建時間排序）

        Returns:
            下一個待處理的任務，如果沒有則返回 None
        """
        try:
            task = await self.task_repo.collection.find_one(
                {"status": "pending"},
                sort=[("timestamps.created_at", 1)]  # 按創建時間升序
            )
            return task
        except Exception as e:
            print(f"⚠️  獲取下一個待處理任務失敗: {e}")
            return None

    async def process_pending_queue(self, transcription_service, max_concurrent: int = 2):
        """後台隊列處理器：自動處理 pending 任務

        定期檢查隊列，當有空閒時自動啟動待處理任務

        Args:
            transcription_service: TranscriptionService 實例
            max_concurrent: 最大並發數（默認 2）
        """
        print("🚀 啟動任務隊列處理器...")

        while True:
            try:
                # 每 5 秒檢查一次隊列
                await asyncio.sleep(5)

                # 檢查當前處理中的任務數
                processing_count = await self.count_processing_tasks()

                # 如果有空閒，處理下一個任務
                if processing_count < max_concurrent:
                    pending_task = await self.get_next_pending_task()

                    if pending_task:
                        task_id = pending_task.get("task_id")
                        print(f"📋 從隊列取出任務：{task_id}")

                        # 立即將任務標記為 processing，防止被重複取出
                        await self.task_repo.update(task_id, {
                            "status": "processing",
                            "updated_at": get_current_time()
                        })
                        print(f"🔄 任務 {task_id} 狀態已更新為 processing")

                        # 獲取任務配置和文件路徑
                        config = pending_task.get("config", {})
                        temp_dir_path = self._temp_dirs.get(task_id)

                        if not temp_dir_path or not temp_dir_path.exists():
                            print(f"⚠️  任務 {task_id} 的臨時文件不存在，標記為失敗")
                            await self.task_repo.update(task_id, {
                                "status": "failed",
                                "error": {"code": "AUDIO_MISSING", "message": "音檔文件已遺失"},
                                "updated_at": get_current_time()
                            })
                            continue

                        # 找到音檔文件
                        audio_files = list(temp_dir_path.glob("input.*"))
                        if not audio_files:
                            print(f"⚠️  任務 {task_id} 找不到音檔文件")
                            await self.task_repo.update(task_id, {
                                "status": "failed",
                                "error": {"code": "AUDIO_MISSING", "message": "音檔文件已遺失"},
                                "updated_at": get_current_time()
                            })
                            continue

                        audio_file_path = audio_files[0]

                        # 啟動轉錄
                        use_punctuation = config.get("punct_provider", "none") != "none"
                        language_code = config.get("language")
                        if language_code == "auto":
                            language_code = None

                        try:
                            await transcription_service.start_transcription(
                                task_id=task_id,
                                audio_file_path=audio_file_path,
                                language=language_code,
                                use_chunking=config.get("chunk_audio", True),
                                use_punctuation=use_punctuation,
                                punctuation_provider=config.get("punct_provider", "gemini"),
                                use_diarization=config.get("diarize", False),
                                max_speakers=config.get("max_speakers")
                            )

                            print(f"✅ 任務 {task_id} 已從隊列啟動處理")
                        except Exception as e:
                            print(f"❌ 啟動任務 {task_id} 失敗: {e}")
                            await self.task_repo.update(task_id, {
                                "status": "failed",
                                "error": {"code": "SYSTEM_ERROR", "message": f"啟動失敗: {str(e)}"},
                                "updated_at": get_current_time()
                            })

            except Exception as e:
                print(f"⚠️  隊列處理器錯誤: {e}")
