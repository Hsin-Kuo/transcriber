"""轉錄任務 Worker 入口(薄殼)。

解析 SQS 訊息 → SQS 重送 dedup → 建 S3Source → 呼叫統一 TranscriptionOrchestrator。
轉錄 pipeline 本身在 src/transcription/orchestrator.py,Web Server 與 Worker 共用同一份。
"""
from structlog.contextvars import bind_contextvars, clear_contextvars

from src.models.worker_job import TranscriptionJob
from src.services.progress_store import Phase, ProgressStore
from src.services.utils.diarization_processor import DiarizationProcessor
from src.services.utils.punctuation_processor import PunctuationProcessor
from src.transcription.audio_source import S3Source
from src.transcription.orchestrator import TranscriptionOrchestrator
from src.utils.logger import get_logger
from src.worker_core.db import get_db, update_task
from src.worker_core.model_cache import get_diarization_pipeline, get_whisper_processor

log = get_logger(__name__)

# SQS 可能重送同一訊息(Spot 中斷恢復、或在排隊期間被取消);任務已進終態就跳過
_SKIP_STATUSES = {"completed", "canceling", "cancelled"}


def process_task(message_body: dict, progress_store: ProgressStore) -> None:
    """處理單個轉錄任務(由 sqs_consumer 呼叫)。

    `message_body` 已被 sqs_consumer 驗 HMAC 並 pop `_signature`。
    """
    job = TranscriptionJob.model_validate(message_body)
    task_id = job.task_id
    # 綁定 task_id 到 log context:本任務內(含 orchestrator)所有 log 都帶 task_id
    bind_contextvars(task_id=task_id)
    try:
        db = get_db()
        task_doc = db.tasks.find_one({"_id": task_id}, {"status": 1})
        if task_doc and task_doc.get("status") in _SKIP_STATUSES:
            log.info("worker.task.skipped", status=task_doc.get("status"))
            progress_store.clear(task_id)
            return

        log.info("worker.task.received")
        update_task(db, task_id, {"status": "processing"})
        progress_store.set_phase(task_id, Phase.PREPARATION, 0.0, message="Worker 開始處理...")

        try:
            full_doc = db.tasks.find_one({"_id": task_id}) or {}
            user_tier = (full_doc.get("user") or {}).get("tier", "free")
            ui_language = (full_doc.get("config") or {}).get("ui_language")

            audio_source = S3Source(task_id, job.handoff_ext, user_tier)
            diarization = (
                DiarizationProcessor(get_diarization_pipeline()) if job.use_diarization else None
            )
            orchestrator = TranscriptionOrchestrator(
                db=db,
                progress_store=progress_store,
                whisper=get_whisper_processor(),
                punctuation=PunctuationProcessor(),
                diarization=diarization,
            )
            orchestrator.run(
                task_id, audio_source, job.language, job.use_chunking, job.use_punctuation,
                job.punctuation_provider, job.use_diarization, job.max_speakers, ui_language,
            )
        except Exception as e:
            # orchestrator.run() 自己處理 pipeline 失敗;這裡只接薄殼 setup 階段的例外
            log.error("worker.task.failed", error=str(e), exc_info=True)
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("task_id", task_id)
                    sentry_sdk.capture_exception(e)
            except Exception:
                pass
            update_task(db, task_id, {
                "status": "failed",
                "error": {"code": "SYSTEM_ERROR", "message": str(e)},
            })
            progress_store.clear(task_id)
    finally:
        clear_contextvars()
