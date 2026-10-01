#!/usr/bin/env bash
# 把實例切到最小權限 instance profile（或回滾）。
#
#   bash switch-instance-profile.sh <instance-id> <profile-name>
#   bash switch-instance-profile.sh i-01a34a514d56269db transcriber-staging-worker-profile
#   bash switch-instance-profile.sh i-01a34a514d56269db transcriber-ec2-profile   # 回滾
#
# 注意：ReplaceIamInstanceProfileAssociation 需要實例在 running 狀態；停機中的
# association 雖顯示 associated，API 仍回 IncorrectState。本腳本會自動先開機。
# 切換後必須重啟服務（或 reboot），否則進程仍在用啟動時讀進記憶體的舊值。
set -euo pipefail
R=${AWS_REGION:-ap-northeast-1}
I=${1:?用法: $0 <instance-id> <profile-name>}
P=${2:?用法: $0 <instance-id> <profile-name>}

state() { aws ec2 describe-instances --region "$R" --instance-ids "$I" \
            --query "Reservations[0].Instances[0].State.Name" --output text; }

if [ "$(state)" != "running" ]; then
  echo "▶ 開機（換 profile 需要 running）…"
  aws ec2 start-instances --region "$R" --instance-ids "$I" >/dev/null
  aws ec2 wait instance-running --region "$R" --instance-ids "$I"
fi
echo "  狀態: $(state)"

ASSOC=$(aws ec2 describe-iam-instance-profile-associations --region "$R" \
  --filters "Name=instance-id,Values=$I" "Name=state,Values=associated" \
  --query "IamInstanceProfileAssociations[0].AssociationId" --output text)
echo "▶ ${ASSOC} → ${P}"
aws ec2 replace-iam-instance-profile-association --region "$R" \
  --association-id "$ASSOC" --iam-instance-profile "Name=${P}" \
  --query "IamInstanceProfileAssociation.State" --output text

echo "▶ reboot（讓進程以新憑證重讀 SSM）…"
aws ec2 reboot-instances --region "$R" --instance-ids "$I"
sleep 45
aws ec2 wait instance-running --region "$R" --instance-ids "$I"
aws ec2 describe-instances --region "$R" --instance-ids "$I" \
  --query "Reservations[0].Instances[0].[State.Name,IamInstanceProfile.Arn]" --output text
echo "✅ 完成。GPU worker 閒置 3 分鐘會自關，要驗證請立刻送任務。"
