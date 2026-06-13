# Staging 環境建置計畫（B1）

> 建立日期：2026-05-17
> 最後更新：2026-06-13（現況對齊校對）
> 對應 LAUNCH_READINESS_PLAN：B1
> 目的：建立可在上線前驗證所有改動的 staging 環境，避免直接 push prod

---

## ⚠️ 現況對齊（2026-06-13 校對）

> 本計畫主體寫於 2026-05-22。已逐檔對齊現況：**Phase 2 的 dispatch 架構描述仍準確**
> （`worker_dispatch._dispatch` / `sqs_consumer._verify_message_signature` /
> `worker_core/db.get_db()` / `worker_core/config` 與計畫描述一致）。
> 但 2026-05-22 之後有幾項變動會卡到 staging，**執行前務必先處理以下 delta**。

### 仍然正確（不用改）
- Phase 2 環境路由設計（SQS payload 加 `env`、worker 依此切 DB/S3/secret）
- Phase 1 AWS 資源 CLI（SQS / S3 / SSM / IAM / EC2 指令仍可用）
- Rollback 策略（`WORKER_DUAL_ENV=false` kill switch）
- HMAC per-env secret 隔離原則

### Delta 1 — `uvicorn --workers 2` 在 t3.micro 會 OOM 🔴（必處理）
- 現況：`deploy/transcriber.service:23` **寫死** `--workers 2`（2026-05-30 multi-worker 後）。
- 問題：staging 用 t3.micro（1 vCPU / 1 GiB），跑 2 個 uvicorn worker + 應用依賴會記憶體不足／thrash。
- **修正（擇一）**：
  - **(推薦) 參數化 worker 數**：unit 改 `Environment=WEB_CONCURRENCY=2` +
    `ExecStart=... --workers ${WEB_CONCURRENCY}`；staging 的 `.env` 設 `WEB_CONCURRENCY=1`。
    `EnvironmentFile` 載入順序在 `Environment=` 之後，可覆寫。prod 行為不變（預設 2）。
  - 或 staging 直接用 **t3.small**（+$4/月，與 prod 一致，省掉參數化）。

### Delta 2 — `.env.aws` 是單一 canonical 檔 🔴（必處理）
- 現況：`deploy/.env.aws` **已 commit 進 repo**（不含密鑰——密鑰全走 SSM `/transcriber/*`，
  檔內只有 `DEPLOY_ENV` / `APP_ROLE` / `S3_BUCKET` / `SQS_QUEUE_URL` / `CORS_ORIGINS` / `FRONTEND_URL` 等非敏感值）。
  `deploy/deploy-web.sh:30` 寫死 `cp deploy/.env.aws → .env`；`deploy-aws.yml` 每次 deploy 也 sync 同一份。
- 問題：staging 不能共用 prod 的 `.env.aws`（bucket / SQS / CORS / FRONTEND_URL 全不同）。
- **修正**：照同模式**新增（並 commit）`deploy/.env.aws.staging`**——只放非敏感 staging 值
  （`APP_ENV=staging` + `WEB_CONCURRENCY=1` + staging bucket/SQS/CORS/FRONTEND_URL），
  密鑰仍由 SSM `/transcriber-staging/*` 載入（靠 Delta 5 的 `get_ssm_prefix()` 路由）。
  `deploy-staging.yml` 改 `cp deploy/.env.aws.staging`。**不要把任何密鑰寫進此檔**（維持與 `.env.aws` 相同慣例）。

### Delta 3 — `env` 欄位改加在 model 層，worker_dispatch 不用動 🟡（簡化）
- 計畫 2-C 說「在 `_dispatch()` 加 `"env": APP_ENV`」。現況 `worker_dispatch._dispatch` 用
  `self._sign(job.model_dump())`，所以**只要在 `TranscriptionJob`（`src/models/worker_job.py`）加
  `env: str = "prod"` 欄位**，`model_dump()` 自動帶上、HMAC 自然涵蓋，`worker_dispatch.py` 零改動。
- model 已是 `extra="ignore"`（forward-compat），舊 worker 收到也安全忽略。
- web server 端 `env` 值來源：用 `config_loader.APP_ENV`（Delta 5 一起加）→ 建 `TranscriptionJob` 時填入。

### Delta 4 — health check hostname 是 `my.soundlite.app` 不是 `soundlite.app` 🟡
- 現況：`deploy-aws.yml:216` 實際打 `https://my.soundlite.app/health`（prod app 在 `my.` 子網域，
  `soundlite.app` 是 landing、`admin.soundlite.app` 是後台）。
- **修正**：Phase 3 的 `deploy-staging.yml` health check 與 nginx `server_name` 用統一的 staging
  hostname（建議 `staging.soundlite.app` 單一入口，不分 landing/app/admin）。

### Delta 5 — `APP_ENV` 常數尚未存在 🟡
- 現況：`config_loader.py` 只有 `DEPLOY_ENV`，**還沒有 `APP_ENV` / `get_ssm_prefix()`**（計畫 2-C 是規劃，未實作）。
- 確認計畫 2-C / 2-B 的程式改動全部仍是 **TODO**（尚未動工），照原計畫實作即可。

### Delta 6 — 新增 collection 會自動建立（只需驗證）🟢
- 2026-05-22 後新增 `chunk_uploads` / `reservations` / `rate_limits` / `worker_heartbeats` 等 collection，
  各 repo 啟動時 `create_indexes`（獨立 try/except）。**fresh staging DB 首次開機自動建好**，無需手動。
- Phase 4 多驗一項：確認 `users` 的 `email_unique_partial` index 正確建立（避開 Atlas 舊 `email_1` drift）。

### Delta 7 — 配額/金流 #86 背景任務 🟢
- 月度 refill + 訂閱到期 sweep 會在 staging web server 跑、打 staging DB，無害。
- `QUOTA_TIERS` 為程式內權威來源（`/subscriptions/tiers` 下發），staging 行為與 prod 一致。
- 藍新：staging 設 `NEWEBPAY_ENV=sandbox` + 自己的 sandbox 金鑰（金流測試仍延後，見「未決項目」）。

### 對齊後的執行順序（取代下方「上線順序」的前置）
1. **先做 Delta 1 + 3 + 5 的程式改動**（worker 數參數化、`APP_ENV`/`get_ssm_prefix`、`TranscriptionJob.env`、Phase 2 worker dual-queue），本地測過再上。
2. 再走 Phase 1 AWS 資源建置（含 `deploy/.env.aws.staging`，Delta 2）。
3. dual-queue 改動 push `aws` → prod GPU worker auto-pull，設 `WORKER_DUAL_ENV=true`。
4. Phase 3 `deploy-staging.yml`（hostname 用 Delta 4 的值）→ 部署 staging → Phase 4 驗證。

---

## 已決策項目

| 項目 | 決策 | 理由 |
|------|------|------|
| GPU worker | **共用 prod GPU**（一台 worker 同時 poll staging + prod SQS） | 省 ~$8/月，blast radius 接受 |
| MongoDB tier | Staging **M2**，後續 prod 也升 M2 | 取得 PITR 備份；staging 順便當升級演練 |
| CI/CD 分流 | `main → staging`（自動）+ `aws → prod`（GitHub Environment 手動 approve） | 最少改動現有流程 |
| Web server | **新開 t3.micro** | 乾淨隔離，+$4/月可接受 |
| 藍新測試金鑰 | **未申請** | 付款測試延後，其他先建好 |
| SSM 路徑 | `/transcriber-staging/*`（獨立 prefix） | 與 prod `/transcriber/*` 完全隔離，不會互相覆蓋 |
| CORS | staging server 只允許 `https://staging.soundlite.app` | 防止跨環境 cookie 混用 |

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

## 整體依賴順序

```
Phase 1 (AWS 資源)          Phase 2 (程式改動)         Phase 3 (CI/CD)
─────────────────          ─────────────────         ─────────────

┌─────────────┐
│ 1. SQS      │──┐
└─────────────┘  │
┌─────────────┐  │  ┌────────────────────┐
│ 2. S3       │──┼─→│ 5. IAM 擴權        │──┐
└─────────────┘  │  └────────────────────┘  │
┌─────────────┐  │                          │  ┌──────────────────────┐
│ 3. Atlas M2 │──┘                          ├─→│ 7. deploy-web.sh     │
└─────────────┘                             │  │    (staging EC2 初始) │
┌─────────────┐  ┌────────────────────┐     │  └──────────┬───────────┘
│ 4. SSM 參數 │─→│ 6. EC2 t3.micro    │─────┘             │
└─────────────┘  └────────────────────┘                    ▼
                                            ┌──────────────────────────┐
                 ┌────────────────────┐     │ 8. DNS staging.soundlite │
                 │ Worker dual-queue  │     └──────────────────────────┘
                 │ 程式改動 (Phase 2) │
                 └────────┬───────────┘            ┌──────────────────┐
                          │                        │ deploy-staging.yml│
                          ▼                        │ (Phase 3)        │
                 ┌────────────────────┐            └──────────────────┘
                 │ 部署到 prod GPU    │
                 │ (aws branch push)  │
                 └────────────────────┘
                          │
                          ▼
                 ┌────────────────────┐
                 │ Phase 4 驗證       │
                 └────────────────────┘
```

**可並行的區塊**：
- 步驟 1/2/3 彼此獨立，可同時建立
- Phase 2 程式改動可與 Phase 1 的 EC2/DNS 並行開發（在 local 測試）
- Phase 3 CI workflow 可與 Phase 2 同時開發

**必須先後的**：
- SSM 參數 → EC2 啟動（EC2 啟動時 config_loader 就會嘗試讀 SSM）
- IAM 擴權 → EC2/Worker 才能存取 staging 資源
- Worker dual-queue 部署到 prod GPU → Phase 4 才能測「staging 上傳 → prod GPU 處理」

---

## Phase 1 — AWS 資源建置

### 1-A. 命名規則

- Region：`ap-northeast-1`（同 prod）
- SQS：`transcriber-tasks-staging`
- S3：`transcriber-files-staging-696637902131`
- Atlas cluster：`transcriber-staging`（新 project 或同 project 不同 cluster）
- SSM 路徑：`/transcriber-staging/*`
- IAM Role：複用 `transcriber-ec2-role`（擴權 staging 資源 ARN）

### 1-B. CLI 指令清單

#### 1. SQS Queue

```bash
aws sqs create-queue --queue-name transcriber-tasks-staging \
  --attributes VisibilityTimeout=600,MessageRetentionPeriod=345600
```

**Why**: VisibilityTimeout=600 同 prod（單任務最多 10 分鐘）；Retention 4 天夠 debug。

驗證：`aws sqs get-queue-url --queue-name transcriber-tasks-staging`

#### 2. S3 Bucket

```bash
aws s3api create-bucket --bucket transcriber-files-staging-696637902131 \
  --region ap-northeast-1 \
  --create-bucket-configuration LocationConstraint=ap-northeast-1

aws s3api put-bucket-encryption --bucket transcriber-files-staging-696637902131 \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-public-access-block --bucket transcriber-files-staging-696637902131 \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
```

**Why**: 加密 + 全面封鎖公開存取，同 prod 設定。

驗證：`aws s3api head-bucket --bucket transcriber-files-staging-696637902131`

#### 3. Atlas M2

用 Atlas Console 或 atlas CLI 建立：
- Cluster name: `transcriber-staging`
- Tier: M2, Region: AP Northeast (Tokyo)
- 建好後取連線字串、設 IP allowlist（staging EC2 IP + 你本機 + prod GPU worker IP）

**Why**: M2 有 PITR 備份，staging 先上 M2 當 prod 升級演練。

驗證：用連線字串 `mongosh` 測試連線

#### 4. SSM 參數

```bash
aws ssm put-parameter --name /transcriber-staging/mongodb-url \
  --type SecureString --value "<atlas-staging-uri>"

aws ssm put-parameter --name /transcriber-staging/jwt-secret \
  --type SecureString --value "$(openssl rand -hex 32)"

aws ssm put-parameter --name /transcriber-staging/worker-secret \
  --type SecureString --value "$(openssl rand -hex 32)"

aws ssm put-parameter --name /transcriber-staging/google-client-id \
  --type String --value "<同 prod 或新建 OAuth client>"

aws ssm put-parameter --name /transcriber-staging/google-api-key-1 \
  --type SecureString --value "<staging Gemini key>"

aws ssm put-parameter --name /transcriber-staging/resend-api-key \
  --type SecureString --value "<同 prod 的 Resend key>"
```

**Why**: 每個 secret 獨立，staging/prod WORKER_SECRET 不同才能防跨環境訊息互通。

驗證：`aws ssm get-parameter --name /transcriber-staging/jwt-secret --with-decryption --query 'Parameter.Value' --output text | wc -c`（應 ≥64 字元）

#### 5. IAM Role 擴權

編輯 `transcriber-ec2-role` 的 inline policy，加入 staging 資源 ARN：

```json
{
  "Effect": "Allow",
  "Action": ["sqs:*"],
  "Resource": "arn:aws:sqs:ap-northeast-1:696637902131:transcriber-tasks-staging"
},
{
  "Effect": "Allow",
  "Action": ["s3:*"],
  "Resource": [
    "arn:aws:s3:::transcriber-files-staging-696637902131",
    "arn:aws:s3:::transcriber-files-staging-696637902131/*"
  ]
},
{
  "Effect": "Allow",
  "Action": ["ssm:GetParameter"],
  "Resource": "arn:aws:ssm:ap-northeast-1:696637902131:parameter/transcriber-staging/*"
}
```

**Why**: 共用 IAM role 最少改動；prod GPU worker 需同時存取兩邊資源。

驗證：SSH 進 prod GPU worker → `aws sqs get-queue-url --queue-name transcriber-tasks-staging`

#### 6. Staging EC2

```bash
aws ec2 run-instances \
  --image-id ami-06daba374fafd57e3 \
  --instance-type t3.micro \
  --key-name transcriber-key \
  --security-group-ids sg-0cbcd8f856d859962 \
  --iam-instance-profile Name=transcriber-ec2-profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=transcriber-web-staging},{Key=Env,Value=staging}]' \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]'
```

之後分配 Elastic IP：

```bash
aws ec2 allocate-address --domain vpc
aws ec2 associate-address --instance-id <staging-instance-id> --allocation-id <eipalloc>
```

驗證：`ssh -i ~/.ssh/transcriber-key.pem ec2-user@<staging-eip> whoami`

#### 7. Staging EC2 初始佈建

SSH 進 staging EC2 後跑 `deploy/deploy-web.sh`（需先將 `.env` 改為 staging 值）：

```bash
# .env 關鍵差異（對比 prod）
DEPLOY_ENV=aws
APP_ROLE=server
APP_ENV=staging
S3_BUCKET=transcriber-files-staging-696637902131
SQS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks-staging
CORS_ORIGINS=https://staging.soundlite.app
FRONTEND_URL=https://staging.soundlite.app
```

#### 8. Cloudflare DNS

Cloudflare Dashboard → DNS → Add record：
- Type: A
- Name: `staging`
- Content: `<staging EIP>`
- Proxy: ON（橘色雲）

驗證：`curl -I https://staging.soundlite.app/health`（等 DNS 傳播，通常 <1min）

### 1-C. 完成後記錄

| 資源 | 值 |
|------|-----|
| Staging EC2 instance id | （待填） |
| Staging EIP | （待填） |
| Atlas staging URI | SSM `/transcriber-staging/mongodb-url` |
| Staging SQS URL | `https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks-staging` |

---

## Phase 2 — 程式改動

### 架構決策

**核心問題**：一台 GPU worker 如何同時服務兩個環境？

**選擇方案**：SQS payload 加 `env` 欄位 → worker 依此切換 DB/S3/secret。

**Why 不是兩台 worker**：GPU $16/月 vs $8/月，staging 用量極低（一天幾次測試），不值得獨立一台。

**Why 不是 Web Server 區分就好**：staging 有獨立 EC2 web server，但 GPU worker 共用 → worker 必須知道當前任務屬於哪個環境。

### 2-A. 環境路由設計

SQS payload 加 `env` 欄位：

```python
# Web Server 送出的 SQS 訊息
{
  "env": "staging",        # ← 新增
  "task_id": "...",
  "handoff_ext": "mp3",
  "language": "zh",
  ...
  "_signature": "..."      # HMAC 包含 env 欄位
}
```

### 2-B. 檔案改動清單

| 檔案 | 改動 | 影響範圍 |
|------|------|---------|
| `src/utils/config_loader.py` | 新增 `APP_ENV` 常數；`get_parameter()` 加 `env_prefix` 參數選 SSM path | 低：加參數、預設行為不變 |
| `src/worker_core/config.py` | 載入雙環境設定（staging SQS/DB/S3/secret） | 中：新增 env-keyed config dict |
| `src/worker_core/db.py` | `get_db(env="prod")` → LRU cache 兩個 MongoClient | 中：函數簽名變更 |
| `src/worker_core/sqs_consumer.py` | 交替 poll 兩個 queue；poll 間隔從 20s → 10s×2 | 高：主迴圈改動 |
| `src/worker_core/transcription_job.py` | `process_task()` 依 `body["env"]` 取對應 db | 低：一行 dispatch |
| `src/services/worker_dispatch.py` | payload 加 `"env": APP_ENV` | 低：一行加欄位 |
| `src/models/worker_job.py` | `TranscriptionJob` 加 `env: str = "prod"` 欄位 | 低：Pydantic field |
| `deploy/nginx-staging.conf` | 新檔：staging.soundlite.app server block | staging 專用，不影響 prod |

### 2-C. 各模組改動描述

#### `config_loader.py` — APP_ENV 路由

```python
APP_ENV = os.getenv("APP_ENV", "prod")  # "prod" | "staging"

def get_ssm_prefix() -> str:
    """根據 APP_ENV 回傳 SSM 路徑前綴"""
    return "/transcriber-staging" if APP_ENV == "staging" else "/transcriber"
```

Web Server 端只需設 `APP_ENV=staging`，`get_parameter("/transcriber/jwt-secret")` 會自動路由到 `/transcriber-staging/jwt-secret`。

**對 prod 影響**：零。`APP_ENV` 預設 `"prod"`，行為不變。

#### `worker_core/config.py` — 雙環境 config

```python
# 新增：依 env key 取對應環境的值
ENV_CONFIG = {
    "prod": {
        "sqs_queue_url": os.getenv("SQS_QUEUE_URL", ""),
        "mongodb_url": get_parameter("/transcriber/mongodb-url", ...),
        "s3_bucket": os.getenv("S3_BUCKET", ""),
        "worker_secret": get_parameter("/transcriber/worker-secret", ...),
    },
    "staging": {
        "sqs_queue_url": os.getenv("SQS_QUEUE_URL_STAGING", ""),
        "mongodb_url": get_parameter("/transcriber-staging/mongodb-url", ...),
        "s3_bucket": os.getenv("S3_BUCKET_STAGING", ""),
        "worker_secret": get_parameter("/transcriber-staging/worker-secret", ...),
    },
}

WORKER_DUAL_ENV = os.getenv("WORKER_DUAL_ENV", "false").lower() == "true"
```

只有 `WORKER_DUAL_ENV=true` 時才啟用 staging queue poll。

#### `worker_core/db.py` — 雙 client

```python
def get_db(env: str = "prod") -> Database:
    """依環境取 MongoClient（cache；一個 env 一個連線池）"""
```

原本是 `get_db()` 無參數（回傳全域單例）。改為依 `env` key 分開 cache。

#### `worker_core/sqs_consumer.py` — 交替 poll

主迴圈改為輪流 poll 兩個 queue（prod → staging → prod → ...），每次 `WaitTimeSeconds=10`（原 20）：

```python
queues = [("prod", PROD_SQS_URL)]
if WORKER_DUAL_ENV and STAGING_SQS_URL:
    queues.append(("staging", STAGING_SQS_URL))

for env, queue_url in cycle(queues):
    resp = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=10, ...)
    for msg in resp.get("Messages", []):
        body = json.loads(msg["Body"])
        body["_env"] = env  # 標記來源環境
        # 驗 HMAC 時用對應環境的 secret
        if not _verify_message_signature(body, secret=ENV_CONFIG[env]["worker_secret"]):
            ...
        process_task(body, progress_store=get_progress_store(env))
```

**延遲影響**：staging 任務最多多等 10 秒（原來 prod 獨享 20s long-poll，現在兩個各 10s 輪流）。可接受——staging 不需要 prod 級別的回應速度。

#### `worker_core/transcription_job.py` — env dispatch

```python
def process_task(message_body: dict, progress_store: ProgressStore) -> None:
    env = message_body.get("env", "prod")
    db = get_db(env)
    # 其餘不變——orchestrator 本身 env-agnostic
```

#### `worker_dispatch.py` — 加 env 欄位

在 `_dispatch()` 裡 `job.model_dump()` 後加入 `"env": APP_ENV`。HMAC 簽名自然會涵蓋此欄位。

#### `deploy/nginx-staging.conf` — staging Nginx

與 prod `nginx-ec2.conf` 結構相同，差異：
- `server_name staging.soundlite.app`
- CSP 的 S3 connect-src 改為 staging bucket
- 不含 `admin.soundlite.app` server block（staging 先不部 admin）

### 2-D. 環境變數總覽

| 變數 | Staging Web Server | Prod Web Server | Prod GPU Worker |
|------|-------------------|-----------------|-----------------|
| `APP_ENV` | `staging` | `prod` | `prod` |
| `DEPLOY_ENV` | `aws` | `aws` | `aws` |
| `APP_ROLE` | `server` | `server` | `worker` |
| `WORKER_DUAL_ENV` | — | — | `true` |
| `SQS_QUEUE_URL` | staging URL | prod URL | prod URL |
| `SQS_QUEUE_URL_STAGING` | — | — | staging URL |
| `S3_BUCKET` | staging bucket | prod bucket | prod bucket |
| `S3_BUCKET_STAGING` | — | — | staging bucket |

### 2-E. 注意事項

- **WORKER_SECRET 不能共用**：staging / prod 各自獨立 HMAC key，避免跨環境訊息互通
- **DEPLOY_ENV vs APP_ENV**：`DEPLOY_ENV`（local/aws）控制「從哪讀設定」；`APP_ENV`（prod/staging）控制「用哪組資源」
- **Orchestrator 不改**：`TranscriptionOrchestrator` 是 env-agnostic 的——它接收注入的 db instance，不自己決定連哪個 DB
- **HMAC 驗證改動**：`_verify_message_signature` 需接收 env-specific secret 而非全域 `WORKER_SECRET`

---

## Phase 3 — CI/CD 改動

### 3-A. 新增 `deploy-staging.yml`

基於現有 `deploy-aws.yml`，關鍵差異：

| 項目 | prod (`deploy-aws.yml`) | staging (`deploy-staging.yml`) |
|------|------------------------|-------------------------------|
| 觸發分支 | `aws` | `main` |
| EC2_HOST | `3.112.209.96` | `<staging-eip>` |
| Environment | `production`（需 reviewer） | `staging`（無 reviewer） |
| VITE_SENTRY_ENVIRONMENT | `production` | `staging` |
| Health check URL | `https://soundlite.app/health` | `https://staging.soundlite.app/health` |

其餘步驟（打包 backend/frontend、SSH 上傳、解壓部署）結構相同。

### 3-B. 修改 `deploy-aws.yml`

加入 GitHub Environment gate：

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production   # ← 新增：需 reviewer approve
```

### 3-C. GPU Worker 部署

Worker 不需要獨立 CI workflow。Worker auto-pull from `aws` branch（已有機制）：
1. push `aws` 分支（含 dual-queue 改動）
2. Worker 下次啟動時 `git fetch + reset --hard origin/aws` + `pip install`
3. 新增環境變數 `WORKER_DUAL_ENV=true` + `SQS_QUEUE_URL_STAGING` + `S3_BUCKET_STAGING` 到 worker `.env`

### 3-D. GitHub Settings 手動設定

1. Settings → Environments → **New environment** `production`
   - Required reviewers: 你的 GitHub 帳號
   - Wait timer: 0 min
2. Settings → Environments → New `staging`
   - 無 reviewer（main push 自動部署）

---

## Phase 4 — 驗證 Checklist

### 認證
- [ ] 註冊新帳號 → email 驗證 → 登入
- [ ] DevTools → Application → Cookies：確認 `refresh_token` 有 HttpOnly + Secure + SameSite=Strict
- [ ] 等 15 分鐘讓 access token 過期 → 自動 refresh 不踢出
- [ ] Google OAuth 登入流程
- [ ] 登出後 cookie 消失

### 上傳 / 轉錄（共用 prod GPU）
- [ ] 上傳 mp3 → 任務進 staging SQS → prod GPU worker 處理 → 結果寫回 staging MongoDB
- [ ] 驗證 staging 任務不會出現在 prod MongoDB（見「資料隔離驗證」）
- [ ] 故意上傳 `.exe` → 被 audio_validator 擋下
- [ ] SSE 進度推送正常

### 可觀測性
- [ ] `/health` 真實 ping MongoDB
- [ ] `worker_heartbeats` collection 持續寫入
- [ ] Sentry 收到 staging environment 的測試錯誤

### 部署 / 回滾
- [ ] push main → deploy-staging.yml 自動跑
- [ ] 確認 `/opt/transcriber/releases/` 保留歷史 tar.gz
- [ ] 跑 `sudo transcriber-rollback --prev` 驗證 2 分鐘內回到上一版

### 資安
- [ ] auth/upload rate limit 觸發 429
- [ ] 故意設低熵 JWT_SECRET_KEY → 啟動失敗

### 金流（藍新申請完才測）
- [ ] checkout 流程走測試 gateway URL
- [ ] webhook idempotency：replay 同一個 notify → 第二次回 200 但不重複授信

---

## Rollback 策略

| 故障場景 | 回滾方式 | 時間 |
|---------|---------|------|
| Staging web server 壞了 | `sudo transcriber-rollback --prev`（同 prod 機制） | <2 min |
| GPU worker dual-queue 改壞了（staging 任務影響 prod） | SSH 進 worker → 改 `.env` 設 `WORKER_DUAL_ENV=false` → `sudo systemctl restart transcriber-worker` | <3 min |
| Worker HMAC 驗證改壞（prod 訊息也拒） | 同上：`WORKER_DUAL_ENV=false` 回退到單 queue 模式 | <3 min |
| Atlas staging 資料異常 | 不影響 prod（完全隔離的 cluster）；Atlas M2 有 PITR 可回 | — |
| CI deploy-staging 誤觸 prod | 不可能：deploy-aws.yml 只在 `aws` branch 觸發 + environment gate 要 approve | — |

**關鍵原則**：`WORKER_DUAL_ENV=false` 是 kill switch，關掉後 GPU worker 立即回到「只服務 prod」的行為，staging 任務會留在 SQS 等待（不丟失）。

---

## 資料隔離驗證

### 方法

部署完成後，跑一次手動 smoke test：

1. 在 staging 前端上傳一個小 mp3
2. 等任務完成
3. 在 staging MongoDB 確認 task 存在
4. 在 prod MongoDB 確認同一 task_id **不存在**

### 自動化（後續）

可在 `deploy-staging.yml` 最後加一步：

```bash
# staging 部署後自動驗證
python scripts/smoke_test_isolation.py \
  --staging-url https://staging.soundlite.app \
  --prod-db-check  # 用 SSM 取 prod mongodb-url，確認 task 不存在
```

初期手動做即可，確認機制沒問題後再自動化。

---

## 時程估計

| Phase | 預估時間 | 說明 |
|-------|---------|------|
| Phase 1 (AWS 資源) | **1~2 小時** | 主要是 AWS console/CLI + 等 Atlas 建好 |
| Phase 2 (程式改動) | **3~4 小時** | Worker dual-queue 是主要工作量；需寫測試 |
| Phase 3 (CI/CD) | **1 小時** | 複製 + 改 workflow，設 GitHub Environment |
| Phase 4 (驗證) | **1~2 小時** | 手動走 checklist |
| **總計** | **6~9 小時** | 可拆 2~3 天做完 |

**建議執行順序**：
1. Day 1：Phase 1（資源建置）+ Phase 2 開發（local 測試 dual-queue 邏輯）
2. Day 2：Phase 2 部署到 prod GPU + Phase 3 CI + Phase 4 驗證

---

## 上線順序

```
1. 完成 Phase 1：AWS 資源全部建好、staging EC2 跑起 /health 200
2. 完成 Phase 2：程式改好、本地測試 dual-queue 邏輯通過
3. 部署 Phase 2 到 prod GPU worker（aws branch push）
4. 完成 Phase 3：CI workflow 設好
5. 用 deploy-staging.yml 部署 staging
6. Phase 4 驗證 checklist 全過
7. 任何 regression 在 staging 修，重驗
8. 全綠 → 日常使用 staging 作為 pre-prod gate
9. prod 升 Atlas M2（staging 先演練過）
10. 藍新測試帳號申請完成 → 補 webhook 測試
```

---

## 未決項目（後續）

- [ ] 藍新測試環境申請（金流測試 blocker）
- [ ] Cloudflare Access 鎖 staging（避免被搜尋引擎索引）
- [ ] CloudWatch alarm：staging worker_heartbeats 異常告警
- [ ] Atlas 備份 restore 演練（升 M2 後可做）
- [ ] Playwright E2E 4 條黃金路徑（依賴 staging 環境）
