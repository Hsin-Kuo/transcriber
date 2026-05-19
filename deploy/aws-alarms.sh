#!/bin/bash
# CloudWatch alarms reconciler — idempotent，可隨時重跑。
# put-metric-alarm 本身是 upsert，重跑只會把 alarm 同步到下方定義。
#
# Usage:
#   bash deploy/aws-alarms.sh
#
# Override（如果改了 region / account / queue 名 / web EC2）：
#   AWS_REGION=... AWS_ACCOUNT_ID=... SQS_QUEUE_NAME=... WEB_INSTANCE_ID=... \
#     bash deploy/aws-alarms.sh

set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-696637902131}"
QUEUE_NAME="${SQS_QUEUE_NAME:-transcriber-tasks}"
WEB_INSTANCE_ID="${WEB_INSTANCE_ID:-i-099bcb529f335d20b}"

ALERTS_TOPIC="arn:aws:sns:${REGION}:${ACCOUNT_ID}:transcriber-alerts"
SQS_LAMBDA_TOPIC="arn:aws:sns:${REGION}:${ACCOUNT_ID}:transcriber-sqs-alarm"
EC2_RECOVER_ACTION="arn:aws:automate:${REGION}:ec2:recover"

echo "== reconciling alarms in ${REGION} =="

# 1. sqs-queue-depth — 佇列堆積警示（≥10 訊息持續 5 分鐘）
aws cloudwatch put-metric-alarm \
  --region "$REGION" \
  --alarm-name sqs-queue-depth \
  --alarm-description "SQS queue depth > 10 for 5 minutes - worker may be down" \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Maximum \
  --dimensions "Name=QueueName,Value=${QUEUE_NAME}" \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 10 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "$ALERTS_TOPIC"
echo "  OK  sqs-queue-depth"

# 2. transcriber-sqs-messages-alarm — 喚醒 GPU 用的快速觸發
#    visible >= 1 達 1 分鐘 → SNS → Lambda(transcriber-gpu-starter)
#    AlarmActions 和 OKActions 都接 Lambda，這樣 ALARM↔OK 翻轉都會觸發。
aws cloudwatch put-metric-alarm \
  --region "$REGION" \
  --alarm-name transcriber-sqs-messages-alarm \
  --alarm-description "Trigger GPU starter when SQS has messages" \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Maximum \
  --dimensions "Name=QueueName,Value=${QUEUE_NAME}" \
  --period 60 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$SQS_LAMBDA_TOPIC" \
  --ok-actions "$SQS_LAMBDA_TOPIC"
echo "  OK  transcriber-sqs-messages-alarm"

# 3. transcriber-sqs-oldest-message-stuck — 真.卡住偵測
#    用 Minimum：訊息任一秒被 worker 收走（visible→0）就 reset 該分鐘 datapoint。
#    連續 10 個 1 分鐘 datapoint 都 ≥1 才觸發 → 真的「整整 10 分鐘沒人收訊息」。
#    避開 ApproximateAgeOfOldestMessage 把 in-flight 也算進去造成的長任務誤觸。
aws cloudwatch put-metric-alarm \
  --region "$REGION" \
  --alarm-name transcriber-sqs-oldest-message-stuck \
  --alarm-description "SQS 有訊息可見且連續 10 分鐘沒被任何 worker 收走（worker 卡住 / 沒被 Lambda 啟動）。用 Minimum 統計：只要任何一分鐘內 visible 曾經降到 0 就不算 breach，避免 worker 正常處理中時誤觸。" \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Minimum \
  --dimensions "Name=QueueName,Value=${QUEUE_NAME}" \
  --period 60 \
  --evaluation-periods 10 \
  --datapoints-to-alarm 10 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --treat-missing-data notBreaching \
  --alarm-actions "$ALERTS_TOPIC"
echo "  OK  transcriber-sqs-oldest-message-stuck"

# 4. transcriber-ec2-auto-recover — Web Server 硬體層故障自動 recover
#    用 AWS 內建 ec2:recover action（不走 SNS），系統層 status check fail → AWS 自動換 host。
aws cloudwatch put-metric-alarm \
  --region "$REGION" \
  --alarm-name transcriber-ec2-auto-recover \
  --alarm-description "Auto recover EC2 web server on system status check failure" \
  --metric-name StatusCheckFailed_System \
  --namespace AWS/EC2 \
  --statistic Maximum \
  --dimensions "Name=InstanceId,Value=${WEB_INSTANCE_ID}" \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions "$EC2_RECOVER_ACTION"
echo "  OK  transcriber-ec2-auto-recover"

echo "== done =="
