#!/bin/bash
# S3 音檔 Lifecycle 規則套用腳本（冪等）
#
# 音檔依方案分資料夾存放，靠 S3 Lifecycle 自動過期刪除（見 CLAUDE.md / compact.py）：
#   uploads/free/      → 3 天
#   uploads/basic/     → 7 天
#   uploads/pro/       → 7 天
#   uploads/enterprise/→ 7 天
#   uploads/kept/      → 不設規則（手動保留 / 降級寬限期搬移後由各 tier 資料夾的規則接手）
#
# 這份是 lifecycle 的「唯一真實來源」。過去規則是手動在 console 設的、未進版控，
# 導致建 staging 時整組漏設（staging bucket 一度完全沒有 lifecycle，音檔無限累積）。
# 改用本腳本套用，bucket 名稱由 prod|staging 帶入，prod/staging 共用同一份規則。
#
# 用法：
#   bash deploy/apply-s3-lifecycle.sh prod      # 套到 prod bucket
#   bash deploy/apply-s3-lifecycle.sh staging   # 套到 staging bucket
#   bash deploy/apply-s3-lifecycle.sh prod --dry-run   # 只印出將套用的設定，不實際寫入
#
# 冪等：put-bucket-lifecycle-configuration 為整批覆寫，重複執行結果一致。
set -euo pipefail

APP_ENV="${1:-}"
DRY_RUN="${2:-}"
case "$APP_ENV" in
  prod)
    S3_BUCKET=transcriber-files-696637902131 ;;
  staging)
    S3_BUCKET=transcriber-files-staging-696637902131 ;;
  *)
    echo "用法: $0 [prod|staging] [--dry-run]"; exit 1 ;;
esac
S3_REGION=ap-northeast-1

LIFECYCLE_JSON=$(cat <<'JSON'
{
  "Rules": [
    {"ID": "free-audio-3days", "Filter": {"Prefix": "uploads/free/"}, "Status": "Enabled", "Expiration": {"Days": 3}},
    {"ID": "basic-audio-7days", "Filter": {"Prefix": "uploads/basic/"}, "Status": "Enabled", "Expiration": {"Days": 7}},
    {"ID": "pro-audio-7days", "Filter": {"Prefix": "uploads/pro/"}, "Status": "Enabled", "Expiration": {"Days": 7}},
    {"ID": "enterprise-audio-7days", "Filter": {"Prefix": "uploads/enterprise/"}, "Status": "Enabled", "Expiration": {"Days": 7}}
  ]
}
JSON
)

echo "=== S3 Lifecycle：${APP_ENV}（bucket=${S3_BUCKET}）==="

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[DRY-RUN] 將套用以下設定（不實際寫入）："
  echo "$LIFECYCLE_JSON"
  echo
  echo "[DRY-RUN] 目前 bucket 上的設定："
  aws s3api get-bucket-lifecycle-configuration \
    --bucket "$S3_BUCKET" --region "$S3_REGION" --output json 2>&1 || true
  exit 0
fi

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$S3_BUCKET" \
  --region "$S3_REGION" \
  --lifecycle-configuration "$LIFECYCLE_JSON"

echo "=== 套用完成，回讀驗證 ==="
aws s3api get-bucket-lifecycle-configuration \
  --bucket "$S3_BUCKET" --region "$S3_REGION" --output json
