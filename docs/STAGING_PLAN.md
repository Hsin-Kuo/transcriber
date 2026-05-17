# Staging 環境建置計畫（B1）

> 建立日期：2026-05-17
> 對應 LAUNCH_READINESS_PLAN：B1
> 目的：建立可在上線前驗證所有改動的 staging 環境，避免直接 push prod

---

## 已決策項目

| 項目 | 決策 | 理由 |
|------|------|------|
| GPU worker | **共用 prod GPU**（一台 worker 同時 poll staging + prod SQS） | 省 ~$8/月，blast radius 接受 |
| MongoDB tier | Staging **M2**，後續 prod 也升 M2 | 取得 PITR 備份；staging 順便當升級演練 |
| CI/CD 分流 | `main → staging`（自動）+ `aws → prod`（GitHub Environment 手動 approve） | 最少改動現有流程 |
| Web server | **新開 t3.micro** | 乾淨隔離，+$4/月可接受 |
| 藍新測試金鑰 | **未申請** | 付款測試延後，其他先建好 |

---

## 域名與費用

- **域名**：`staging.soundlite.app`（Cloudflare DNS 已控同 zone，加 A record 即可）
- **TLS**：Cloudflare proxied + auto TLS（同 prod）
- **存取限制**：建議加 Cloudflare Access 鎖 IP，避免被搜尋引擎索引

### 月費預估

| 項目 | $/月 |
|------|-----|
| EC2 t3.micro (24/7) | 4 |
| EBS 20GB gp3 | 2 |
| Atlas M2 | 9 |
| S3 + SQS（極小量） | <1 |
| Data transfer | <1 |
| **Staging 小計** | **~$17** |
| Prod 升 M2 增量 | +9 |
| **總計** | **~$26 增量** |

---

## Phase 1 — AWS 資源建置（手動 + 腳本）

### 1-A. 命名規則
- Region：`ap-northeast-1`（同 prod）
- SQS：`transcriber-tasks-staging`
- S3：`transcriber-files-staging-696637902131`
- Atlas cluster：`transcriber-staging`（新 project 或同 project 不同 cluster）
- SSM 路徑：`/transcriber-staging/*`
- IAM Role：複用 `transcriber-ec2-role`（已有 SQS/S3/SSM 權限，需擴 staging 資源 ARN）

### 1-B. CLI 指令清單（執行前再 review）

```bash
# 1. SQS
aws sqs create-queue --queue-name transcriber-tasks-staging \
  --attributes VisibilityTimeout=600,MessageRetentionPeriod=345600

# 2. S3
aws s3api create-bucket --bucket transcriber-files-staging-696637902131 \
  --region ap-northeast-1 \
  --create-bucket-configuration LocationConstraint=ap-northeast-1
aws s3api put-bucket-encryption --bucket transcriber-files-staging-696637902131 \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket transcriber-files-staging-696637902131 \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'

# 3. Atlas M2（用 Atlas Console 建立；或 atlas CLI）
# - cluster name: transcriber-staging
# - tier: M2, region: AP Northeast (Tokyo)
# - 建好後取得連線字串、設 IP allowlist（Web Server EC2 staging IP + 你本機）

# 4. SSM 參數
aws ssm put-parameter --name /transcriber-staging/mongodb-url --type SecureString --value "<atlas-staging-uri>"
aws ssm put-parameter --name /transcriber-staging/jwt-secret --type SecureString --value "$(openssl rand -hex 32)"
aws ssm put-parameter --name /transcriber-staging/worker-secret --type SecureString --value "$(openssl rand -hex 32)"
aws ssm put-parameter --name /transcriber-staging/google-client-id --type String --value "<同 prod 或新建 OAuth client>"
aws ssm put-parameter --name /transcriber-staging/google-api-key-1 --type SecureString --value "<staging Gemini key>"
# 藍新：等申請後補
# aws ssm put-parameter --name /transcriber-staging/newebpay-hash-key --type SecureString --value "<test>"
# aws ssm put-parameter --name /transcriber-staging/newebpay-hash-iv --type SecureString --value "<test>"

# 5. IAM Role 擴權（讓 prod EC2 也能訪問 staging 資源）
# 編輯 transcriber-ec2-role 政策，加入：
# - SQS: arn:aws:sqs:ap-northeast-1:696637902131:transcriber-tasks-staging
# - S3:  arn:aws:s3:::transcriber-files-staging-696637902131/*
# - SSM: arn:aws:ssm:ap-northeast-1:696637902131:parameter/transcriber-staging/*

# 6. Staging EC2 t3.micro
aws ec2 run-instances \
  --image-id ami-06daba374fafd57e3 \
  --instance-type t3.micro \
  --key-name transcriber-key \
  --security-group-ids sg-0cbcd8f856d859962 \
  --iam-instance-profile Name=transcriber-ec2-profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=transcriber-web-staging},{Key=Env,Value=staging}]' \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]'

# 7. 取得 Elastic IP（或用 public IP）
# aws ec2 allocate-address --domain vpc
# aws ec2 associate-address --instance-id <staging-instance-id> --allocation-id <eipalloc>

# 8. Cloudflare DNS：staging.soundlite.app → <staging EIP>（手動於 Cloudflare console）
```

### 1-C. 完成後記錄到 MEMORY.md

| 資源 | 值 |
|------|-----|
| Staging EC2 instance id | （待填） |
| Staging EIP | （待填） |
| Atlas staging URI | SSM `/transcriber-staging/mongodb-url` |
| Staging SQS URL | `https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks-staging` |

---

## Phase 2 — App 程式改動

### 2-A. 環境路由設計

每個 SQS 訊息加 `env` 欄位（`"prod"` 或 `"staging"`），worker 收到後依此挑選正確的 MongoDB / S3。

```python
# SQS payload 範例
{
  "env": "staging",        # ← 新增
  "task_id": "...",
  "audio_s3_key": "uploads/free/abc.mp3",
  ...
  "_signature": "..."
}
```

### 2-B. 檔案改動清單

| 檔案 | 改動 |
|------|------|
| `src/worker_core/config.py` | 載入雙環境 `MONGODB_URL_PROD/STAGING`、`S3_BUCKET_PROD/STAGING`、`SQS_QUEUE_URL_PROD/STAGING` |
| `src/worker_core/sqs_consumer.py` | 同時 poll 兩個 queue（receive_message 輪流，long-poll 縮短至 10s） |
| `src/worker_core/transcription_job.py` | 收到 task 時 `env = payload["env"]`，後續所有 DB/S3 操作依 env 決定 client |
| `src/worker_core/db.py` | `get_db(env)`：cache 兩個 client |
| `src/routers/transcriptions.py` | SQS payload 加 `"env": APP_ENV`（透過環境變數設） |
| `src/utils/config_loader.py` | 支援 `get_parameter(name, env_prefix)`，預設讀目前 env |
| `deploy/nginx-ec2.conf` | 加 `staging.soundlite.app` server block；同 prod 但反代 staging EC2 內部 IP |
| `.env.example` | 加 `APP_ENV=staging` 文件 |

### 2-C. 新增環境變數

| 變數 | 值（prod / staging） |
|------|------------------|
| `APP_ENV` | `prod` / `staging` |
| `WORKER_DUAL_ENV` | `false` / `true`（只有 worker 那台設 true 開雙 poll） |

### 2-D. 注意事項

- **共用 worker 機**：worker 的 IAM role 必須同時涵蓋兩邊 SQS/S3/SSM 資源
- **WORKER_SECRET 不能共用**：staging / prod 各自獨立 HMAC key，避免跨環境訊息互通
- **DEPLOY_ENV vs APP_ENV**：DEPLOY_ENV (local/aws) 維持舊語意；APP_ENV (prod/staging) 是新概念
- **資料隔離測試**：要寫個 smoke test 驗 staging 任務絕不會出現在 prod MongoDB（反之亦然）

---

## Phase 3 — CI/CD 改動

### 3-A. 新增 `.github/workflows/deploy-staging.yml`

```yaml
name: Deploy to Staging
on:
  push:
    branches: [main]
env:
  EC2_HOST: <staging-eip>
  EC2_USER: ec2-user
  APP_ENV: staging
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: staging   # GitHub Environment（無 reviewer）
    steps:
      # ...類似 deploy-aws.yml，差異：
      # - 部署到 staging EC2
      # - env: APP_ENV=staging
      # - 健康檢查打 https://staging.soundlite.app/health
```

### 3-B. 修改 `.github/workflows/deploy-aws.yml`

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production  # ← 加這行；GitHub Environment 設 reviewer
    env:
      APP_ENV: prod
    # ...其餘不變
```

### 3-C. GitHub Settings 手動設定

1. Settings → Environments → **New environment** `production`
   - Required reviewers: 你的 GitHub 帳號
   - Wait timer: 0 min
2. Settings → Environments → New `staging`
   - 無 reviewer
3. Settings → Branches → Branch protection rules
   - `aws` 分支：require PR review、require CI pass

---

## Phase 4 — 驗證 checklist

部署到 staging 後依序驗：

### 認證
- [ ] 註冊新帳號 → email 驗證 → 登入
- [ ] DevTools → Application → Cookies：確認 `refresh_token` 有 HttpOnly + Secure + SameSite=Strict
- [ ] 等 15 分鐘讓 access token 過期，操作任何 API → 自動 refresh 不踢出
- [ ] 開新分頁，登入狀態應該保留
- [ ] Google OAuth 登入流程
- [ ] 登出後 cookie 消失

### 上傳 / 轉錄（共用 prod GPU）
- [ ] 上傳 mp3 → 任務進 staging SQS → prod GPU worker 處理 → 結果寫回 staging MongoDB
- [ ] 驗證 staging 任務不會出現在 prod MongoDB
- [ ] 故意上傳 `.exe` → 被 audio_validator 擋下
- [ ] 故意上傳 `.mp3` 但內容是 shell script → 被 magic bytes 擋下
- [ ] SSE 進度推送正常

### 可觀測性
- [ ] `/health` 真實 ping MongoDB
- [ ] `/readiness` 等 model 載入後才回 200
- [ ] `worker_heartbeats` collection 持續寫入
- [ ] Sentry 收到 staging environment 的測試錯誤

### 部署 / 回滾
- [ ] push main → deploy-staging.yml 自動跑
- [ ] 確認 `/opt/transcriber/releases/` 保留歷史 tar.gz
- [ ] 跑 `sudo transcriber-rollback --prev` 驗證 2 分鐘內回到上一版

### 資安
- [ ] CSP Report-Only 一週內收集違規回報
- [ ] 確認沒有真的違規（OAuth / Stripe / Sentry 都該被白名單放行）
- [ ] auth/upload rate limit 觸發 429
- [ ] 故意設低熵 JWT_SECRET_KEY → 啟動失敗

### 金流（藍新申請完才測）
- [ ] checkout 流程走測試 gateway URL
- [ ] webhook idempotency：故意 replay 同一個 notify → 第二次回 200 但不重複授信

---

## 上線順序

```
1. 完成 Phase 1+2+3，staging 跑起來
2. 在 staging 完整跑過 Phase 4 checklist
3. 任何 regression 在 staging 修，回 staging 重驗
4. 全綠 → push aws 分支 → prod 部署（GitHub Environment 需手動 approve）
5. prod 跑穩一週後 → 升 Atlas M2（同樣 staging 先演練）
6. 藍新測試帳號申請完成 → 補 webhook 測試
```

---

## 未決項目（後續）

- [ ] 藍新測試環境申請（金流測試 blocker）
- [ ] Cloudflare Access 鎖 staging（避免被搜尋引擎索引）
- [ ] CloudWatch alarm：staging worker_heartbeats 異常告警（先設給 prod，staging 後補）
- [ ] Atlas 備份 restore 演練（升 M2 後可做）
