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

### 開發流程（三層分支：feature → main → staging → aws）

`main` / `staging` / `aws` 都有 branch protection（[詳細規則](#branch-protection)）。**不准直接 push**。
升級鏈靠 **Promotion Guard** workflow 強制來源分支：只有 `main` 能 PR 進 `staging`、只有 `staging` 能 PR 進 `aws`。`main` **不部署**（純整合層）。

```bash
# 1. feature → main（整合，不部署）
git checkout main && git pull
git checkout -b feature/xxx
# 開發 + commit
git push -u origin feature/xxx
gh pr create --base main                    # CI 跑 5 個 status check
gh pr merge --squash --delete-branch

# 2. main → staging（部署 + 驗證 staging）
gh pr create --base staging --head main     # Promotion Guard 檢查 head=main
gh pr merge --merge                          # ⚠️ 用 merge commit（非 squash）→ 觸發 deploy-staging.yml
# 在 https://staging.soundlite.app 驗證；要測轉錄先起 GPU worker（見「Staging 環境」）

# 3. staging → aws（部署 prod）
gh pr create --base aws --head staging       # Promotion Guard 檢查 head=staging
gh pr merge --merge                          # → 觸發 deploy-aws.yml
```

> **環境分支（staging / aws）一律用 merge commit 合併，不要 squash**——squash 會讓環境分支與 main 分歧，之後每次 promotion PR 都重列一堆 commit。

### GitHub Actions 自動執行的步驟

| 項目 | 動作 |
|---|---|
| 後端 Python 程式碼 | 打包 `src/` + `deploy/` → SCP 到 EC2 → 解壓 + `pip install -r requirements-web.txt` |
| 前端 | `npm run build` → 上傳到 `/var/www/transcriber` |
| Admin 前端 | `npm run build` → 上傳到 `/var/www/admin` |
| Nginx config | `cp deploy/nginx-ec2.conf` → `nginx -t && systemctl reload nginx` |
| **systemd unit** | `cp deploy/transcriber.service` → `systemd-analyze verify` → `systemctl daemon-reload` |
| Backend restart | `systemctl restart transcriber` → 等 3s → `systemctl is-active --quiet` 驗證沒 crash loop |
| `.env` | 從 `deploy/.env.aws` sync（帶 timestamp backup） |

進度可在 GitHub Actions 頁面查看，最後會自動 curl `https://soundlite.app/health` 驗證。

### systemd unit 變更規則 ⚠️

**禁止 SSH 直接編輯 `/etc/systemd/system/transcriber.service`**。
- ✅ 改 `deploy/transcriber.service`（含 `ExecStartPre`、`--workers 2` 等） → PR → push aws → deploy 自動 sync + daemon-reload + restart
- ❌ 直接 SSH 改 EC2 上的 unit → 下次 deploy 會被覆蓋掉，且改動沒在 git，造成 drift
- 在本機沒辦法跑 `systemd-analyze verify`（macOS 沒 systemd），靠 CI deploy 階段驗證 + `is-active --quiet` 兜底

### Branch protection（三層）

- `main`: PR + 5 個 status check（Ruff / Pytest / Nginx conf / Frontend lint × 2），來源不限
- `staging`: 上述 5 個 + **Promotion Guard**（限來源=`main`）；push staging → `deploy-staging.yml`
- `aws`: 上述 5 個 + **Promotion Guard**（限來源=`staging`）；push aws → `deploy-aws.yml`
- 三者皆禁 force push / 禁刪除
- **Promotion Guard**（`.github/workflows/promotion-guard.yml`）：GitHub 原生無法限制 PR 來源分支，故用此 required check 強制三層升級鏈
- Admin（你）可 bypass，但 bypass 會留在 GitHub 個人 security log

---

## Staging 環境

與 prod **物理隔離**的 pre-prod 環境（完整規劃見 [`STAGING_PLAN.md`](./STAGING_PLAN.md)）。

| 項目 | 值 |
|------|-----|
| 網址 | `https://staging.soundlite.app`（Cloudflare Access 鎖 email allowlist；`/subscriptions/notify/*`、`/webhooks/*`、`/health` 為 bypass） |
| Web EC2 | `i-0e328071b52856681`（t3.micro），EIP `52.196.120.189` |
| GPU Worker | `i-015808e5cedccd77f`（g4dn.xlarge On-Demand，**手動啟動**，idle 3 分鐘自停） |
| 資源 | SQS `transcriber-tasks-staging`、S3 `transcriber-files-staging-...`、Atlas **M0**（獨立 project）、SSM `/transcriber-staging/*` |
| Admin 帳號 | `admin@example.com` / `Admin@123456`（在 Cloudflare Access 後，刻意用弱密碼） |

**部署**：PR `main → staging` merge → `deploy-staging.yml` 自動部署 web（只部使用者前端，不含 admin）。

**測轉錄**（worker 平常停著）：
```bash
aws ec2 start-instances --region ap-northeast-1 --instance-ids i-015808e5cedccd77f
# ~3-5 分鐘 ready → 自動 git reset origin/staging + 載模型 + poll staging SQS
# 測完 idle 3 分鐘自動關機（要手動關：aws ec2 stop-instances ...）
```

**佈建新 worker**（可重現，prod/staging 共用）：
```bash
bash deploy/deploy-gpu-worker.sh staging   # 自動裝 ffmpeg / git deploy key / clone / 預裝 deps / unit
```

> 環境路由靠 `APP_ENV=staging` → `config_loader.get_parameter` 把 `/transcriber/*` 改讀 `/transcriber-staging/*`（與 prod secret 完全隔離）。
> ⚠️ DLAMI / EC2 base 都**不含 ffmpeg**（intake 量時長、worker 解碼都需要）→ 已收進 `deploy-web.sh` / `deploy-gpu-worker.sh`。ML 依賴（torch / pyannote / huggingface_hub）已在 `requirements.txt` 釘版本，避免新機抓 bleeding-edge 爆掉。

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
