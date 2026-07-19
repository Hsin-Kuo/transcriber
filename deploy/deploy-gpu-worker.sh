#!/bin/bash
# GPU Worker 佈建腳本（在 GPU EC2 實例上執行）
#
# 前提：實例用 AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Amazon Linux 2023)
#       → 已含 NVIDIA driver / CUDA / python3.12 / git，但「不含」ffmpeg 與本專案程式。
#
# 用法：
#   bash deploy-gpu-worker.sh prod       # prod worker（預設）
#   bash deploy-gpu-worker.sh staging    # staging worker
#
# 本腳本把過去散落的手動步驟收斂成可重現流程：deploy key → ffmpeg → clone →
# .env.worker → 預裝 deps（避開 systemd 90s ExecStartPre timeout）→ canonical unit。
set -euo pipefail

APP_ENV="${1:-prod}"
case "$APP_ENV" in
  prod)
    DEPLOY_BRANCH=aws
    S3_BUCKET=transcriber-files-696637902131
    SQS_NAME=transcriber-tasks
    SENTRY_ENVIRONMENT=prod-worker
    IDLE_MIN=5
    ;;
  staging)
    DEPLOY_BRANCH=staging
    S3_BUCKET=transcriber-files-staging-696637902131
    SQS_NAME=transcriber-tasks-staging
    SENTRY_ENVIRONMENT=staging-worker
    IDLE_MIN=3
    ;;
  *)
    echo "用法: $0 [prod|staging]"; exit 1 ;;
esac
S3_REGION=ap-northeast-1
SQS_QUEUE_URL="https://sqs.${S3_REGION}.amazonaws.com/696637902131/${SQS_NAME}"
# 優先佇列（pro+enterprise）；命名慣例 = 一般佇列名 + -priority
PRIORITY_SQS_QUEUE_URL="https://sqs.${S3_REGION}.amazonaws.com/696637902131/${SQS_NAME}-priority"
REPO=git@github.com:Hsin-Kuo/transcriber.git

echo "=== 佈建 ${APP_ENV} GPU worker（branch=${DEPLOY_BRANCH}）==="

# DLAMI 已含 git，保險確保
command -v git >/dev/null || sudo dnf install -y git

# --- 1. ffmpeg（DLAMI 無、AL2023 dnf 也沒有 → 裝 static binary）---
if ! command -v ffmpeg >/dev/null; then
  echo "=== 安裝 ffmpeg static binary ==="
  cd /tmp
  curl -fsSL -o ffmpeg.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
  tar xf ffmpeg.tar.xz
  D=$(ls -d ffmpeg-*-static | head -1)
  sudo cp "$D/ffmpeg" "$D/ffprobe" /usr/local/bin/
  rm -rf ffmpeg.tar.xz "$D"
fi
echo "ffmpeg: $(command -v ffmpeg)"

# --- 2. git deploy key（worker 開機 ExecStartPre 要 git fetch/reset origin/<branch>）---
KEY=~/.ssh/repo_deploy
if [ ! -f "$KEY" ]; then
  ssh-keygen -t ed25519 -N "" -f "$KEY" -C "$(hostname)-deploy"
fi
if ! grep -q "Host github.com" ~/.ssh/config 2>/dev/null; then
  cat >> ~/.ssh/config <<EOF
Host github.com
  IdentityFile ~/.ssh/repo_deploy
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
  chmod 600 ~/.ssh/config
fi
if ! git ls-remote "$REPO" >/dev/null 2>&1; then
  echo ""
  echo "⚠️  尚無法存取 repo。請把下面這把 public key 加為 GitHub repo 的【唯讀 Deploy Key】："
  echo "    https://github.com/Hsin-Kuo/transcriber/settings/keys/new  （勾選 read-only）"
  echo "    ---"
  cat "$KEY.pub"
  echo "    ---"
  echo "加好後重跑本腳本即可繼續。"
  exit 1
fi

# --- 3. clone / 更新程式碼到指定分支 ---
sudo mkdir -p /opt/transcriber && sudo chown ec2-user:ec2-user /opt/transcriber
if [ ! -d /opt/transcriber/.git ]; then
  git clone "$REPO" /opt/transcriber
fi
cd /opt/transcriber
git fetch origin "$DEPLOY_BRANCH"
git checkout "$DEPLOY_BRANCH" 2>/dev/null || git checkout -b "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
git reset --hard "origin/$DEPLOY_BRANCH"
echo "code: $(git rev-parse --short HEAD) @ ${DEPLOY_BRANCH}"

# --- 4. .env.worker（環境差異；密鑰走 SSM /transcriber{,-staging}/*，靠 APP_ENV 路由）---
# WHISPER_MODEL=large-v3 + RESEG_MAX_SEGMENT_SEC=4：2026-06-17 staging 實測 medium/turbo/large-v3
# × batched/sequential 矩陣後定案的 production 標準（v3+batched 不掉段、幻覺較少），
# staging/prod 一致，不再各自漂移。
cat > /opt/transcriber/.env.worker <<EOF
DEPLOY_ENV=aws
APP_ROLE=worker
APP_ENV=${APP_ENV}
DEPLOY_BRANCH=${DEPLOY_BRANCH}
S3_BUCKET=${S3_BUCKET}
S3_REGION=${S3_REGION}
SQS_QUEUE_URL=${SQS_QUEUE_URL}
PRIORITY_SQS_QUEUE_URL=${PRIORITY_SQS_QUEUE_URL}
SENTRY_ENVIRONMENT=${SENTRY_ENVIRONMENT}
AUTO_SHUTDOWN_IDLE_MINUTES=${IDLE_MIN}
WHISPER_MODEL=large-v3
RESEG_MAX_SEGMENT_SEC=4
DIAR_DEBUG_DUMP=${DIAR_DEBUG_DUMP:-}
EOF
# DIAR_DEBUG_DUMP：語者對齊除錯 dump（預設空=關）。開啟方式：
#   DIAR_DEBUG_DUMP=1 bash deploy-gpu-worker.sh staging
# 或手改 .env.worker 後 systemctl restart transcriber-worker（下次佈建會被覆蓋回預設）。

# --- 4b. 台語模型 Breeze-ASR-26（CT2 轉檔版，S3 → 本地，idempotent）---
# 模型檔 ~2.9GB，放各環境自己的 bucket（models/ prefix），沿用 instance role 唯讀。
# S3 物件缺失時只警告不中斷佈建，且**不寫 env**——routing 程式碼對未設
# WHISPER_MODEL_NAN_TW 的台語任務會安全退回 WHISPER_MODEL（docs/TAIWANESE_ASR_PLAN.md）。
# 千萬別無條件寫 env：env 指向不存在的路徑會讓台語任務在載入模型時直接失敗。
BREEZE_DIR=/opt/models/breeze-asr-26-ct2
if [ ! -f "$BREEZE_DIR/model.bin" ]; then
  echo "=== 下載台語模型 Breeze-ASR-26（s3://${S3_BUCKET}/models/breeze-asr-26-ct2/）==="
  sudo mkdir -p /opt/models && sudo chown ec2-user:ec2-user /opt/models
  aws s3 sync "s3://${S3_BUCKET}/models/breeze-asr-26-ct2/" "$BREEZE_DIR" \
    --region "${S3_REGION}" --only-show-errors || true
fi
if [ -f "$BREEZE_DIR/model.bin" ]; then
  echo "WHISPER_MODEL_NAN_TW=${BREEZE_DIR}" >> /opt/transcriber/.env.worker
  echo "台語模型就緒：${BREEZE_DIR}"
else
  echo "⚠️  台語模型不存在（S3 尚未上傳？）——不寫 WHISPER_MODEL_NAN_TW，台語任務退回 WHISPER_MODEL"
fi

# --- 5. 預裝 deps（暖快取）---
# 用 requirements-worker.lock（完整 closure 鎖定）確保重建 deterministic，不受未釘
# transitive 漂移。unit 的 ExecStartPre 也會 pip install，但受 systemd TimeoutStartSec=90s
# 限制；冷裝 torch 會 timeout，故首次佈建先在這裡裝好，之後 ExecStartPre 秒過。
echo "=== 預裝 Python 依賴（從 lock，含 ML 套件，首次較久）==="
python3.12 -m pip install -r requirements-worker.lock -q

# --- 6. systemd unit（從 repo canonical 檔，禁止直接 SSH 改 EC2 上的 unit）---
sudo cp /opt/transcriber/deploy/transcriber-worker.service /etc/systemd/system/transcriber-worker.service
sudo systemctl daemon-reload
sudo systemctl enable transcriber-worker
# restart 而非 start：服務已在跑時 start 是 no-op，.env.worker/unit 的變更不會生效
# （2026-07-19 staging 驗證 DIAR_DEBUG_DUMP 時踩到：檔案更新了、跑的還是舊 env 進程）
sudo systemctl restart transcriber-worker

echo "=== 佈建完成（${APP_ENV}）==="
echo "GPU Worker 已啟動，poll ${SQS_NAME}；閒置 ${IDLE_MIN} 分鐘後自動關機。"
