"""
Worker 執行時共享狀態

這些變數由主迴圈與 SpotMonitor 背景執行緒共享：
- shutdown: 觸發後主迴圈退出
- spot_interruption_detected: Spot 中斷預警，主迴圈保留 SQS 訊息
- current_task_id / current_receipt_handle: 供 SpotMonitor 執行緒重置任務用

Signal handler 的註冊在 sqs_consumer.main() 中執行，
避免 import 時產生副作用。
"""

from typing import Optional

shutdown: bool = False
spot_interruption_detected: bool = False
current_task_id: Optional[str] = None
current_receipt_handle: Optional[str] = None
