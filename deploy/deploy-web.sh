#!/bin/bash
# Web Server 部署腳本
# 在 EC2 實例上執行

set -e

echo "=== 安裝系統依賴 ==="
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip git nginx

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

echo "=== 建立環境變數檔案（從 deploy/.env.aws 同步） ==="
# 改成從 repo 內 canonical 檔案 cp 過來；後續 GitHub Actions 每次 deploy
# 也會用同一份檔案重新 sync，避免 EC2 .env 與 repo drift。
cp /opt/transcriber/deploy/.env.aws /opt/transcriber/.env

echo "=== 安裝 systemd 服務 ==="
# 從 repo 內 canonical 檔案 cp 過來，避免 EC2 上的 unit 跟 repo drift。
# 後續每次 deploy（deploy-aws.yml）也會 sync 這份檔案 + systemctl daemon-reload。
sudo cp /opt/transcriber/deploy/transcriber.service /etc/systemd/system/transcriber.service

echo "=== 啟動後端服務 ==="
sudo systemctl daemon-reload
sudo systemctl enable transcriber
sudo systemctl start transcriber

echo "=== 建立前端目錄 ==="
sudo mkdir -p /var/www/transcriber
sudo mkdir -p /var/www/admin
sudo chown -R nginx:nginx /var/www/transcriber /var/www/admin

echo "=== 設定 Nginx ==="
sudo cp /opt/transcriber/deploy/nginx-ec2.conf /etc/nginx/conf.d/transcriber.conf
sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t && sudo systemctl enable nginx && sudo systemctl restart nginx

echo "=== 部署完成 ==="
echo "Web Server API:  http://localhost:8000"
echo "Landing:         https://soundlite.app"
echo "App (前端):       https://my.soundlite.app"
echo "管理後台:        https://admin.soundlite.app"
echo ""
echo "前端靜態檔案請透過 GitHub Actions CI/CD 部署"
