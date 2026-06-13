# Staging 環境建置計畫（B1）

> 建立日期：2026-05-17
> 重寫日期：2026-06-14（依 grill 釐清的 7 個決策全面改寫）
> 對應 LAUNCH_READINESS_PLAN：B1
> 目的：建立可在上線前驗證所有改動的 staging 環境，避免直接 push prod

---

> **⚠️ 本版取代舊設計。** 2026-05-22 的舊版採「共用 prod GPU worker + dual-queue + 把
> `env` 串進 DB/S3/secret 三個模組全域變數」。經程式碼盤點後否決——該設計要在 prod 的轉錄
> 熱路徑上改 `storage_service.S3_BUCKET`（模組全域）等，blast radius 是付費用戶的轉錄。
> 新設計改為 **staging 完全獨立的環境**（獨立 web + 獨立 on-demand GPU worker），prod
> 熱路徑零改動，需要的程式改動也從一大坨縮到三項。

---

## 核心決策（grill 2026-06-14 定案）

| # | 決策 | 理由 / 影響 |
|---|------|------|
| 1 | **獨立 on-demand GPU worker**（不共用 prod、不做 dual-queue） | prod 轉錄熱路徑零改動；各行程自帶 env，不必把 env 串進全域變數 |
| 2 | **手動 / 腳本啟動 worker** + 沿用既有 5 分鐘 idle 自停 | staging 測試是有意識發起的，不需 event-driven 自動啟動；`shutdown_instance()` 用 `stop_instances`（非 terminate），重開即用 |
| 3 | **GPU g4dn.xlarge On-Demand** | 跑跟 prod 完全相同的 batched-GPU 轉錄路徑，pre-prod gate 才有保真度（CPU 會走不同路徑且需改 `model_cache` 的 float16） |
| 4 | **Cloudflare Access**：email allowlist + webhook/health bypass（金流測試在即，現在就加） | 機器回呼（藍新 notify / Resend webhook）自帶驗證，bypass 不降安全；人類流程走 Access 登入 |
| 5 | **取碼 = systemd `ExecStartPre` `git reset --hard origin/<branch>`** | 已實證 prod worker 就是這樣（origin/aws）；順手把 worker unit 收成 repo-as-source，補掉 IaC 破口 |
| 6 | **Atlas staging M2 allowlist = `0.0.0.0/0`** | 鏡像 prod（實證 prod worker 每次開機都是動態 IP、無 EIP 仍能連），靠帳密 + TLS 保護 |
| 7 | **三層分支** `feature → main(不部署) → staging → aws`，**guard workflow 強制來源分支** | 所有改動必經 staging 驗證才進 prod；GitHub 原生無法限制 PR 來源，靠 required status check 強制 |

### 沿用舊版仍有效的決策

| 項目 | 決策 |
|------|------|
| MongoDB tier | Staging **M2**（每日快照備份；⚠️ **PITR 需 M10+ dedicated**，M2/M5 shared tier 沒有 PITR） |
| Staging web server | **新開 t3.micro** |
| SSM 路徑 | `/transcriber-staging/*`（與 prod `/transcriber/*` 完全隔離） |
| 對外入口 | **單一網域 `staging.soundlite.app`**（不拆 landing/app/admin；先不部 admin） |
| CORS | 只允許 `https://staging.soundlite.app` |

---

## ⚠️ 前置條件 / 可行性複查（2026-06-14）

落地前必須先處理，否則會卡住：

| # | 項目 | 狀態 | 處理 |
|---|------|------|------|
| P1 | **On-Demand G 配額 = 4 vCPU（硬天花板）** | 🟡 申請已送出（2026-06-14，待審批） | 實測 On-Demand G 與 Spot G 配額**都只有 4**，g4dn.xlarge 吃滿 4。staging on-demand worker 與 **prod on-demand 備援 worker 無法同時存在**。已透過 Console 送出 On-Demand G 4→8 申請；批准前若 prod failover，暫停 staging 測試 |
| P2 | **`transcriber.service` 無 `EnvironmentFile`** | 🔴 必修 | web env 靠 `main.py` 的 `load_dotenv()` 在執行期讀，systemd 不知道 → 無法用 `${WEB_CONCURRENCY}`。需給 unit 加 `EnvironmentFile=-/opt/transcriber/.env` + `Environment=WEB_CONCURRENCY=2`（見 2-D） |
| P3 | **Atlas M2 無 PITR** | 🟡 前提修正 | M2/M5 shared tier 只有每日快照；PITR 需 M10+。若 staging 只為驗證，每日快照夠用；別把它當 PITR 演練 |
| P4 | 無 `Makefile` | 🟢 註記 | `staging-worker-up` 改成新增一支 shell script |

**已驗證可行**：`get_parameter` 單點 prefix 路由 ✓；`load_dotenv()` 早於 config_loader import ✓；
t3.micro web 可行（`APP_ROLE=server` 不載入模型）✓；worker unit `EnvironmentFile`+`${DEPLOY_BRANCH}` ✓；
Access bypass 路徑自帶驗證 ✓。

---

## 架構總覽

```
                     ┌─────────────────────────────┐
  staging.soundlite  │  Cloudflare（Proxy + TLS）   │
  .app ──────────────▶  + Access（email allowlist） │
                     └──────────────┬──────────────┘
            bypass: /subscriptions/notify/*, /webhooks/*, /health
                                    │
                     ┌──────────────▼──────────────┐
                     │  Staging Web EC2 (t3.micro)  │   APP_ENV=staging
                     │  Nginx + uvicorn --workers 1 │   讀 SSM /transcriber-staging/*
                     └──────────────┬──────────────┘
                                    │  S3 handoff + SQS（staging 專屬資源）
                     ┌──────────────▼──────────────┐
                     │ Staging GPU Worker           │   APP_ENV=staging
                     │ g4dn.xlarge On-Demand        │   DEPLOY_BRANCH=staging
                     │ 手動 start → 5 分鐘 idle 自停 │   ExecStartPre: reset origin/staging
                     └──────────────────────────────┘
                                    │
                     ┌──────────────▼──────────────┐
                     │  Atlas M2 cluster (staging)  │   allowlist 0.0.0.0/0
                     └──────────────────────────────┘

  prod 環境完全平行（/transcriber/*、prod bucket/queue、origin/aws），互不交集。
```

**與 prod 的隔離**：S3 bucket、SQS queue、Atlas cluster、SSM prefix、WORKER_SECRET、
GPU worker 全部獨立。唯一共用的是 AWS account / IAM role（擴權涵蓋 staging ARN）與
Cloudflare zone。

---

## 月費預估（增量）

| 項目 | $/月 | 備註 |
|------|------|------|
| Staging Web EC2 t3.micro (24/7) | ~8 | 依 ap-northeast-1 on-demand 定價 |
| Web EBS 20GB gp3 | ~1.6 | |
| Atlas M2 | 9 | 每日快照（非 PITR；PITR 需 M10+） |
| **GPU Worker EBS（停機也算）** | ~3 | 40GB gp3；models+deps，不需 100GB |
| GPU Worker 計算（僅測試時） | ~2~3 | on-demand g4dn ~$0.526/hr × 每月幾小時，5 分鐘自停 |
| S3 + SQS + transfer | <1 | 極小量 |
| **Staging 小計** | **~$25** | |
| Prod 升 M2（後續，選做） | +9 | |

> **重點**：停機的 GPU worker 仍會收 EBS 儲存費（~$3/月）。把 root volume 開小（40GB）即可壓低；
> 計算費只在你實際測試時產生。

---

## Phase 1 — AWS 資源建置

Region 一律 `ap-northeast-1`（同 prod）。

### 命名規則

| 資源 | 名稱 |
|------|------|
| SQS | `transcriber-tasks-staging` |
| S3 | `transcriber-files-staging-696637902131` |
| Atlas cluster | `transcriber-staging`（M2） |
| SSM prefix | `/transcriber-staging/*` |
| Web EC2 tag | `transcriber-web-staging` |
| GPU Worker EC2 tag | `transcriber-gpu-staging` |
| IAM Role | 複用 `transcriber-ec2-role`（擴權 staging ARN） |

### 1. SQS

```bash
aws sqs create-queue --queue-name transcriber-tasks-staging \
  --attributes VisibilityTimeout=600,MessageRetentionPeriod=345600
```

### 2. S3

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

### 3. Atlas M2

Atlas Console / `atlas` CLI 建立 `transcriber-staging`（M2, Tokyo）。
- **Network allowlist：`0.0.0.0/0`**（鏡像 prod；GPU worker 動態 IP 無法逐一列舉，靠帳密 + TLS）
- 取連線字串備用（下一步寫進 SSM）

### 4. SSM 參數（`/transcriber-staging/*`）— **完整清單**

> ⚠️ 舊版只列 6 個，實際 worker + web + 金流測試需要以下**全部**：

```bash
P=/transcriber-staging

# 必要
aws ssm put-parameter --name $P/mongodb-url   --type SecureString --value "<atlas-staging-uri>"
aws ssm put-parameter --name $P/jwt-secret    --type SecureString --value "$(openssl rand -hex 32)"
aws ssm put-parameter --name $P/worker-secret --type SecureString --value "$(openssl rand -hex 32)"  # 必須與 prod 不同
aws ssm put-parameter --name $P/google-client-id --type String    --value "<同 prod client_id>"
aws ssm put-parameter --name $P/google-api-key-1 --type SecureString --value "<Gemini key>"
aws ssm put-parameter --name $P/google-api-key-2 --type SecureString --value "<Gemini key 2>"
aws ssm put-parameter --name $P/hf-token        --type SecureString --value "<HuggingFace token>"  # diarization 必要
aws ssm put-parameter --name $P/resend-api-key  --type SecureString --value "<同 prod Resend key>"
aws ssm put-parameter --name $P/resend-webhook-secret --type SecureString --value "<Resend webhook secret>"

# 金流測試（Q4：sandbox 值）
aws ssm put-parameter --name $P/newebpay-merchant-id --type SecureString --value "<sandbox MerchantID>"
aws ssm put-parameter --name $P/newebpay-hash-key    --type SecureString --value "<sandbox HashKey>"
aws ssm put-parameter --name $P/newebpay-hash-iv     --type SecureString --value "<sandbox HashIV>"
```

### 5. IAM Role 擴權（`transcriber-ec2-role` inline policy 加 staging ARN）

```json
[
  { "Effect": "Allow", "Action": ["sqs:*"],
    "Resource": "arn:aws:sqs:ap-northeast-1:696637902131:transcriber-tasks-staging" },
  { "Effect": "Allow", "Action": ["s3:*"],
    "Resource": ["arn:aws:s3:::transcriber-files-staging-696637902131",
                 "arn:aws:s3:::transcriber-files-staging-696637902131/*"] },
  { "Effect": "Allow", "Action": ["ssm:GetParameter","ssm:GetParameters"],
    "Resource": "arn:aws:ssm:ap-northeast-1:696637902131:parameter/transcriber-staging/*" }
]
```

### 6. Staging Web EC2（t3.micro）

```bash
aws ec2 run-instances \
  --image-id ami-06daba374fafd57e3 --instance-type t3.micro \
  --key-name transcriber-key --security-group-ids sg-0cbcd8f856d859962 \
  --iam-instance-profile Name=transcriber-ec2-profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=transcriber-web-staging},{Key=Env,Value=staging}]' \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]'

aws ec2 allocate-address --domain vpc
aws ec2 associate-address --instance-id <staging-web-id> --allocation-id <eipalloc>
```

### 7. Staging GPU Worker EC2（g4dn.xlarge On-Demand）

```bash
aws ec2 run-instances \
  --image-id <與 prod worker 同一張 GPU AMI> --instance-type g4dn.xlarge \
  --key-name transcriber-key --security-group-ids sg-0cbcd8f856d859962 \
  --iam-instance-profile Name=transcriber-ec2-profile \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=transcriber-gpu-staging},{Key=Env,Value=staging}]' \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":40,"VolumeType":"gp3"}}]'
```

> 🔴 **GPU 配額（見前置條件 P1）**：On-Demand G 配額**只有 4 vCPU**，g4dn.xlarge 吃滿 4 →
> staging worker 與 **prod on-demand 備援無法同時存在**。這不是機率問題，是硬天花板：prod spot
> 中斷 failover 到 on-demand 備援、而你正在測 staging 時，其中一台起不來。**建議先申請 On-Demand G
> 配額加到 8** 再依賴此 worker；否則明確接受「prod failover 期間暫停 staging 測試」。
> 建好後 `stop-instances` 讓它待命。

### 完成後記錄（2026-06-14 建置中）

| 資源 | 值 | 狀態 |
|------|-----|------|
| Staging SQS URL | `https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks-staging` | ✅ |
| Staging S3 bucket | `transcriber-files-staging-696637902131`（AES256 + PAB） | ✅ |
| IAM policy | `transcriber-ec2-policy` **v4**（加 staging S3/SQS/SSM ARN，最小權限） | ✅ |
| SSM `/transcriber-staging/*` | jwt-secret, worker-secret（fresh）+ google-client-id, google-api-key-1/2, hf-token, resend-api-key（copy from prod） | ✅ 7/10 |
| Staging Web EC2 id / EIP | `i-0e328071b52856681` / **`52.196.120.189`**（t3.micro, AMI `ami-0f0e8dab98a36cdd7`） | ✅ 建立（未 provision） |
| Staging GPU Worker EC2 id | （待 provision 時建；AMI `ami-06daba374fafd57e3`） | ⏳ |
| Atlas M2 + SSM mongodb-url | Console 建立後填 | ⏳ |
| SSM newebpay-* / resend-webhook-secret | sandbox 值 / prod 也未設 | ⏳ |

---

## Phase 2 — 程式改動（僅三項）

> 新設計下 staging 是獨立環境，**不需要** dual-queue / env routing / 改 storage_service。
> 剩下的改動只有：SSM prefix 路由、worker unit repo 化、Sentry env。對 prod 全部零行為改變。

### 2-A. SSM prefix 路由（單點，`config_loader.get_parameter`）

19 處 `/transcriber/*` 全經過同一個 `get_parameter()`，所以只在此處依 `APP_ENV` 改寫前綴：

```python
# src/utils/config_loader.py
def get_parameter(name: str, fallback_env: Optional[str] = None, default: str = "") -> str:
    # 呼叫時讀 APP_ENV（非 module 全域）——徹底避開 import 時序疑慮
    if os.getenv("APP_ENV", "prod") == "staging" and name.startswith("/transcriber/"):
        name = name.replace("/transcriber/", "/transcriber-staging/", 1)
    # ...（cache key 用改寫後的 name；其餘維持現狀）
```

**對 prod 影響**：零。`APP_ENV` 預設 `prod`，不改寫。`fallback_env`（本地 .env）行為不變。
> 在函式內讀 `APP_ENV` 而非 module 全域：雖然實證 `load_dotenv()` 已早於 config_loader import
> （main.py 1-19 行只 import 標準庫+fastapi），呼叫時讀更穩、零時序風險。

### 2-B. Worker systemd unit 收成 repo-as-source（補 IaC 破口）

實證 prod worker 跑的 unit 是**手改在實機、未回寫 repo**（`deploy/deploy-gpu-worker.sh` 已嚴重 drift）。
新增 canonical `deploy/transcriber-worker.service`，用 `EnvironmentFile` + `DEPLOY_BRANCH` 變數讓 prod/staging 共用一份：

```ini
# deploy/transcriber-worker.service（canonical，prod 與 staging 共用）
[Unit]
Description=Transcriber AI Worker (GPU)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/opt/transcriber
EnvironmentFile=/opt/transcriber/.env.worker          # 每台機器自帶（含 DEPLOY_BRANCH/APP_ENV/資源）
Environment="PYTHONUNBUFFERED=1" "PATH=/usr/local/bin:/home/ec2-user/.local/bin:/usr/bin:/bin"
ExecStartPre=/bin/bash -c 'cd /opt/transcriber && git fetch origin ${DEPLOY_BRANCH} && git reset --hard origin/${DEPLOY_BRANCH}'
ExecStartPre=/bin/bash -c 'cd /opt/transcriber && pip install -r requirements.txt -q 2>&1 | tail -1'
ExecStart=/usr/bin/python3.12 -m src.worker
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`/opt/transcriber/.env.worker`（每台機器寫一次，非 repo）：

| 變數 | Prod worker | Staging worker |
|------|-------------|----------------|
| `DEPLOY_ENV` | `aws` | `aws` |
| `APP_ROLE` | `worker` | `worker` |
| `APP_ENV` | `prod` | `staging` |
| `DEPLOY_BRANCH` | `aws` | `staging` |
| `S3_BUCKET` | prod bucket | `transcriber-files-staging-696637902131` |
| `SQS_QUEUE_URL` | prod queue | staging queue |
| `SENTRY_ENVIRONMENT` | `prod-worker` | `staging-worker` |
| `AUTO_SHUTDOWN_IDLE_MINUTES` | `5` | `5` |

> 落地時把 prod 實機現有的手改 unit 也換成這份 canonical（一次性對齊），之後兩環境都可重現。

### 2-C. Sentry environment（防 staging 污染 prod）

`sentry_init.py` 是 `environment = SENTRY_ENVIRONMENT or f"{DEPLOY_ENV}-{component}"`。staging 與 prod
的 `DEPLOY_ENV` 都是 `aws` → 不設就都 tag 成 `aws-server`/`aws-worker` 撞在一起。**只需在 staging
的 env 顯式設**（零程式改動）：

- Staging web `.env`：`SENTRY_ENVIRONMENT=staging-server`
- Staging worker `.env.worker`：`SENTRY_ENVIRONMENT=staging-worker`
- 前端 build：`VITE_SENTRY_ENVIRONMENT=staging`（在 `deploy-staging.yml`）

### 2-D. Web `.env`：新增 `deploy/.env.aws.staging`（committed，非密鑰）

照 `deploy/.env.aws` 同模式（密鑰走 SSM，不入檔）：

```bash
DEPLOY_ENV=aws
APP_ROLE=server
APP_ENV=staging
WEB_CONCURRENCY=1                 # ← t3.micro 只跑 1 個 uvicorn worker（見下方注意）
S3_BUCKET=transcriber-files-staging-696637902131
S3_REGION=ap-northeast-1
SQS_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks-staging
EMAIL_PROVIDER=resend
NEWEBPAY_ENV=sandbox
CORS_ORIGINS=https://staging.soundlite.app
FRONTEND_URL=https://staging.soundlite.app
SENTRY_ENVIRONMENT=staging-server
```

> **t3.micro worker 數（修正 P2）**：`deploy/transcriber.service` 寫死 `--workers 2`，1GiB 機器會 OOM。
> ⚠️ 但該 unit **目前沒有 `EnvironmentFile`**，web env 全靠 `main.py` 的 `load_dotenv()` 在執行期讀，
> systemd 看不到 `.env` 的 `WEB_CONCURRENCY` → 直接用 `${WEB_CONCURRENCY}` 會展成空字串 → crash。
> **正解**（三步）：
> 1. unit 加 `EnvironmentFile=-/opt/transcriber/.env`（`-` = 檔案不存在也不報錯，prod 安全）
> 2. unit 加 `Environment=WEB_CONCURRENCY=2`（預設值；EnvironmentFile 載入順序在後，會覆寫它）
> 3. `ExecStart=... --workers ${WEB_CONCURRENCY}`；staging `.env` 設 `WEB_CONCURRENCY=1`，prod `.env` 不設 → 維持預設 2
>
> 注意：`.env` 須維持 systemd EnvironmentFile 可解析格式（`KEY=value` + `#` 註解，勿用 `export`）。
> `deploy/.env.aws` 現狀符合。

---

## Phase 3 — CI/CD（三層分支 + guard workflow）

### 3-A. 分支模型

```
feature ──PR──▶ main（整合層，不部署）
                 │ PR（guard 限 head=main）
                 ▼
              staging ─push─▶ deploy-staging.yml ─▶ staging 環境
                 │ PR（guard 限 head=staging）
                 ▼
               aws ────push─▶ deploy-aws.yml ─▶ prod 環境（+ Environment 手動 approve）
```

### 3-B. 新增 `deploy-staging.yml`（基於 `deploy-aws.yml`）

| 項目 | prod (`deploy-aws.yml`) | staging (`deploy-staging.yml`) |
|------|------------------------|-------------------------------|
| 觸發分支 | `aws` | `staging` |
| EC2_HOST | `3.112.209.96`（prod web） | `<staging web EIP>` |
| Environment | `production`（需 reviewer） | `staging`（無 reviewer） |
| `VITE_SENTRY_ENVIRONMENT` | `production` | `staging` |
| Health check | `https://my.soundlite.app/health` | `https://staging.soundlite.app/health`（需 Access bypass /health，見 Phase 5） |

> 其餘步驟（打包 backend/frontend、SSH 上傳、解壓、`systemd-analyze verify`、`is-active`）結構相同。
> Staging web 只部使用者前端，不部 admin。

### 3-C. 新增 `promotion-guard.yml`（強制來源分支）

GitHub branch protection **無法**原生限制 PR 來源分支，靠這支 workflow 當 required status check：

```yaml
name: Promotion Guard
on:
  pull_request:
    branches: [staging, aws]
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - name: Enforce source branch
        run: |
          BASE="${{ github.base_ref }}"; HEAD="${{ github.head_ref }}"
          if [ "$BASE" = "staging" ] && [ "$HEAD" != "main" ]; then
            echo "::error::只有 main 能 PR 進 staging（目前來源：$HEAD）"; exit 1; fi
          if [ "$BASE" = "aws" ] && [ "$HEAD" != "staging" ]; then
            echo "::error::只有 staging 能 PR 進 aws（目前來源：$HEAD）"; exit 1; fi
          echo "OK: $HEAD → $BASE"
```

### 3-D. Branch protection / Environments（GitHub Settings 手動）

| 分支 | 設定 |
|------|------|
| `main` | require PR + `test.yml` 綠；來源不限（feature 任意命名）；禁直接 push |
| `staging` | require PR + **Promotion Guard** + `test.yml` 綠；禁直接 push |
| `aws` | require PR + **Promotion Guard** + `test.yml` 綠；Environment `production` reviewer approve；禁直接 push |

- Settings → Environments → `production`：Required reviewers = 你；`staging`：無 reviewer
- 把 `Promotion Guard` 設成 `staging` / `aws` 的 **required status check**

### 3-E. Worker 取碼

無獨立 CI。staging worker 開機 `ExecStartPre` 自動 `git reset --hard origin/staging`（見 2-B），
所以每次手動 start 都跑最新 `staging`。prod worker 同理走 `origin/aws`。

---

## Phase 4 — 驗證 Checklist

> 跑前先手動啟動 staging worker：`aws ec2 start-instances --instance-ids <staging-gpu-id>`
> （建議新增一支 shell script，如 `scripts/staging-worker-up.sh`；repo 目前無 Makefile）。測完它會 5 分鐘 idle 自停。

### 環境隔離（最關鍵）
- [ ] staging 上傳一個小 mp3 → 任務進 **staging** SQS → **staging** worker 處理 → 結果寫回 **staging** Atlas
- [ ] 確認同一 task_id **不存在於 prod** Atlas（完全隔離）
- [ ] 確認 staging 任務的 handoff/音檔在 **staging** bucket（不在 prod bucket）

### 認證
- [ ] 註冊 → email 驗證 → 登入；Google OAuth（需先在 OAuth client 加 `staging.soundlite.app` JS origin）
- [ ] refresh_token cookie：HttpOnly + Secure + SameSite=Strict；access token 過期自動 refresh
- [ ] 首位 admin：對 staging DB 跑 `python -m src.database.migrations.seed_admin`（APP_ENV=staging 自動連 staging）

### 上傳 / 轉錄
- [ ] 上傳走 chunked、worker 走 GPU batched（與 prod 同路徑）；SSE 進度正常
- [ ] 故意上傳 `.exe` → 被 audio_validator 擋下

### 可觀測性
- [ ] `/health` ping DB；`worker_heartbeats` 持續寫入（staging DB）
- [ ] Sentry 收到 `staging-server` / `staging-worker` environment 的測試錯誤（**不**混進 prod）
- [ ] 確認新 collection 自動建立，尤其 `users` 的 `email_unique_partial` index

### 部署 / 回滾
- [ ] PR main→staging 合併 → `deploy-staging.yml` 自動跑；錯誤來源（如 feature→staging）被 Promotion Guard 擋下
- [ ] `/opt/transcriber/releases/` 保留歷史；`sudo transcriber-rollback --prev` 2 分鐘回上一版

### 資安
- [ ] auth/upload rate limit 觸發 429；低熵 JWT_SECRET 啟動 fail-fast
- [ ] Cloudflare Access：未授權 email 無法進主站；`/subscriptions/notify/*`、`/webhooks/*`、`/health` 可被機器直達

### 金流（sandbox）
- [ ] checkout 走 sandbox gateway；藍新 notify 經 Access bypass 打進 `/subscriptions/notify/period`
- [ ] webhook idempotency：replay 同一 notify → 第二次 200 但不重複授信

---

## Phase 5 — Cloudflare 設定

### DNS
- A record：`staging` → `<staging web EIP>`，Proxy ON（橘雲），TLS = Cloudflare auto

### Access（三個 application，最具體路徑優先）

| 順序 | 路徑 | 政策 |
|------|------|------|
| 1 | `staging.soundlite.app/subscriptions/notify/*` | **Bypass**（everyone）— 藍新 notify |
| 2 | `staging.soundlite.app/webhooks/*` | **Bypass**（everyone）— Resend bounce |
| 3 | `staging.soundlite.app/health` | **Bypass**（everyone）— CI / 監控健康檢查 |
| 4 | `staging.soundlite.app/*` | **Allow**（你的 email allowlist）|

> Bypass 路徑安全性：藍新 notify 自帶 AES 加密 + `decrypt_period_notify` 驗證 + `processed_webhooks`
> idempotency；Resend webhook 驗 svix 簽章；`/health` 無敏感資料。故 bypass 不降低安全。
> 付款 return URL 走人類流程，瀏覽器已帶 Access cookie → 正常通過，不需 bypass。

---

## Rollback 策略

| 故障場景 | 回滾方式 | 時間 |
|---------|---------|------|
| Staging web 壞了 | `sudo transcriber-rollback --prev` | <2 min |
| Staging worker 改壞 | 完全不影響 prod（獨立實例 + 獨立 queue/bucket/secret）；改 `.env.worker` 或回退 `staging` 分支即可 | — |
| Staging Atlas 資料異常 | 不影響 prod（獨立 cluster）；M2 每日快照可回（非 PITR） | — |
| 錯誤分支誤入 prod | 不可能：Promotion Guard 擋非 `staging→aws`；`aws` 還要 Environment approve | — |

> 新設計下 staging 與 prod **物理隔離**，沒有舊版「dual-queue 改壞會波及 prod」的風險，
> 因此不再需要 `WORKER_DUAL_ENV` kill switch。

---

## 時程估計

| Phase | 預估 | 說明 |
|-------|------|------|
| Phase 1 AWS 資源 | 1.5~2.5 hr | SQS/S3/SSM/IAM/兩台 EC2 + 等 Atlas |
| Phase 2 程式改動 | 1~2 hr | 三項都小（prefix 路由 / unit repo 化 / Sentry env） |
| Phase 3 CI/CD | 1.5 hr | deploy-staging + promotion-guard + branch protection + Environments |
| Phase 4 驗證 | 1~2 hr | 走 checklist |
| **總計** | **5~8 hr** | 比舊版（含 dual-queue 開發）省，因 Phase 2 大幅縮小 |

---

## 上線順序

1. Phase 2 程式改動（prefix 路由 / worker unit / Sentry env / `.env.aws.staging`）→ 本地測 + PR 進 main
2. Phase 1 AWS 資源全部建好（含 staging worker `.env.worker`、Atlas allowlist、SSM 全清單）
3. Phase 3 CI/CD：`promotion-guard.yml`、`deploy-staging.yml`、branch protection、Environments
4. 開 `staging` 分支（從 main），PR main→staging → 觸發首次 staging 部署
5. Phase 5 Cloudflare DNS + Access
6. 手動 start staging worker → Phase 4 驗證 checklist 全過
7. 金流 sandbox 測通（含 webhook bypass）
8. 全綠 → 日常以 `staging` 作 pre-prod gate；prod release = PR staging→aws（+ approve）
9. （選做）prod 升 Atlas M2，staging 已演練過

---

## 未決項目（後續）

- [ ] prod hotfix 後門：目前 hotfix 也須走 feature→main→staging→aws 全程；如需緊急繞道再設計
- [ ] CloudWatch alarm：staging worker_heartbeats 異常告警
- [ ] Atlas 每日快照 restore 演練（M2；PITR 須 M10+ 才有）
- [ ] **（P1）申請 On-Demand G 配額 4→8 vCPU**，讓 staging worker 與 prod 備援可並存
- [ ] Playwright E2E 4 條黃金路徑（依賴 staging 環境）
- [ ] `make staging-worker-up` / `down` 包裝腳本
