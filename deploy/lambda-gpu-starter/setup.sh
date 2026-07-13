#!/usr/bin/env bash
#
# 部署 transcriber-gpu-starter Lambda + 定期重試機制（冪等，可重跑）。
#
# 做四件事：
#   1. 打包並更新 Lambda 程式碼（lambda_function.py）
#   2. 補齊 Lambda 環境變數（佇列 URL）
#   3. 補齊 IAM policy（priority queue 的 sqs:GetQueueAttributes）
#   4. 建立 EventBridge 定期排程（rate(2 minutes)）→ 觸發 Lambda
#
# 背景：CloudWatch alarm 只在狀態轉換時觸發一次，遇到 InsufficientInstanceCapacity
# 不會自行重試；此排程負責在容量釋出後自動把 worker 補起來。
#
# 用法：bash deploy/lambda-gpu-starter/setup.sh
set -euo pipefail

REGION="ap-northeast-1"
ACCOUNT_ID="696637902131"
FUNC="transcriber-gpu-starter"
RULE="transcriber-gpu-starter-periodic-retry"
SCHEDULE="rate(2 minutes)"
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/transcriber-lambda-policy"
MAIN_QUEUE_URL="https://sqs.${REGION}.amazonaws.com/${ACCOUNT_ID}/transcriber-tasks"
PRIORITY_QUEUE_URL="https://sqs.${REGION}.amazonaws.com/${ACCOUNT_ID}/transcriber-tasks-priority"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> 1/4 更新 Lambda 程式碼"
ZIP="$(mktemp -d)/function.zip"
(cd "$HERE" && zip -q -j "$ZIP" lambda_function.py)
aws lambda update-function-code --region "$REGION" \
  --function-name "$FUNC" --zip-file "fileb://$ZIP" >/dev/null
aws lambda wait function-updated --region "$REGION" --function-name "$FUNC"

echo "==> 2/4 補齊環境變數（保留既有 GPU/ONDEMAND ID）"
EXISTING=$(aws lambda get-function-configuration --region "$REGION" \
  --function-name "$FUNC" --query 'Environment.Variables' --output json)
GPU_ID=$(echo "$EXISTING" | python3 -c "import sys,json;print(json.load(sys.stdin).get('GPU_INSTANCE_ID',''))")
OND_ID=$(echo "$EXISTING" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ONDEMAND_INSTANCE_ID',''))")
aws lambda update-function-configuration --region "$REGION" --function-name "$FUNC" \
  --environment "Variables={GPU_INSTANCE_ID=$GPU_ID,ONDEMAND_INSTANCE_ID=$OND_ID,MAIN_QUEUE_URL=$MAIN_QUEUE_URL,PRIORITY_QUEUE_URL=$PRIORITY_QUEUE_URL}" \
  >/dev/null
aws lambda wait function-updated --region "$REGION" --function-name "$FUNC"

echo "==> 3/4 更新 IAM policy（priority queue 讀取權限，見 iam-policy.json）"
# 刪除最舊的非預設版本以避免 5 版上限（IAM policy 最多 5 個版本）
VERSIONS=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
  --query 'Versions[?IsDefaultVersion==`false`].VersionId' --output text)
COUNT=$(echo "$VERSIONS" | wc -w | tr -d ' ')
if [ "$COUNT" -ge 4 ]; then
  OLDEST=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
    --query 'sort_by(Versions[?IsDefaultVersion==`false`],&CreateDate)[0].VersionId' --output text)
  aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$OLDEST"
fi
aws iam create-policy-version --policy-arn "$POLICY_ARN" \
  --policy-document "file://$HERE/iam-policy.json" --set-as-default >/dev/null
echo "    IAM policy 已更新"

echo "==> 4/4 建立 EventBridge 定期排程"
aws events put-rule --region "$REGION" --name "$RULE" \
  --schedule-expression "$SCHEDULE" \
  --description "定期重試啟動 GPU worker（補 alarm 一次性觸發之不足；Lambda 端有無任務安全閥）" \
  --state ENABLED >/dev/null
# 允許 EventBridge 呼叫 Lambda（statement-id 冪等，已存在則忽略）
aws lambda add-permission --region "$REGION" --function-name "$FUNC" \
  --statement-id "eventbridge-periodic-retry" \
  --action "lambda:InvokeFunction" --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE}" \
  >/dev/null 2>&1 || echo "    (invoke 權限已存在，略過)"
aws events put-targets --region "$REGION" --rule "$RULE" \
  --targets "Id=1,Arn=arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNC}" >/dev/null

echo "✅ 完成。排程：${SCHEDULE} ；停用排程：aws events disable-rule --region ${REGION} --name ${RULE}"
