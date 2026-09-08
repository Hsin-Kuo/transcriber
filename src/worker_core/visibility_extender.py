"""SQS visibility 續命背景執行緒。

為什麼需要：`SQS_VISIBILITY_TIMEOUT_SECONDS` 是 600 秒，但單顆任務可以跑更久
（89.9 分鐘音檔在 sequential 路徑實測轉錄 1275 秒）。visibility 一到期，SQS 會
把同一則訊息重投給另一個 worker，於是同一顆任務被同時處理兩次——GPU 與 Gemini
雙重花費、進度互相蓋寫、結果 last-writer-wins，最多重複 maxReceiveCount 次。

這個風險本來就存在（90 分鐘音檔一直都會踩到），只是「長音檔自動走 sequential」
把觸發點從 ~90 分鐘拉低到 ~40 分鐘的常見尺寸，所以必須一起處理。

與 SpotMonitor 的關係：兩者都會呼叫 `change_message_visibility`，但方向相反
（Spot 是縮短以便快速 requeue、這裡是延長）。Spot 中斷偵測到之後本執行緒就停止
續命，不要把剛縮短的 visibility 又推回去。
"""
import threading
import time

from src.worker_core import state
from src.worker_core.config import (
    SQS_VISIBILITY_HEARTBEAT_SECONDS,
    SQS_VISIBILITY_TIMEOUT_SECONDS,
)
from src.utils.logger import get_logger

log = get_logger(__name__)


def extend_once(sqs) -> bool:
    """把當前處理中訊息的 visibility 往後推一個完整 timeout。

    回傳 True 表示確實延長了。沒有進行中的訊息、或 Spot 中斷已觸發時不動作。
    任何 API 失敗只記 log——續命失敗不該中斷正在跑的轉錄。
    """
    if state.spot_interruption_detected:
        return False
    receipt_handle = state.current_receipt_handle
    queue_url = state.current_queue_url
    if not receipt_handle or not queue_url:
        return False

    try:
        sqs.change_message_visibility(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=SQS_VISIBILITY_TIMEOUT_SECONDS,
        )
        log.debug(
            "sqs.visibility.extended",
            task_id=state.current_task_id,
            timeout_seconds=SQS_VISIBILITY_TIMEOUT_SECONDS,
        )
        return True
    except Exception as e:
        # 續命失敗最壞的結果是訊息被重投，而重投有 processing claim 這道防線接住
        log.warning(
            "sqs.visibility.extend_failed",
            task_id=state.current_task_id,
            error=str(e),
        )
        return False


def run_visibility_extender(sqs, interval_seconds: int = SQS_VISIBILITY_HEARTBEAT_SECONDS) -> None:
    """背景迴圈：每 interval 秒續命一次，直到 worker 關閉。"""
    log.info(
        "sqs.visibility.extender_started",
        interval_seconds=interval_seconds,
        timeout_seconds=SQS_VISIBILITY_TIMEOUT_SECONDS,
    )
    while not state.shutdown:
        time.sleep(interval_seconds)
        if state.shutdown:
            break
        extend_once(sqs)


def start_visibility_extender(sqs) -> threading.Thread:
    thread = threading.Thread(
        target=run_visibility_extender,
        args=(sqs,),
        daemon=True,
        name="SqsVisibilityExtender",
    )
    thread.start()
    return thread
