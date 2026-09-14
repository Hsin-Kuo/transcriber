"""轉錄任務 Worker 入口(薄殼)。

解析 SQS 訊息 → SQS 重送 dedup → 建 S3Source → 呼叫統一 TranscriptionOrchestrator。
轉錄 pipeline 本身在 src/transcription/orchestrator.py,Web Server 與 Worker 共用同一份。
"""
from typing import Optional

from structlog.contextvars import bind_contextvars, clear_contextvars

from src.models.worker_job import TranscriptionJob
from src.services.progress_store import Phase, ProgressStore
from src.services.utils.diarization_processor import DiarizationProcessor
from src.services.utils.punctuation_processor import PunctuationProcessor
from src.transcription.audio_source import S3Source
from src.transcription.orchestrator import TranscriptionOrchestrator
from src.utils.logger import get_logger
from src.utils.time_utils import get_utc_timestamp
from src.worker_core.config import PROCESSING_CLAIM_STALE_SECONDS
from src.worker_core.db import get_db, update_task
from src.worker_core.heartbeat import get_worker_id
from src.worker_core.model_cache import get_diarization_pipeline, get_whisper_processor

log = get_logger(__name__)

# SQS 可能重送同一訊息(Spot 中斷恢復、或在排隊期間被取消);任務已進終態就跳過
_SKIP_STATUSES = {"completed", "canceling", "cancelled"}


def _claim_task(db, task_id: str) -> bool:
    """原子搶佔任務的 processing 權；搶不到回傳 False。

    為什麼要原子：`update_task(status="processing")` 是無條件寫入，`_should_skip`
    也不擋 processing 狀態。visibility 到期被 SQS 重投時，第二個 worker 會照樣
    寫入並開跑，同一顆任務被轉兩次（GPU/Gemini 雙重花費、進度交錯、結果
    last-writer-wins）。visibility 續命讓重投變罕見，這道是重投真的發生時的防線。

    搶佔條件（`$or`）：
      - status 不是 processing —— 正常情況
      - 沒有 claim 紀錄 —— 舊資料或上一版寫的
      - claim 已過期 —— 前一個 worker 掉了，任務必須能被接手，
        否則會永久卡在 processing
    """
    from pymongo import ReturnDocument

    now = get_utc_timestamp()
    stale_before = now - PROCESSING_CLAIM_STALE_SECONDS
    worker_id = get_worker_id()

    doc = db.tasks.find_one_and_update(
        {
            "_id": task_id,
            "$or": [
                {"status": {"$ne": "processing"}},
                {"processing_claim": {"$exists": False}},
                {"processing_claim.claimed_at": {"$lt": stale_before}},
            ],
        },
        {
            "$set": {
                "status": "processing",
                "updated_at": now,
                "processing_claim": {"worker_id": worker_id, "claimed_at": now},
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return doc is not None


def _should_skip(task_doc: Optional[dict]) -> bool:
    """是否該跳過這顆任務(不處理、直接刪訊息)。

    - 軟刪除(deleted=True):刪任務不會、也無法即時移除已在佇列的 SQS 訊息
      (SQS 只能憑 ReceiptHandle 刪),訊息會留到 worker 收到才清。此時音檔/文檔
      皆已物理刪除,絕不能復活去 S3 抓已不存在的音檔。**不分 status 一律跳過。**
    - 終態(_SKIP_STATUSES):completed / 取消中 / 已取消。
    """
    if not task_doc:
        return False
    return bool(task_doc.get("deleted")) or task_doc.get("status") in _SKIP_STATUSES


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
        task_doc = db.tasks.find_one({"_id": task_id}, {"status": 1, "deleted": 1})
        if _should_skip(task_doc):
            log.info(
                "worker.task.skipped",
                status=task_doc.get("status"),
                deleted=bool(task_doc.get("deleted")),
            )
            progress_store.clear(task_id)
            return

        log.info("worker.task.received")
        if not _claim_task(db, task_id):
            # 另一個 worker 正在處理同一顆（visibility 到期後的重投）
            log.warning("worker.task.claim_lost", task_id=task_id)
            progress_store.clear(task_id)
            return
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
                whisper=get_whisper_processor(job.language),
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
