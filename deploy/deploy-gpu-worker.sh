#!/bin/bash
# GPU Worker 部署腳本
# 在 GPU EC2 實例上執行

set -e

echo "=== 安裝系統依賴 ==="
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git

echo "=== 建立應用目錄 ==="
sudo mkdir -p /opt/transcriber
sudo chown ec2-user:ec2-user /opt/transcriber
cd /opt/transcriber

echo "=== 安裝 Python 依賴（包含 ML 套件）==="
pip install -r requirements.txt -q

echo "=== 建立 Worker 環境變數檔案 (.env.worker) ==="
# 環境差異放這裡（密鑰仍走 SSM /transcriber{,-staging}/*，靠 APP_ENV 路由）。
# ⚠️ prod 用下列值；staging worker 請改 DEPLOY_BRANCH=staging / APP_ENV=staging
#    / S3_BUCKET=transcriber-files-staging-... / SQS=...-staging / SENTRY_ENVIRONMENT=staging-worker
cat > /opt/transcriber/.env.worker << 'EOF'
DEPLOY_ENV=aws
APP_ROLE=worker
APP_ENV=prod
DEPLOY_BRANCH=aws
S3_BUCKET=transcriber-files-696637902131
S3_REGION=ap-northeast-1
SQS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks
SENTRY_ENVIRONMENT=prod-worker
AUTO_SHUTDOWN_IDLE_MINUTES=5
# 密鑰從 SSM Parameter Store 自動載入（APP_ENV 決定 /transcriber 或 /transcriber-staging）
EOF

echo "=== 安裝 Worker systemd 服務（從 repo canonical 檔，避免 drift）==="
# 從 repo cp，禁止直接 SSH 改 EC2 上的 unit。開機 ExecStartPre 會依 .env.worker 的
# DEPLOY_BRANCH 自我更新程式碼。
sudo cp /opt/transcriber/deploy/transcriber-worker.service /etc/systemd/system/transcriber-worker.service

echo "=== 啟動服務 ==="
sudo systemctl daemon-reload
sudo systemctl enable transcriber-worker
sudo systemctl start transcriber-worker

echo "=== 部署完成 ==="
echo "GPU Worker 已啟動，開始處理 SQS 佇列任務"
echo "空閒 5 分鐘後會自動關機"
