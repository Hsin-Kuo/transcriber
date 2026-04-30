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

from src.worker_core.config import SQS_QUEUE_URL, S3_REGION, SPOT_CHECK_INTERVAL_SECONDS, SPOT_INTERRUPT_VISIBILITY_TIMEOUT
from src.worker_core.db import get_db, update_task
import src.worker_core.state as state


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
    print("⚠️ [Spot] 收到中斷預警！開始清理，約 2 分鐘後關機...")

    if state.current_task_id:
        try:
            db = get_db()
            update_task(db, state.current_task_id, {
                "status": "pending",
                "progress": "Worker 被 Spot 中斷，重新排隊等待處理...",
            })
            print(f"🔄 [Spot] 已將任務 {state.current_task_id} 重置為 pending")
        except Exception as e:
            print(f"⚠️ [Spot] 無法重置任務狀態: {e}")

    if state.current_receipt_handle and SQS_QUEUE_URL:
        try:
            sqs.change_message_visibility(
                QueueUrl=SQS_QUEUE_URL,
                ReceiptHandle=state.current_receipt_handle,
                VisibilityTimeout=SPOT_INTERRUPT_VISIBILITY_TIMEOUT,
            )
            print(f"📨 [Spot] SQS 消息可見時間已縮短，其他 Worker {SPOT_INTERRUPT_VISIBILITY_TIMEOUT} 秒後可接手")
        except Exception as e:
            print(f"⚠️ [Spot] 無法修改 SQS 可見時間: {e}")


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

        print(f"🔌 正在關閉實例 {instance_id}...")
        ec2 = boto3.client("ec2", region_name=S3_REGION)
        ec2.stop_instances(InstanceIds=[instance_id])
        print("✅ 已發送關機指令")
    except Exception as e:
        print(f"⚠️ 無法自動關機: {e}")


def run_spot_monitor(sqs) -> None:
    """背景執行緒：每 SPOT_CHECK_INTERVAL_SECONDS 秒輪詢 Spot 中斷預警"""
    while not state.shutdown:
        time.sleep(SPOT_CHECK_INTERVAL_SECONDS)
        if not state.shutdown and _check_spot_interruption():
            state.spot_interruption_detected = True
            state.shutdown = True
            _handle_spot_interruption(sqs)
            break
    print("🛑 [Spot Monitor] 執行緒已結束")
