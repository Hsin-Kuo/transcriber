"""
AWS Spot 中斷偵測與 EC2 自動關機

Spot Instance 被回收前約 2 分鐘，EC2 metadata endpoint 會回傳 200。
背景執行緒每 30 秒輪詢一次；偵測到中斷後：
1. 把當前任務重置為 pending，讓其他 Worker 接手
2. 縮短 SQS 訊息的 visibility timeout，讓其他 Worker 30 秒內可見
"""

import time
import urllib.request

import boto3

from src.worker_core.config import S3_REGION, SPOT_CHECK_INTERVAL_SECONDS, SPOT_INTERRUPT_VISIBILITY_TIMEOUT
from src.worker_core.db import get_db, update_task
from src.utils.logger import get_logger
import src.worker_core.state as state

log = get_logger(__name__)


def _check_spot_interruption() -> bool:
    """輪詢 EC2 metadata，偵測 Spot 中斷預警（約 2 分鐘前出現）"""
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT",
        )
        token = urllib.request.urlopen(token_req, timeout=1).read().decode()
        req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/spot/termination-time",
            headers={"X-aws-ec2-metadata-token": token},
        )
        urllib.request.urlopen(req, timeout=1)
        return True  # endpoint 回應 → 即將中斷
    except Exception:
        return False  # 404 或 timeout 視為正常


def _handle_spot_interruption(sqs) -> None:
    """偵測到中斷後：重置任務狀態、縮短 SQS visibility timeout"""
    log.warning("spot.interruption.detected")

    if state.current_task_id:
        try:
            db = get_db()
            update_task(db, state.current_task_id, {
                "status": "pending",
                "progress": "Worker 被 Spot 中斷，重新排隊等待處理...",
            })
            log.info("spot.task.requeued", task_id=state.current_task_id)
        except Exception as e:
            log.error("spot.task.requeue_failed", task_id=state.current_task_id, error=str(e))

    # 必須打到訊息實際所屬的佇列（priority 或 normal），不可用全域 SQS_QUEUE_URL，
    # 否則 priority 任務的快速 requeue 會打錯佇列。
    if state.current_receipt_handle and state.current_queue_url:
        try:
            sqs.change_message_visibility(
                QueueUrl=state.current_queue_url,
                ReceiptHandle=state.current_receipt_handle,
                VisibilityTimeout=SPOT_INTERRUPT_VISIBILITY_TIMEOUT,
            )
            log.info("spot.sqs.visibility_shortened", timeout_seconds=SPOT_INTERRUPT_VISIBILITY_TIMEOUT)
        except Exception as e:
            log.error("spot.sqs.visibility_change_failed", error=str(e))


def shutdown_instance() -> None:
    """關閉當前 EC2 實例（用於空閒自動關機）"""
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT",
        )
        token = urllib.request.urlopen(token_req, timeout=2).read().decode()
        instance_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        instance_id = urllib.request.urlopen(instance_req, timeout=2).read().decode()

        log.info("worker.instance.stopping", instance_id=instance_id)
        ec2 = boto3.client("ec2", region_name=S3_REGION)
        ec2.stop_instances(InstanceIds=[instance_id])
        log.info("worker.instance.stop_sent")
    except Exception as e:
        log.error("worker.instance.stop_failed", error=str(e))


def run_spot_monitor(sqs) -> None:
    """背景執行緒：每 SPOT_CHECK_INTERVAL_SECONDS 秒輪詢 Spot 中斷預警"""
    while not state.shutdown:
        time.sleep(SPOT_CHECK_INTERVAL_SECONDS)
        if not state.shutdown and _check_spot_interruption():
            state.spot_interruption_detected = True
            state.shutdown = True
            _handle_spot_interruption(sqs)
            break
    log.info("spot.monitor.stopped")
