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
python3.11 -m pip install --user -r requirements-worker.txt

echo "=== 建立環境變數檔案 ==="
cat > /opt/transcriber/.env << 'EOF'
# AWS 部署配置
DEPLOY_ENV=aws
APP_ROLE=worker

# AWS 資源
S3_BUCKET=transcriber-files-696637902131
S3_REGION=ap-northeast-1
SQS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks

# 自動關機設定（空閒 5 分鐘後關機）
AUTO_SHUTDOWN_IDLE_MINUTES=5

# 以下密鑰從 SSM Parameter Store 自動載入
EOF

echo "=== 建立 Worker systemd 服務 ==="
sudo tee /etc/systemd/system/transcriber-worker.service > /dev/null << 'EOF'
[Unit]
Description=Transcriber GPU Worker
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/transcriber
Environment="PATH=/home/ec2-user/.local/bin:/usr/local/bin:/usr/bin"
ExecStart=/home/ec2-user/.local/bin/python3.11 src/worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "=== 啟動服務 ==="
sudo systemctl daemon-reload
sudo systemctl enable transcriber-worker
sudo systemctl start transcriber-worker

echo "=== 部署完成 ==="
echo "GPU Worker 已啟動，開始處理 SQS 佇列任務"
echo "空閒 5 分鐘後會自動關機"
