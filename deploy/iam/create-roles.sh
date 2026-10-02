#!/usr/bin/env bash
# transcriber IAM 拆分 — Step 2+3：建立 policy / role / instance profile
# 純新增：不修改也不刪除任何現有資源，不切換任何實例。
set -euo pipefail

D="$(cd "$(dirname "$0")" && pwd)"
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
SSM_CORE="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"

for P in prod-web prod-worker staging-web staging-worker; do
  NAME="transcriber-${P}"
  echo "──────── ${NAME} ────────"

  ARN=$(aws iam create-policy \
      --policy-name "${NAME}-policy" \
      --policy-document "file://${D}/${NAME}-policy.json" \
      --description "transcriber ${P} - least privilege (2026-10-01)" \
      --query "Policy.Arn" --output text)
  echo "  policy  : ${ARN}"

  aws iam create-role --role-name "${NAME}-role" \
      --assume-role-policy-document "$TRUST" \
      --description "transcriber ${P}" --query "Role.Arn" --output text \
    | sed 's/^/  role    : /'

  aws iam attach-role-policy --role-name "${NAME}-role" --policy-arn "$ARN"
  aws iam attach-role-policy --role-name "${NAME}-role" --policy-arn "$SSM_CORE"
  echo "  attached: ${NAME}-policy + AmazonSSMManagedInstanceCore"

  aws iam create-instance-profile --instance-profile-name "${NAME}-profile" \
      --query "InstanceProfile.Arn" --output text | sed 's/^/  profile : /'
  aws iam add-role-to-instance-profile \
      --instance-profile-name "${NAME}-profile" --role-name "${NAME}-role"
  echo "  linked  : role -> profile"
done

echo
echo "✅ 建立完成。現有的 transcriber-ec2-role / -profile 未被更動，五台實例仍在用它。"
