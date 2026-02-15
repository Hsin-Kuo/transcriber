#!/bin/bash
# Web Server 部署腳本
# 在 EC2 實例上執行

set -e

echo "=== 安裝系統依賴 ==="
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git

echo "=== 建立應用目錄 ==="
sudo mkdir -p /opt/transcriber
sudo chown ec2-user:ec2-user /opt/transcriber
cd /opt/transcriber

echo "=== 克隆或更新代碼 ==="
if [ -d ".git" ]; then
    git pull
else
    # 替換為你的實際 Git 倉庫 URL
    echo "請手動上傳代碼或設定 Git 倉庫"
fi

echo "=== 安裝 Python 依賴 ==="
python3.11 -m pip install --user -r requirements-web.txt

echo "=== 建立環境變數檔案 ==="
cat > /opt/transcriber/.env << 'EOF'
# AWS 部署配置
DEPLOY_ENV=aws
APP_ROLE=server

# AWS 資源
S3_BUCKET=transcriber-files-696637902131
S3_REGION=ap-northeast-1
SQS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks

# Email 設定（使用 SES）
EMAIL_PROVIDER=ses
FROM_EMAIL=hsinforwork@gmail.com

# 以下密鑰從 SSM Parameter Store 自動載入
# JWT_SECRET_KEY - 從 /transcriber/jwt-secret 載入
# WORKER_SECRET - 從 /transcriber/worker-secret 載入
# MONGODB_URL - 從 /transcriber/mongodb-url 載入

# CORS 設定（替換為你的實際域名）
CORS_ORIGINS=http://localhost:3000,http://your-domain.com
EOF

echo "=== 建立 systemd 服務 ==="
sudo tee /etc/systemd/system/transcriber.service > /dev/null << 'EOF'
[Unit]
Description=Transcriber Web Server
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/transcriber
Environment="PATH=/home/ec2-user/.local/bin:/usr/local/bin:/usr/bin"
ExecStart=/home/ec2-user/.local/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "=== 啟動服務 ==="
sudo systemctl daemon-reload
sudo systemctl enable transcriber
sudo systemctl start transcriber

echo "=== 部署完成 ==="
echo "Web Server 運行在: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8000"
