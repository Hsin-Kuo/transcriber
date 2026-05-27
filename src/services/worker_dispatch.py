"""WorkerDispatch — 對應 CONTEXT.md「WorkerDispatch」，[[Task dispatch]] 的 AWS adapter。

建立 Task 後把音檔送到 S3 [[Handoff audio]] 位置、簽 HMAC 訊息、發進 SQS。任一步
失敗就把 Task 標 failed。GPU Worker 取走 handoff、轉成 [[Compact audio]] 後 DELETE。

本模組以可注入的 boto3 client 與 handoff uploader 為 interface，方便測試以 mock
替換而不必 monkeypatch 環境變數。main.py startup 建好後透過
task_dispatch.init_task_dispatch() 註冊為單例。
"""
import asyncio
import hashlib
import hmac
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from src.database.sync_client import get_sync_db
from src.models.worker_job import TranscriptionJob
from src.services.task_dispatch import DispatchResult
from src.utils.logger import get_logger
from src.utils.sentry_helpers import create_background_task

log = get_logger(__name__)


class WorkerDispatch:
    """[[Task dispatch]] 的 AWS adapter：封裝 Web Server → GPU Worker 的 task 移交。

    Construction-time DI：sqs_client + handoff_uploader 由呼叫端注入，
    測試可塞 mock。
    """

    def __init__(
        self,
        *,
        sqs_client: Any,
        sqs_queue_url: str,
        worker_secret: str,
        handoff_uploader: Callable[[str, Path, str], str],
    ):
        """
        Args:
            sqs_client: boto3.client("sqs", region_name=...)
            sqs_queue_url: SQS queue URL；空字串時略過發送（dev/未配置）
            worker_secret: HMAC 簽名密鑰；空字串時略過簽章（dev/未配置）
            handoff_uploader: callable(task_id, local_path, ext) -> str
                              把音檔上傳到 S3 `handoff/{task_id}.{ext}`，回傳 s3:// URI
                              （包 blocking I/O；典型實作見 storage_service.upload_to_handoff）
        """
        self._sqs_client = sqs_client
        self._sqs_queue_url = sqs_queue_url
        self._worker_secret = worker_secret
        self._handoff_uploader = handoff_uploader

    # ── public（TaskDispatch Protocol）─────────────────────────

    async def submit(
        self,
        *,
        job: TranscriptionJob,
        audio_local_path: Path,
        temp_dir: Path,
        user_tier: str,
    ) -> DispatchResult:
        """背景上傳 S3 + 送 SQS（fire-and-forget），立即返回 status=pending。

        實際工作在 create_background_task 內（失敗會送 Sentry、把 task 標 failed、
        清 temp_dir）。後續由 GPU Worker 從 SQS 取走。

        Args:
            job: TranscriptionJob（含 task_id + 轉錄參數）；schema 見 src/models/worker_job.py
            audio_local_path: 已落地的音檔絕對路徑
            temp_dir: 整個 temp 工作區，dispatch 完成後刪
            user_tier: free / pro / ...，決定 S3 路徑 prefix
        """
        coro = self._dispatch(
            job=job,
            audio_local_path=audio_local_path,
            temp_dir=temp_dir,
            user_tier=user_tier,
        )
        create_background_task(coro, name=f"worker_dispatch:{job.task_id}")
        return DispatchResult(status="pending", queue_position=None)

    def start(self) -> None:
        """AWS adapter 無 server 端背景迴圈（轉錄迴圈在 GPU Worker process）。"""

    # ── internal ────────────────────────────────────────────

    async def _dispatch(
        self,
        *,
        job: TranscriptionJob,
        audio_local_path: Path,
        temp_dir: Path,
        user_tier: str,
    ) -> None:
        task_id = job.task_id
        try:
            loop = asyncio.get_event_loop()

            # 1. Handoff S3 上傳（blocking → executor）
            # ext 從本機檔案的副檔名推；job.handoff_ext 應該由 caller 設成同一值。
            ext = audio_local_path.suffix.lstrip(".").lower()
            await loop.run_in_executor(
                None, self._handoff_uploader, task_id, audio_local_path, ext
            )
            log.debug("dispatch.handoff_uploaded", task_id=task_id, ext=ext)

            # 2. SQS 送出（model_dump → sign envelope → JSON）
            if self._sqs_queue_url:
                payload = self._sign(job.model_dump())
                await loop.run_in_executor(None, self._send_sqs_blocking, payload)
                log.info("dispatch.sqs_message_sent", task_id=task_id)
            else:
                log.warning("dispatch.sqs_queue_url_missing", task_id=task_id)

        except Exception as e:
            log.error("dispatch.failed", task_id=task_id, error=str(e), exc_info=True)
            self._mark_task_failed(task_id, str(e))
            raise  # 讓 create_background_task 的 Sentry hook 抓到
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _sign(self, payload: dict) -> dict:
        """為 SQS 訊息附 HMAC-SHA256 簽章。未設定 secret 時跳過。"""
        if not self._worker_secret:
            return payload
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        signature = hmac.new(
            self._worker_secret.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()
        return {**payload, "_signature": signature}

    def _send_sqs_blocking(self, payload: dict) -> None:
        self._sqs_client.send_message(
            QueueUrl=self._sqs_queue_url,
            MessageBody=json.dumps(payload),
        )

    def _mark_task_failed(self, task_id: str, error_msg: str) -> None:
        try:
            get_sync_db().tasks.update_one(
                {"_id": task_id},
                {
                    "$set": {
                        "status": "failed",
                        "error": {
                            "code": "UPLOAD_FAILED",
                            "message": f"音檔上傳失敗: {error_msg}",
                        },
                    }
                },
            )
        except Exception as db_err:
            log.error(
                "dispatch.mark_failed_error",
                task_id=task_id,
                error=str(db_err),
                exc_info=True,
            )
