"""
自動啟動 GPU Worker 的 Lambda。

觸發來源（兩者皆為冪等，可安全並存）：
1. CloudWatch Alarm → SNS：佇列一有訊息就立刻叫醒（低延遲）。
2. EventBridge 定期排程（rate(2 minutes)）：alarm 只在狀態轉換時 fire 一次，
   遇到 InsufficientInstanceCapacity 這類「暫時性容量枯竭」不會自行重試；
   定期排程負責在容量釋出後把 worker 補起來（自癒）。

啟動策略：先 Spot（便宜），無容量則切 On-Demand 備援。

安全閥：因為 EventBridge 會週期性觸發，Lambda 必須自行確認
「佇列真的有等待任務」才起機，否則會與 worker 閒置 5 分鐘自動關機互打、
把 GPU 長時間叫醒燒錢。

注意：Lambda 不直接消費 SQS 訊息，只負責開機。
"""
import boto3
import os
import time

GPU_INSTANCE_ID = os.environ.get('GPU_INSTANCE_ID', '')  # Spot Instance
ONDEMAND_INSTANCE_ID = os.environ.get('ONDEMAND_INSTANCE_ID', '')  # On-Demand 備援
MAIN_QUEUE_URL = os.environ.get('MAIN_QUEUE_URL', '')
PRIORITY_QUEUE_URL = os.environ.get('PRIORITY_QUEUE_URL', '')

ec2 = boto3.client('ec2', region_name='ap-northeast-1')
sqs = boto3.client('sqs', region_name='ap-northeast-1')


def get_instance_state(instance_id):
    """取得實例狀態"""
    response = ec2.describe_instances(InstanceIds=[instance_id])
    return response['Reservations'][0]['Instances'][0]['State']['Name']


def wait_for_stopped(instance_id, max_wait_seconds=120):
    """等待實例完全停止"""
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        state = get_instance_state(instance_id)
        print(f"⏳ 等待停止中... 目前狀態: {state}")
        if state == 'stopped':
            return True
        time.sleep(5)
    return False


def start_instance_with_retry(instance_id, max_retries=3, initial_delay=3):
    """啟動實例，帶重試機制。容量不足視為暫時性失敗（回 False，交給下次觸發重試）。"""
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            ec2.start_instances(InstanceIds=[instance_id])
            print(f"✅ 實例 {instance_id} 啟動成功")
            return True
        except Exception as e:
            error_msg = str(e)
            if "IncorrectSpotRequestState" in error_msg:
                print(f"⏳ Spot Request 狀態轉換中，{delay} 秒後重試... (嘗試 {attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay *= 2
            elif "InsufficientInstanceCapacity" in error_msg:
                print(f"❌ 無可用容量（{instance_id}），暫時性失敗，等下次觸發重試")
                return False  # 不在本次呼叫內硬重試（容量荒常持續數分鐘）
            else:
                print(f"❌ 啟動失敗: {e}")
                raise
    return False


def try_start_instance(instance_id, label):
    """依實例狀態嘗試啟動（Spot / On-Demand 共用；容量不足回 False 不拋例外）。"""
    state = get_instance_state(instance_id)
    print(f"📊 {label} 實例狀態: {state}")

    if state == 'running':
        print(f"✅ {label} 實例已在運行")
        return True

    if state in ['pending', 'starting']:
        print(f"⏳ {label} 實例啟動中...")
        return True

    if state == 'stopping':
        print(f"🔄 {label} 正在關閉中，等待完全停止...")
        if not wait_for_stopped(instance_id, max_wait_seconds=90):
            print(f"⚠️ 等待停止超時")
            return False
        time.sleep(3)

    if state == 'stopped':
        print(f"🚀 嘗試啟動 {label} 實例...")
        return start_instance_with_retry(instance_id)

    print(f"❌ {label} 狀態異常: {state}")
    return False


def is_any_worker_running():
    """檢查是否已有 Worker 在運行 / 啟動中（避免重複開機）"""
    for instance_id in [GPU_INSTANCE_ID, ONDEMAND_INSTANCE_ID]:
        if instance_id:
            try:
                state = get_instance_state(instance_id)
                if state in ['running', 'pending']:
                    return True
            except Exception:
                pass
    return False


def count_pending_tasks():
    """回傳兩條佇列中等待處理（visible）的訊息總數。

    無法查詢時回傳 None（呼叫端會退回「假設有任務」以維持 alarm 觸發的向後相容）。
    """
    queue_urls = [u for u in (MAIN_QUEUE_URL, PRIORITY_QUEUE_URL) if u]
    if not queue_urls:
        return None  # 未設定佇列 URL → 不做安全閥檢查（相容舊行為）

    total = 0
    for url in queue_urls:
        try:
            attrs = sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=['ApproximateNumberOfMessages'],
            )
            total += int(attrs['Attributes'].get('ApproximateNumberOfMessages', 0))
        except Exception as e:
            print(f"⚠️ 查詢佇列失敗 {url}: {e}")
            return None  # 查詢異常時保守起見不擋（回退相容）
    return total


def lambda_handler(event, context):
    print(f"📨 收到事件")

    if not GPU_INSTANCE_ID and not ONDEMAND_INSTANCE_ID:
        print("⚠️ 未設定任何 GPU 實例 ID")
        return {"status": "error", "message": "No instance IDs configured"}

    # 已有 Worker 在運行 / 啟動中 → 不需再開機（冪等）
    if is_any_worker_running():
        print("✅ 已有 Worker 在運行")
        return {"status": "already_running"}

    # 安全閥：定期排程會週期性觸發，必須確認真的有等待任務才起機，
    # 否則會把閒置關機的 GPU 一直叫醒。
    pending = count_pending_tasks()
    if pending is not None:
        print(f"📊 等待中任務數: {pending}")
        if pending == 0:
            print("💤 無等待任務，不啟動 Worker")
            return {"status": "no_pending_tasks"}

    # 策略：先 Spot，失敗則 On-Demand
    if GPU_INSTANCE_ID:
        if try_start_instance(GPU_INSTANCE_ID, "Spot"):
            return {"status": "spot_started", "instance_id": GPU_INSTANCE_ID}

    if ONDEMAND_INSTANCE_ID:
        print(f"⚠️ Spot 啟動失敗，切換到 On-Demand 備援")
        if try_start_instance(ONDEMAND_INSTANCE_ID, "On-Demand"):
            return {"status": "ondemand_started", "instance_id": ONDEMAND_INSTANCE_ID}

    print("❌ 所有實例暫時無法啟動（可能容量不足），等下次觸發重試")
    return {"status": "no_capacity", "message": "All instances failed to start, will retry"}
