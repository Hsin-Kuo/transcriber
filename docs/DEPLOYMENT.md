# 部署指南

## 架構概覽

```
GitHub (aws branch)
  └─ GitHub Actions CI/CD
       ├─ Web Server EC2 (t3.small, 3.112.209.96)
       │    ├─ Backend (FastAPI / uvicorn)
       │    ├─ Frontend (/var/www/transcriber)
       │    ├─ Admin Frontend (/var/www/admin)
       │    └─ Nginx (反向代理 + 靜態檔案)
       │
       └─ ※ GPU Worker、MongoDB、Lambda 不在 CI/CD 內
```

---

## 一般功能開發部署

**觸發方式：push 到 `aws` branch**

```bash
git checkout aws
git merge main
git push origin aws
```

GitHub Actions 自動執行以下步驟：

| 項目 | 動作 |
|---|---|
| 後端 Python 程式碼 | 打包 `src/` → SCP 到 EC2 → `systemctl restart transcriber` |
| 前端 | `npm run build` → 上傳到 `/var/www/transcriber` |
| Admin 前端 | `npm run build` → 上傳到 `/var/www/admin` |
| Nginx config | 複製 `deploy/nginx-ec2.conf` → `nginx -t && systemctl reload nginx` |

進度可在 GitHub Actions 頁面查看，最後會自動 curl `https://soundlite.app/health` 驗證。

---

## Web Server EC2（手動操作）

**連線：**
```bash
ssh -i ~/.ssh/transcriber-key.pem ec2-user@3.112.209.96
```

**常用指令：**
```bash
# 查看後端狀態
sudo systemctl status transcriber

# 重啟後端
sudo systemctl restart transcriber

# 即時 log
sudo journalctl -u transcriber -f

# 查看 Nginx 狀態
sudo systemctl status nginx

# 手動更新 Nginx config（通常 CI/CD 會做，手動時用）
sudo cp /opt/transcriber/deploy/nginx-ec2.conf /etc/nginx/conf.d/transcriber.conf
sudo nginx -t && sudo systemctl reload nginx
```

---

## GPU Worker EC2（手動操作）

GPU Worker（g4dn.xlarge）平常是**關機狀態**，收到 SQS 任務時由 Lambda 自動啟動，空閒 5 分鐘後自動關機。

> **正常更新 Worker 程式碼不需要 SSH。** Worker 服務啟動時會自動 `git fetch + reset --hard origin/aws` 並執行 `pip install`，所以 push 到 `aws` branch 後下次任務觸發起機就會跑新版。只有改 systemd unit / 系統層東西時才需要手動進去。

**兩台 GPU 實例（Spot 優先 + On-Demand fallback）：**

| Instance ID | 類型 | 用途 |
|---|---|---|
| `i-0d133cca8e6ce23c2` | g4dn.xlarge Spot | 預設啟動（Lambda 環境變數 `GPU_INSTANCE_ID`） |
| `i-058f381c59210c00a` | g4dn.xlarge On-Demand | Spot 容量不足時的 fallback（Lambda 環境變數 `ONDEMAND_INSTANCE_ID`） |

**手動 SSH（系統層改動時才需要）：**

1. 啟動實例
```bash
# Spot
aws ec2 start-instances --instance-ids i-0d133cca8e6ce23c2 --region ap-northeast-1

# 或 On-Demand
aws ec2 start-instances --instance-ids i-058f381c59210c00a --region ap-northeast-1
```

2. 等機器起來後 SSH 進去（需查當下 IP，每次重啟會變）
```bash
# 查目前 IP（替換成想連的 instance id）
aws ec2 describe-instances \
  --instance-ids i-0d133cca8e6ce23c2 \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --region ap-northeast-1

ssh -i ~/.ssh/transcriber-key.pem ec2-user@<GPU_WORKER_IP>
```

3. 常用指令
```bash
# 手動拉最新程式碼（通常自動，這裡是除錯用）
cd /opt/transcriber && sudo -u ec2-user git fetch && sudo -u ec2-user git reset --hard origin/aws

# 重啟 worker service
sudo systemctl restart transcriber-worker

# 即時 log
sudo journalctl -u transcriber-worker -f
```

**初次部署 GPU Worker（全新機器）：**
```bash
scp -i ~/.ssh/transcriber-key.pem deploy/deploy-gpu-worker.sh ec2-user@<GPU_IP>:~/
ssh -i ~/.ssh/transcriber-key.pem ec2-user@<GPU_IP> "bash ~/deploy-gpu-worker.sh"
```

---

## MongoDB Atlas

托管服務，程式碼不需要部署。

| 情況 | 操作方式 |
|---|---|
| Schema / Index 調整 | [Atlas Console](https://cloud.mongodb.com) 操作 |
| 連線字串變更 | 更新 SSM Parameter Store（見下方） |
| 規格升降 | Atlas Console → Cluster → Edit |

---

## SSM Parameter Store（密鑰管理）

所有敏感密鑰存放於 AWS SSM，後端啟動時自動載入，不存在 `.env`。

**查看現有參數：**
```bash
aws ssm get-parameters-by-path \
  --path "/transcriber/" \
  --with-decryption \
  --region ap-northeast-1
```

**更新密鑰：**
```bash
aws ssm put-parameter \
  --name "/transcriber/<參數名>" \
  --value "<新值>" \
  --type SecureString \
  --overwrite \
  --region ap-northeast-1
```

| 參數名 | 說明 |
|---|---|
| `/transcriber/jwt-secret` | JWT 簽名密鑰（最少 32 字元）|
| `/transcriber/worker-secret` | SQS 訊息 HMAC 簽名密鑰 |
| `/transcriber/mongodb-url` | MongoDB Atlas 連線字串 |
| `/transcriber/resend-api-key` | Resend Email API Key |

**更新密鑰後需重啟後端：**
```bash
ssh -i ~/.ssh/transcriber-key.pem ec2-user@3.112.209.96 \
  "sudo systemctl restart transcriber"
```

---

## Lambda（GPU 自動啟動器）

Lambda `transcriber-gpu-starter` 監聽 SQS，收到任務時自動啟動 GPU Worker EC2。

邏輯簡單，幾乎不需要改動。若有修改：
- **AWS Console** → Lambda → `transcriber-gpu-starter` → 直接編輯
- 或用 CLI：
```bash
aws lambda update-function-code \
  --function-name transcriber-gpu-starter \
  --zip-file fileb://function.zip \
  --region ap-northeast-1
```

---

## 各服務更新速查表

| 服務 | 更新方式 | 需要重啟？ |
|---|---|---|
| 後端程式碼 | push 到 `aws` branch | 自動（CI/CD） |
| 前端 / Admin | push 到 `aws` branch | 不需要（靜態檔案） |
| Nginx config | push 到 `aws` branch | 自動 reload |
| GPU Worker 程式碼 | push 到 `aws` branch（下次起機自動 pull） | 自動（service 啟動時 git reset --hard） |
| MongoDB schema | Atlas Console | 不需要 |
| SSM 密鑰 | AWS CLI / Console | 需要重啟後端 |
| Lambda | AWS Console / CLI | 不需要 |
