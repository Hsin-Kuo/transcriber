"""Worker dispatch seam — Web Server 把 Task 移交給 Worker 的封裝。

對應 CONTEXT.md「Worker dispatch」：AWS 模式下，建立 Task 後要把音檔送到
S3、簽 HMAC 訊息、發進 SQS。任一步失敗就把 Task 標 failed。

本模組以可注入的 boto3 client 與 S3 uploader 為 interface，方便測試以 mock
替換而不必 monkeypatch 環境變數。

Lifecycle：main.py startup 一次性呼叫 init_worker_dispatch()；routers 拿
get_worker_dispatch() 用同一實例。local 模式下不需要 init。
"""
import asyncio
import hashlib
import hmac
import json
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from src.database.sync_client import get_sync_db
from src.models.worker_job import TranscriptionWorkerJob
from src.utils.sentry_helpers import create_background_task


class WorkerDispatch:
    """封裝 Web Server → Worker 的 task 移交。

    Construction-time DI：sqs_client + s3_uploader 由呼叫端注入，
    測試可塞 mock。
    """

    def __init__(
        self,
        *,
        sqs_client: Any,
        sqs_queue_url: str,
        worker_secret: str,
        s3_uploader: Callable[[str, Path, str], None],
    ):
        """
        Args:
            sqs_client: boto3.client("sqs", region_name=...)
            sqs_queue_url: SQS queue URL；空字串時略過發送（dev/未配置）
            worker_secret: HMAC 簽名密鑰；空字串時略過簽章（dev/未配置）
            s3_uploader: callable(task_id, local_path, tier) -> None
                         負責把音檔上傳到 S3 對應 tier 路徑（包 blocking I/O）
        """
        self._sqs_client = sqs_client
        self._sqs_queue_url = sqs_queue_url
        self._worker_secret = worker_secret
        self._s3_uploader = s3_uploader

    # ── public ──────────────────────────────────────────────

    def fire_and_forget(
        self,
        *,
        job: TranscriptionWorkerJob,
        audio_local_path: Path,
        temp_dir: Path,
        user_tier: str,
    ) -> None:
        """非阻擋發射：背景上傳 S3 + 送 SQS；失敗自動把 task 標 failed + 清 temp_dir。

        本方法立即返回，實際工作在 create_background_task 內（失敗會送 Sentry）。

        Args:
            job: typed Worker job（含 task_id + 轉錄參數）；schema 見 src/models/worker_job.py
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

    # ── internal ────────────────────────────────────────────

    async def _dispatch(
        self,
        *,
        job: TranscriptionWorkerJob,
        audio_local_path: Path,
        temp_dir: Path,
        user_tier: str,
    ) -> None:
        task_id = job.task_id
        try:
            loop = asyncio.get_event_loop()

            # 1. S3 上傳（blocking → executor）
            await loop.run_in_executor(
                None, self._s3_uploader, task_id, audio_local_path, user_tier
            )
            print(f"☁️  音檔已上傳到 S3: uploads/{user_tier}/{task_id}.mp3", flush=True)

            # 2. SQS 送出（model_dump → sign envelope → JSON）
            if self._sqs_queue_url:
                payload = self._sign(job.model_dump())
                await loop.run_in_executor(None, self._send_sqs_blocking, payload)
                print(f"📨 已發送 SQS 訊息: {task_id}", flush=True)
            else:
                print(
                    f"⚠️  SQS_QUEUE_URL 未設定，任務 {task_id} 保持 pending 狀態",
                    flush=True,
                )

        except Exception as e:
            print(f"❌ Worker dispatch 失敗: {task_id}: {e}", flush=True)
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
            print(f"❌ 更新任務狀態失敗: {task_id}: {db_err}", flush=True)


# ── module-level singleton（與既有 _transcription_service 同 pattern）──

_instance: Optional[WorkerDispatch] = None


def init_worker_dispatch(dispatch: WorkerDispatch) -> None:
    """main.py startup 呼叫一次。local 模式不需要呼叫。"""
    global _instance
    _instance = dispatch


def get_worker_dispatch() -> WorkerDispatch:
    """取得已初始化的 dispatch 實例。

    Raises:
        RuntimeError: 若尚未 init（caller 漏調 init_worker_dispatch）
    """
    if _instance is None:
        raise RuntimeError(
            "WorkerDispatch 尚未初始化；main.py startup 應呼叫 init_worker_dispatch()"
        )
    return _instance
