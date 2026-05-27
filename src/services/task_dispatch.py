"""Task dispatch seam — 對應 CONTEXT.md「Task dispatch」。

把新建 Task 移交給「會去跑它的 runner」的 seam。intake router 不再分支
`is_aws()`——只呼叫 `submit()`，由 adapter 決定走 SQS 還是 in-process executor。

- LocalDispatch（本檔）：local adapter，舊淺殼 TranscriptionService 深化而成。
- WorkerDispatch（src/services/worker_dispatch.py）：AWS adapter。

兩個 adapter 都滿足 `TaskDispatch` Protocol。main.py startup 依部署模式建一個、
呼叫 `init_task_dispatch()` 註冊，routers 拿 `get_task_dispatch()` 用同一實例。
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from src.database.sync_client import get_sync_db
from src.models.worker_job import TranscriptionJob
from src.services.progress_store import Phase
from src.transcription.audio_source import LocalFileSource
from src.transcription.orchestrator import TranscriptionOrchestrator
from src.utils.logger import get_logger
from src.utils.sentry_helpers import create_background_task

log = get_logger(__name__)


@dataclass
class DispatchResult:
    """submit() 的回傳值。

    硬合約只有 `status`；`queue_position` 是 best-effort 顯示糖，adapter 能便宜
    算就算（WorkerDispatch 不算，留 None）。
    """

    status: str  # "pending" | "processing"
    queue_position: Optional[int] = None


class TaskDispatch(Protocol):
    """把新建 Task 移交給 runner 的 seam。兩個 adapter：LocalDispatch / WorkerDispatch。"""

    async def submit(
        self,
        *,
        job: TranscriptionJob,
        audio_local_path: Path,
        temp_dir: Path,
        user_tier: str,
    ) -> DispatchResult:
        """移交 Task。temp_dir 在返回後即歸 adapter 負責清理。"""
        ...

    def start(self) -> None:
        """啟動 adapter 的背景機制（LocalDispatch 起撿單器；WorkerDispatch no-op）。"""
        ...


def _job_from_task_doc(task_doc: dict) -> TranscriptionJob:
    """從 MongoDB task 文件的 config 重建 TranscriptionJob（撿單器用）。"""
    config = task_doc.get("config", {})
    language = config.get("language")
    return TranscriptionJob(
        task_id=task_doc["task_id"],
        language=None if language == "auto" else language,
        use_chunking=config.get("chunk_audio", True),
        use_punctuation=config.get("punct_provider", "none") != "none",
        punctuation_provider=config.get("punct_provider") or "gemini",
        use_diarization=config.get("diarize", False),
        max_speakers=config.get("max_speakers"),
        ui_language=config.get("ui_language"),
    )


class LocalDispatch:
    """[[Task dispatch]] 的 local adapter（舊 TranscriptionService 深化）。

    `submit()` 內含本地並發閘門：未滿載立即把 TranscriptionOrchestrator submit
    進 thread pool；滿載就把 Task 留 pending，由背景撿單器（`start()` 啟動）接走。
    run-now 與撿單兩條路徑共用內部 `_start()`。
    """

    MAX_CONCURRENT_TASKS = 2
    _POLL_INTERVAL_SECONDS = 5

    def __init__(
        self,
        *,
        task_service,
        progress_store,
        whisper,
        punctuation,
        diarization=None,
        executor: Optional[ThreadPoolExecutor] = None,
    ):
        self.task_service = task_service
        self.task_repo = task_service.task_repo
        self.progress_store = progress_store
        self.executor = executor or ThreadPoolExecutor(max_workers=3)
        self.orchestrator = TranscriptionOrchestrator(
            db=get_sync_db(),
            progress_store=progress_store,
            whisper=whisper,
            punctuation=punctuation,
            diarization=diarization,
        )
        self._poller_task = None

    async def submit(
        self,
        *,
        job: TranscriptionJob,
        audio_local_path: Path,
        temp_dir: Path,
        user_tier: str,
    ) -> DispatchResult:
        """未滿載立即啟動轉錄；滿載則留 pending 等撿單器。"""
        task_id = job.task_id
        self.progress_store.set_phase(
            task_id, Phase.PREPARATION, 0.0, message="等待處理中..."
        )
        # 記錄 temp_dir：撿單器之後要靠它定位音檔；轉錄結束由 LocalFileSource 清掉
        self.task_service.set_temp_dir(task_id, temp_dir)

        processing = await self.task_repo.count_all_by_status("processing")
        if processing >= self.MAX_CONCURRENT_TASKS:
            pending = await self.task_repo.count_all_by_status("pending")
            log.info(
                "dispatch.local.queued",
                task_id=task_id,
                processing=processing,
                pending=pending,
            )
            return DispatchResult(status="pending", queue_position=pending)

        await self._start(job, audio_local_path)
        return DispatchResult(status="processing", queue_position=0)

    def start(self) -> None:
        """啟動背景撿單器（5 秒輪詢，把 pending Task 依建立時間接走）。"""
        if self._poller_task is None:
            self._poller_task = create_background_task(
                self._run_poller(), name="task_queue_processor"
            )

    async def _start(self, job: TranscriptionJob, audio_local_path: Path) -> None:
        """把單一 Task 標 processing 並 submit orchestrator 進 executor（非阻擋）。"""
        task_id = job.task_id
        await self.task_repo.update(task_id, {"status": "processing"})
        self.progress_store.set_phase(
            task_id, Phase.PREPARATION, 0.0, message="準備開始轉錄..."
        )
        audio_source = LocalFileSource(audio_local_path)
        try:
            self.executor.submit(
                self.orchestrator.run,
                task_id, audio_source, job.language, job.use_chunking,
                job.use_punctuation, job.punctuation_provider, job.use_diarization,
                job.max_speakers, job.ui_language,
            )
            log.info("dispatch.local.task_submitted", task_id=task_id)
        except Exception as e:
            log.error(
                "dispatch.local.submit_failed",
                task_id=task_id,
                error=str(e),
                exc_info=True,
            )

    async def _run_poller(self) -> None:
        """背景撿單器迴圈：每 _POLL_INTERVAL_SECONDS 跑一次 _poll_once。"""
        log.info(
            "dispatch.local.poller_started", max_concurrent=self.MAX_CONCURRENT_TASKS
        )
        while True:
            await asyncio.sleep(self._POLL_INTERVAL_SECONDS)
            try:
                await self._poll_once()
            except Exception as e:
                log.error("dispatch.local.poller_error", error=str(e), exc_info=True)

    async def _poll_once(self) -> None:
        """撿單器單次迭代：有空閒就把最舊的 pending Task 接走啟動。"""
        processing = await self.task_repo.count_all_by_status("processing")
        if processing >= self.MAX_CONCURRENT_TASKS:
            return

        pending_task = await self.task_repo.get_oldest_pending()
        if not pending_task:
            return

        task_id = pending_task.get("task_id")
        temp_dir_path = self.task_service.get_temp_dir(task_id)
        if not temp_dir_path or not temp_dir_path.exists():
            log.warning("dispatch.local.temp_dir_missing", task_id=task_id)
            await self.task_repo.update(task_id, {
                "status": "failed",
                "error": {"code": "AUDIO_MISSING", "message": "音檔文件已遺失"},
            })
            return

        audio_files = list(temp_dir_path.glob("input.*"))
        if not audio_files:
            log.warning("dispatch.local.audio_file_missing", task_id=task_id)
            await self.task_repo.update(task_id, {
                "status": "failed",
                "error": {"code": "AUDIO_MISSING", "message": "音檔文件已遺失"},
            })
            return

        try:
            await self._start(_job_from_task_doc(pending_task), audio_files[0])
            log.info("dispatch.local.dequeued", task_id=task_id)
        except Exception as e:
            log.error(
                "dispatch.local.start_failed",
                task_id=task_id,
                error=str(e),
                exc_info=True,
            )
            await self.task_repo.update(task_id, {
                "status": "failed",
                "error": {"code": "SYSTEM_ERROR", "message": f"啟動失敗: {str(e)}"},
            })


# ── module-level singleton ────────────────────────────────────

_dispatch: Optional[TaskDispatch] = None


def init_task_dispatch(dispatch: TaskDispatch) -> None:
    """main.py startup 呼叫一次（傳入 LocalDispatch 或 WorkerDispatch）。"""
    global _dispatch
    _dispatch = dispatch


def get_task_dispatch() -> TaskDispatch:
    """取得已初始化的 dispatch 實例。

    Raises:
        RuntimeError: 若尚未 init（caller 漏調 init_task_dispatch）
    """
    if _dispatch is None:
        raise RuntimeError(
            "TaskDispatch 尚未初始化；main.py startup 應呼叫 init_task_dispatch()"
        )
    return _dispatch
