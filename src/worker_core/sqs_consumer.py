"""
SQS Consumer 主迴圈

職責：
- Long-poll SQS，收到訊息後分派給 transcription_job.process_task
- 驗證 HMAC 簽名，拒絕無效訊息
- 追蹤空閒時間，超過閾值後呼叫 EC2 自動關機
- 啟動 Spot 中斷監控背景執行緒
"""

import sys
import json
import time
import hmac
import hashlib
import signal
import threading

import boto3

from src.worker_core.config import (
    SQS_QUEUE_URL,
    S3_REGION,
    WORKER_SECRET,
    AUTO_SHUTDOWN_IDLE_MINUTES,
    DEFAULT_MODEL,
    MONGODB_DB_NAME,
    SQS_LONG_POLL_SECONDS,
    SQS_VISIBILITY_TIMEOUT_SECONDS,
    SPOT_CHECK_INTERVAL_SECONDS,
)
from src.worker_core.db import get_db
from src.worker_core.heartbeat import (
    start_background_heartbeat,
    write_heartbeat,
)
from src.worker_core.model_cache import get_whisper_processor, get_diarization_pipeline
from src.worker_core.spot_monitor import run_spot_monitor, shutdown_instance
from src.worker_core.transcription_job import process_task
from src.services.progress_store import MongoProgressStore
from src.utils.logger import get_logger
import src.worker_core.state as state

log = get_logger(__name__)


def _verify_message_signature(body: dict) -> bool:
    """驗證 SQS 訊息 HMAC-SHA256 簽名。未設定 WORKER_SECRET 時跳過驗證。"""
    if not WORKER_SECRET:
        return True

    signature = body.pop("_signature", None)
    if not signature:
        log.warning("sqs.message.no_signature")
        return False

    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(
        WORKER_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        log.warning("sqs.message.invalid_signature")
        return False

    return True


def _signal_handler(signum, frame):
    state.shutdown = True
    log.info("worker.shutdown.signal_received", signal=signum)


def main() -> None:
    """SQS Consumer 主迴圈"""
    if not SQS_QUEUE_URL:
        log.error("worker.start_failed", reason="no_sqs_queue_url")
        sys.exit(1)

    # 在主函式中才註冊 signal handler，避免 import state.py 時產生副作用
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    sqs = boto3.client("sqs", region_name=S3_REGION)
    log.info(
        "worker.started",
        sqs_queue=SQS_QUEUE_URL,
        whisper_model=DEFAULT_MODEL,
        db=MONGODB_DB_NAME,
        auto_shutdown_minutes=AUTO_SHUTDOWN_IDLE_MINUTES,
    )

    monitor_thread = threading.Thread(
        target=run_spot_monitor, args=(sqs,), daemon=True, name="SpotMonitor"
    )
    monitor_thread.start()
    log.info("spot.monitor.started", interval_seconds=SPOT_CHECK_INTERVAL_SECONDS)

    get_whisper_processor()
    get_diarization_pipeline()

    # 建 ProgressStore（共用同一份 pymongo 連線）
    progress_store = MongoProgressStore(get_db().task_progress)

    # Heartbeat：上線即寫一筆 "starting"，並開背景執行緒每分鐘 keep-alive
    write_heartbeat(status="starting")
    start_background_heartbeat()
    write_heartbeat(status="idle")

    idle_start = None
    idle_threshold = AUTO_SHUTDOWN_IDLE_MINUTES * 60

    while not state.shutdown:
        try:
            resp = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=SQS_LONG_POLL_SECONDS,
                VisibilityTimeout=SQS_VISIBILITY_TIMEOUT_SECONDS,
            )

            messages = resp.get("Messages", [])
            if not messages:
                if idle_start is None:
                    idle_start = time.time()
                    log.info("worker.idle", auto_shutdown_minutes=AUTO_SHUTDOWN_IDLE_MINUTES)

                if time.time() - idle_start >= idle_threshold:
                    log.info("worker.idle.shutdown_triggered", idle_minutes=AUTO_SHUTDOWN_IDLE_MINUTES)
                    write_heartbeat(status="shutting_down")
                    shutdown_instance()
                    break
                continue

            idle_start = None

            for msg in messages:
                body = json.loads(msg["Body"])
                receipt_handle = msg["ReceiptHandle"]

                if not _verify_message_signature(body):
                    sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
                    log.warning("sqs.message.dropped", task_id=body.get("task_id", "unknown"), reason="invalid_signature")
                    continue

                task_id = body.get("task_id")
                state.current_task_id = task_id
                state.current_receipt_handle = receipt_handle
                write_heartbeat(status="processing", last_task_id=task_id)

                process_task(body, progress_store=progress_store)

                state.current_task_id = None
                state.current_receipt_handle = None
                write_heartbeat(status="idle", last_task_id=task_id, task_completed=True)

                if state.spot_interruption_detected:
                    log.warning("sqs.message.retained", reason="spot_interruption")
                    break

                sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
                log.debug("sqs.message.deleted", task_id=task_id)

        except Exception as e:
            log.error("sqs.poll.error", error=str(e), exc_info=True)
            # 送 Sentry（未 init 時 sentry_sdk.capture_exception 為 no-op）
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except ImportError:
                pass
            time.sleep(5)

    write_heartbeat(status="stopped")
    log.info("worker.stopped")
