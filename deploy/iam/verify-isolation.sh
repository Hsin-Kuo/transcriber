#!/usr/bin/env bash
# 唯讀：用 IAM Policy Simulator 驗證隔離是否真的生效。
# 切換任何實例之前都該跑一次 —— policy 寫好不等於生效（見 README 的 managed policy 陷阱）。
set -uo pipefail
A=${AWS_ACCOUNT_ID:-696637902131}; R=${AWS_REGION:-ap-northeast-1}
FAIL=0

chk() { # role action resource expected
  local got
  got=$(aws iam simulate-principal-policy --policy-source-arn "arn:aws:iam::${A}:role/${1}" \
        --action-names "$2" --resource-arns "$3" \
        --query "EvaluationResults[0].EvalDecision" --output text 2>&1)
  case "$4:$got" in
    deny:*Deny|allow:allowed) printf "  ✅ %-9s " "$got" ;;
    *) printf "  ❌ %-9s " "$got"; FAIL=1 ;;
  esac
  echo "${1#transcriber-} $2 ${3##*:}"
}
P() { echo "arn:aws:ssm:${R}:${A}:parameter/$1"; }

echo "═══ staging 不得觸及 prod ═══"
chk transcriber-staging-worker-role ssm:GetParameter "$(P transcriber/mongodb-url)"    deny
chk transcriber-staging-web-role    ssm:GetParameter "$(P transcriber/card-token-kek)" deny
chk transcriber-staging-web-role    ssm:GetParameter "$(P transcriber/jwt-secret)"     deny
chk transcriber-staging-web-role    s3:DeleteObject  "arn:aws:s3:::transcriber-files-${A}/x" deny
chk transcriber-staging-worker-role sqs:ReceiveMessage "arn:aws:sqs:${R}:${A}:transcriber-tasks" deny

echo "═══ worker 不得觸及金流 / jwt ═══"
chk transcriber-prod-worker-role ssm:GetParameter "$(P transcriber/card-token-kek)" deny
chk transcriber-prod-worker-role ssm:GetParameter "$(P transcriber/91app-api-key)"  deny
chk transcriber-prod-worker-role ssm:GetParameter "$(P transcriber/jwt-secret)"     deny
chk transcriber-prod-web-role    ssm:GetParameter "$(P transcriber/hf-token)"       deny

echo "═══ SQS 讀寫分離 ═══"
chk transcriber-prod-web-role    sqs:ReceiveMessage "arn:aws:sqs:${R}:${A}:transcriber-tasks" deny
chk transcriber-prod-worker-role sqs:SendMessage    "arn:aws:sqs:${R}:${A}:transcriber-tasks" deny

echo "═══ 正常路徑必須通 ═══"
for p in jwt-secret mongodb-url worker-secret google-client-id card-token-kek \
         91app-api-key smilepay-grvc resend-api-key email-provider from-email; do
  chk transcriber-prod-web-role ssm:GetParameter "$(P transcriber/$p)" allow
done
for p in mongodb-url worker-secret google-api-key-1 google-api-key-2 hf-token; do
  chk transcriber-prod-worker-role ssm:GetParameter "$(P transcriber/$p)" allow
done
chk transcriber-prod-web-role    sqs:SendMessage    "arn:aws:sqs:${R}:${A}:transcriber-tasks" allow
chk transcriber-prod-worker-role sqs:ReceiveMessage "arn:aws:sqs:${R}:${A}:transcriber-tasks" allow
chk transcriber-staging-web-role s3:PutObject "arn:aws:s3:::transcriber-files-staging-${A}/x" allow

echo "═══ 自我關機：tag condition 要自己傳 context，否則恆為 implicitDeny ═══"
stop() { # role instance tag expected
  local got
  got=$(aws iam simulate-principal-policy --policy-source-arn "arn:aws:iam::${A}:role/${1}" \
        --action-names ec2:StopInstances --resource-arns "arn:aws:ec2:${R}:${A}:instance/${2}" \
        --context-entries "ContextKeyName=ec2:ResourceTag/Name,ContextKeyType=string,ContextKeyValues=$3" \
        --query "EvaluationResults[0].EvalDecision" --output text 2>&1)
  case "$4:$got" in deny:*Deny|allow:allowed) printf "  ✅ %-9s " "$got";; *) printf "  ❌ %-9s " "$got"; FAIL=1;; esac
  echo "${1#transcriber-} 停 tag=$3"
}
stop transcriber-prod-worker-role    i-0d133cca8e6ce23c2 transcriber-gpu-worker   allow
stop transcriber-staging-worker-role i-01a34a514d56269db transcriber-gpu-staging  allow
stop transcriber-staging-worker-role i-0d133cca8e6ce23c2 transcriber-gpu-worker   deny
stop transcriber-prod-worker-role    i-099bcb529f335d20b transcriber-web-server   deny

echo
[ $FAIL -eq 0 ] && echo "✅ 全部符合預期" || { echo "❌ 有項目不符預期——切換前請先修正"; exit 1; }
