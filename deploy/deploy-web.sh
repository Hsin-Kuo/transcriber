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

# Email 設定（使用 Resend）
EMAIL_PROVIDER=resend
FROM_EMAIL=noreply@soundlite.app
FROM_NAME=Soundlite

# 以下密鑰從 SSM Parameter Store 自動載入
# JWT_SECRET_KEY - 從 /transcriber/jwt-secret 載入
# WORKER_SECRET - 從 /transcriber/worker-secret 載入
# MONGODB_URL - 從 /transcriber/mongodb-url 載入
# RESEND_API_KEY - 從 /transcriber/resend-api-key 載入

# CORS 設定（包含主前端和管理後台）
CORS_ORIGINS=https://soundlite.app,https://admin.soundlite.app

# Frontend URL (用於 email 中的連結)
FRONTEND_URL=https://soundlite.app
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

echo "=== 啟動後端服務 ==="
sudo systemctl daemon-reload
sudo systemctl enable transcriber
sudo systemctl start transcriber

echo "=== 安裝 Docker（如尚未安裝）==="
if ! command -v docker &> /dev/null; then
    sudo dnf install -y docker
    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker ec2-user
    echo "⚠️ Docker 已安裝，請重新登入以套用 docker 群組權限"
fi

echo "=== 部署前端容器 ==="
cd /opt/transcriber

# 主前端（port 3000）
docker build -t transcriber-frontend ./frontend
docker rm -f whisper-frontend 2>/dev/null || true
docker run -d \
    --name whisper-frontend \
    --restart unless-stopped \
    -p 3000:3000 \
    -e API_UPSTREAM=172.17.0.1:8000 \
    transcriber-frontend

# 管理後台前端（port 3003）
docker build -t transcriber-admin ./admin-frontend
docker rm -f whisper-admin-frontend 2>/dev/null || true
docker run -d \
    --name whisper-admin-frontend \
    --restart unless-stopped \
    -p 3003:3003 \
    -e API_UPSTREAM=172.17.0.1:8000 \
    transcriber-admin

echo "=== 設定 Nginx 反向代理 ==="
sudo dnf install -y nginx
sudo cp /opt/transcriber/deploy/nginx-ec2.conf /etc/nginx/conf.d/transcriber.conf

# 移除預設設定（避免衝突）
sudo rm -f /etc/nginx/conf.d/default.conf

sudo nginx -t && sudo systemctl enable nginx && sudo systemctl restart nginx

echo "=== 部署完成 ==="
echo "Web Server API:  http://localhost:8000"
echo "前端:            https://soundlite.app (port 3000)"
echo "管理後台:        https://admin.soundlite.app (port 3003)"
