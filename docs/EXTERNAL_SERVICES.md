# 外部服務清單（External Services）

> 本專案依賴的所有第三方 / 雲端服務統整。新增或汰換服務時，請同步更新本文件、`.env.example`、`deploy/.env.aws`。
>
> 最後更新：2026-06-13

---

## 總覽

| 類別 | 服務 | 用途 | 必要性 |
|------|------|------|--------|
| 資料庫 | **MongoDB Atlas** | 主資料庫（全部 collections） | 必要 |
| 雲端基礎設施 | **AWS**（S3 / SQS / Lambda / EC2 / SSM） | 檔案儲存、任務佇列、GPU 自動啟停、密鑰管理 | 生產必要 |
| DNS / CDN | **Cloudflare** | DNS、反向代理、Web Analytics | 生產必要 |
| AI — 標點 | **Google Gemini** | AI 標點強化（預設 provider） | 必要 |
| AI — 標點（備選） | **OpenAI** | AI 標點強化（`gpt-4o-mini`，替代 provider） | 選用 |
| AI — 語者辨識 | **HuggingFace**（pyannote） | speaker diarization 模型下載 / gated access | 啟用辨識時必要 |
| Email | **Resend** | 交易信（驗證 / 密碼重設）+ bounce/complaint webhook | 生產必要 |
| Email（備選） | **SMTP / Gmail** | 本地或備援寄信 | 選用 |
| 登入 | **Google OAuth** | 第三方社群登入 | 選用 |
| 金流 | **藍新金流 Newebpay** | 定期定額訂閱付款 + webhook | 生產必要 |
| 監控 | **Sentry** | 前端 / 後台 / 後端錯誤追蹤 | 選用（建議） |

> 轉錄核心 **faster-whisper（large-v3-turbo）** 為自架模型（在本機進程或 GPU Worker 執行），**非外部 API**，故不列於上表。

---

## 詳細說明

### 1. MongoDB Atlas — 主資料庫
- **用途**：全部 persistent / transient state（`users` / `tasks` / `transcriptions` / `segments` / `orders` … 見 CLAUDE.md collections 清單）。
- **環境變數**：`MONGODB_URL`、`MONGODB_DB_NAME`
- **生產 cluster**：`transcriber-cluster.h79qwpc.mongodb.net`（ap-northeast-1）
- **連線字串**：生產走 `mongodb+srv://`；本地需 `?replicaSet=rs0&directConnection=true`（transaction 需 replica set）。
- **密鑰來源**：SSM `/transcriber/mongodb-url`

### 2. AWS — 雲端基礎設施
帳號 `696637902131`，region `ap-northeast-1`。

| 服務 | 資源 | 用途 |
|------|------|------|
| **S3** | `transcriber-files-696637902131` | 音檔儲存（`StorageService` local/S3 自動切換、presigned URL） |
| **SQS** | `transcriber-tasks` | Web Server → GPU Worker 任務派發（HMAC-SHA256 簽名） |
| **Lambda** | `transcriber-gpu-starter` | SQS 觸發自動啟動 GPU Worker（Spot 優先，fallback On-Demand） |
| **EC2** | Web Server t3.small / GPU Worker g4dn.xlarge | 應用主機 / GPU 推論 |
| **SSM Parameter Store** | `/transcriber/*` | 所有密鑰統一管理（fail-fast 載入） |
| **Service Quotas** | — | GPU vCPU 配額申請 |

- **環境變數**：`S3_BUCKET`、`S3_REGION`、`SQS_QUEUE_URL`、`WORKER_SECRET`、`APP_ROLE`、`DEPLOY_ENV=aws`
- **安全建議**：S3 不開公開讀，一律走 presigned URL 並驗證域名；SQS 訊息必須 HMAC 簽名驗證；IAM Role 採最小權限（`transcriber-ec2-role` / `transcriber-lambda-role`）。詳見 CLAUDE.md 安全規範。

### 3. Cloudflare — DNS / Proxy / Analytics
- **用途**：`soundlite.app` 域名 DNS、反向代理（TLS 終結）、**Web Analytics**（`static.cloudflareinsights.com`，已列入 Nginx CSP allowlist）。
- **域名拆分**：
  - `soundlite.app` — landing
  - `my.soundlite.app` — 使用者 app（`FRONTEND_URL`）
  - `admin.soundlite.app` — 管理後台
- **本地測試 webhook**：用 `cloudflared tunnel` 把 localhost 暴露給藍新 / Resend callback（見金流測試記錄）。
- **設定位置**：`deploy/nginx-ec2.conf`（CSP `connect-src https://cloudflareinsights.com`）。

### 4. Google Gemini — AI 標點強化（預設）
- **用途**：轉錄後標點符號強化（`punctuation_processor.py`，預設 provider）。
- **環境變數**：`GOOGLE_API_KEY_1` / `_2` / `_3`（多把 key 輪替分流）
- **輸入驗證**：`punct_provider` 走白名單（`gemini` / `openai`）。

### 5. OpenAI — AI 標點強化（備選 provider）
- **用途**：標點強化的替代 provider，模型 `gpt-4o-mini`（`punctuation_processor._punctuate_with_openai`）。
- **環境變數**：`OPENAI_API_KEY`
- **備註**：預設走 Gemini，OpenAI 為選用備援。

### 6. HuggingFace — 語者辨識模型（pyannote）
- **用途**：下載 / 存取 gated 的 **pyannote** speaker diarization 模型（`diarization_processor.py`）。
- **環境變數**：`HF_TOKEN`
- **備註**：未設定則語者辨識不可用；轉錄本身不受影響。

### 7. Resend — 交易型 Email（生產）
- **用途**：email 驗證、密碼重設等交易信；接收 **bounce / complaint** webhook（`/webhooks/resend`，`email_webhooks.py`）。
- **環境變數**：`EMAIL_PROVIDER=resend`、`FROM_EMAIL`（須為 Resend 已驗證 sender domain）
- **密鑰來源**：SSM `/transcriber/resend-api-key`、`/transcriber/resend-webhook-secret`
- **Webhook 設定**：Resend dashboard → Webhooks → `https://soundlite.app/webhooks/resend`（取得 `whsec_...`）。
- **備註**：生產使用 Resend，**不使用 AWS SES**。`EmailService` 程式碼仍保留 `ses` 為合法選項但生產未採用。

### 8. SMTP / Gmail — Email（備選）
- **用途**：`EMAIL_PROVIDER=smtp` 時走 SMTP（預設 `smtp.gmail.com:587`）；本地預設則為 `console`（印到終端）。
- **環境變數**：`SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `FROM_EMAIL`
- **安全建議**：Gmail 須用 App Password，勿用主密碼。

### 9. Google OAuth — 第三方登入
- **用途**：Google 社群登入（`routers/oauth.py`）。
- **環境變數**：`GOOGLE_CLIENT_ID`
- **密鑰來源**：SSM `/transcriber/google-client-id`
- **設定**：Authorized origins 須含 `https://my.soundlite.app` 等正式域名。

### 10. 藍新金流 Newebpay — 訂閱付款
- **用途**：定期定額訂閱付款 + payment webhook（`routers/subscriptions.py`、`newebpay_service.py` AES 加解密）。
- **環境變數**：`NEWEBPAY_MERCHANT_ID` / `NEWEBPAY_HASH_KEY` / `NEWEBPAY_HASH_IV` / `NEWEBPAY_ENV`（`sandbox`/`production`）、`NEWEBPAY_PRICE_*`
- **idempotency**：webhook 重發保護 `processed_webhooks` collection。
- **CSP**：`form-action` / `frame-src` 已允許 `*.newebpay.com`、`core.newebpay.com`。
- **上線 checklist（缺一不可）**：`NEWEBPAY_ENV` 只切 gateway URL、金鑰另外注入，兩者錯配只會在加解密/驗簽階段才爆。正式上線需**同時**：(1) 把 SSM `/transcriber/newebpay-*` 三把金鑰換成正式商店值；(2) 在 `deploy/.env.aws` 顯式設 `NEWEBPAY_ENV=production`（未設預設 sandbox）。`NewebpayService` 已內建 fail-fast：production 下若 MerchantID 仍是已知 sandbox 值會啟動即報錯。
- **參考**：`docs/NEWEBPAY_PERIOD_API.md`

### 11. Sentry — 錯誤監控
- **用途**：前端（`frontend/src/main.js`）、管理後台（`admin-frontend/src/main.js`）皆整合 `@sentry/vue ^10`；後端透過 `SENTRY_DSN` 整合。
- **環境變數**：`SENTRY_DSN`、`SENTRY_ENVIRONMENT`、`SENTRY_TRACES_SAMPLE_RATE`、`SENTRY_PROFILES_SAMPLE_RATE`、`SENTRY_RELEASE`
- **CSP**：已允許 `https://*.sentry.io`、`https://*.ingest.sentry.io`。

---

## 密鑰管理（SSM Parameter Store）

生產環境**不在 `.env` 放任何 secret**，一律由 SSM `/transcriber/*` 載入（`config_loader.py`，本地 fallback `.env`）：

| SSM Parameter | 對應環境變數 |
|---------------|--------------|
| `/transcriber/jwt-secret` | `JWT_SECRET_KEY` |
| `/transcriber/worker-secret` | `WORKER_SECRET` |
| `/transcriber/mongodb-url` | `MONGODB_URL` |
| `/transcriber/resend-api-key` | `RESEND_API_KEY` |
| `/transcriber/resend-webhook-secret` | `RESEND_WEBHOOK_SECRET` |
| `/transcriber/google-client-id` | `GOOGLE_CLIENT_ID` |

> 藍新 / Gemini / OpenAI / HF / Sentry 等其餘密鑰目前由 `.env`（或 CI secret）注入；若要進一步收斂，建議一併移入 SSM。

---

## 相關文件
- 部署架構：`docs/AWS_DEPLOYMENT_PLAN.md`、`docs/DEPLOYMENT.md`
- 監控設定：`docs/MONITORING_SETUP.md`
- 金流串接：`docs/NEWEBPAY_PERIOD_API.md`
- 環境變數完整清單：`.env.example`、`deploy/.env.aws`
