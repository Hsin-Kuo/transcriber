#!/bin/bash
# Worker 開機自動把固定 EIP 綁到自己 — systemd ExecStartPre 呼叫。
#
# 目的：GPU Worker（Spot/On-Demand）每次啟動都拿隨機 public IP，導致對外呼叫
# （Gemini 標點/摘要）的來源 IP 不固定，無法上 API key IP 白名單。此腳本讓
# 無論 Spot 或 On-Demand 哪台起來，都搶同一顆 EIP，對外出口 IP 恆定。
#
# EIP allocation id 由 .env.worker 的 WORKER_EIP_ALLOC_ID 提供（prod/staging 各自帶）。
# 未設定則直接 skip（例如尚未配 EIP 的環境），不阻擋 worker 啟動。
#
# best-effort：關聯失敗只告警、exit 0，避免擋掉轉錄主流程（寧可 IP 沒綁也要能跑）。

set -uo pipefail

if [ -z "${WORKER_EIP_ALLOC_ID:-}" ]; then
  echo "[eip] WORKER_EIP_ALLOC_ID 未設定，skip EIP 關聯"
  exit 0
fi

# IMDSv2（web/worker 已收緊成 v2-required）
TOKEN=$(curl -s -m 5 -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 120") || true
if [ -z "${TOKEN:-}" ]; then
  echo "[eip] 取不到 IMDSv2 token，skip（非 EC2 或 IMDS 不可用）"
  exit 0
fi

imds() {
  curl -s -m 5 -H "X-aws-ec2-metadata-token: $TOKEN" \
    "http://169.254.169.254/latest/meta-data/$1"
}

INSTANCE_ID=$(imds instance-id)
REGION=$(imds placement/region)

if [ -z "${INSTANCE_ID:-}" ] || [ -z "${REGION:-}" ]; then
  echo "[eip] 取不到 instance-id/region，skip"
  exit 0
fi

echo "[eip] 關聯 ${WORKER_EIP_ALLOC_ID} → ${INSTANCE_ID} (${REGION})"
# --allow-reassociation：把 EIP 從上一台 worker（Spot↔On-Demand）搬過來
if aws ec2 associate-address \
    --region "$REGION" \
    --allocation-id "$WORKER_EIP_ALLOC_ID" \
    --instance-id "$INSTANCE_ID" \
    --allow-reassociation \
    --output text >/dev/null; then
  echo "[eip] 關聯成功"
else
  echo "[eip] ⚠️ 關聯失敗（檢查 IAM ec2:AssociateAddress / allocation id）；worker 仍繼續啟動"
fi
exit 0
