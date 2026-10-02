#!/usr/bin/env bash
# 修正 AmazonSSMManagedInstanceCore 架空參數範圍的問題：
# 為四份 policy 建立新版本（含明確 Deny）並設為預設。
# 僅更新 policy 內容；不切換實例、不動共用 role。
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
A=696637902131

for P in prod-web prod-worker staging-web staging-worker; do
  printf "%-18s " "$P"
  aws iam create-policy-version \
    --policy-arn "arn:aws:iam::${A}:policy/transcriber-${P}-policy" \
    --policy-document "file://${D}/transcriber-${P}-policy.json" \
    --set-as-default --query "PolicyVersion.VersionId" --output text
done
echo "✅ 四份 policy 已更新為新版本"
