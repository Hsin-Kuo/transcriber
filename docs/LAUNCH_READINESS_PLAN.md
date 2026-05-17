# 上線前修改計畫（Launch Readiness）

> 建立日期：2026-05-17
> 目標：把 SoundLite 從「可運行」推到「可公開導流」的狀態
> 範圍：資安、可維護性、開發/測試/運維三個維度的 launch blocker

---

## 進度總覽

- 🔴 **Blocker（上線前必補）**：B1–B10
- 🟡 **上線後一個月內補**：M1–M8
- 🟢 **規模到了再做**：L1–L4

| 階段 | 預估時間 | 內容 | 狀態 |
|------|---------|------|------|
| Day 1-2 | 30 分鐘 ~ 半天 | B5 / B4 / B8 / B10（純配置） | ✅ 已完成 |
| Day 3-5 | 2-3 天 | B1 staging 環境 | ⏳ 待 AWS 操作 |
| Day 6-8 | 2 天 | B6 真 health check + B7 rollback | ✅ 程式碼完成 |
| Day 9-12 | 3-4 天 | B2 CI gate + E2E + payment webhook 測試 | ⏳ 待規劃 |
| Day 13-14 | 1-2 天 | B3 cookie 改造 + B9 webhook idempotency | B9 ✅；B3 ⏳ |

---

## 🔴 Blocker 清單

### B1. 建立 staging 環境
- [ ] 開新 MongoDB Atlas cluster（M2，含 point-in-time recovery）
- [ ] 建立獨立 SQS queue（`transcriber-tasks-staging`）
- [ ] 建立獨立 S3 bucket（`transcriber-files-staging-*`）
- [ ] 開 t3.micro EC2，部署 staging stack
- [ ] CI 改成：`main` → staging（自動）；`release/*` → production（手動 approve）
- [ ] Nginx 配 `staging.soundlite.app`（Cloudflare DNS + cert）
- **預算**：~$15/月

### B2. CI lint/test gate + 補核心測試
- [ ] 新增 `.github/workflows/test.yml`，PR 階段跑：
  - `ruff check src/`
  - `pytest tests/`
  - 前端 `eslint`（B2 完成後）
- [ ] 補 `src/services/task_service.py` 單元測試（任務狀態機）
- [ ] 補 `src/routers/auth.py` 單元測試（登入/註冊/密碼重設）
- [ ] 補 `src/routers/subscriptions.py` webhook idempotency 測試（搭配 B9）
- [ ] Playwright E2E 4 條黃金路徑：
  - 註冊 → email 驗證 → 登入
  - 上傳音檔 → 開始轉錄 → SSE 收進度 → 完成
  - 訂閱付款 webhook 流程
  - Admin 登入 + 改使用者方案

### B3. Refresh token 改用 httpOnly cookie
- 檔案：`frontend/src/stores/auth.js`、`src/routers/auth.py`、`src/auth/jwt_handler.py`
- [ ] 後端 `/auth/refresh` 改為從 cookie 讀 refresh token
- [ ] 後端 login/register response 用 `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=Strict; Path=/auth/refresh`
- [ ] 前端 axios 設 `withCredentials: true`，移除 localStorage 中的 refresh token
- [ ] Access token 縮短到 15 分鐘
- [ ] CORS 設定加 `allow_credentials=True`

### B4. MongoDB 明確驗證 TLS CA ✅
- 檔案：`src/database/mongodb.py`
- [x] Atlas 連線顯式設 `tls=True, tlsAllowInvalidCertificates=False`
- [x] startup 黑名單檢查 `tlsInsecure / tlsAllowInvalidCertificates / tlsAllowInvalidHostnames`

### B5. JWT secret 熵檢查 ✅
- 檔案：`src/auth/jwt_handler.py`
- [x] 採 Shannon entropy + 格式雙重檢查（hex 門檻 3.5、base64 門檻 4.5）
- [x] `.env.example` 註解更新

### B6. /health 改為真檢查 + GPU worker heartbeat ✅（程式碼）
- 檔案：`src/main.py`、`src/worker_core/sqs_consumer.py`、`src/worker_core/heartbeat.py`
- [x] `/health` 改為 `client.admin.command("ping")` + 1s timeout，degraded 回 503
- [x] 新增 `/readiness`：DB ok + model 載完才回 200
- [x] Worker startup / 每完成任務 / 60 秒背景 keep-alive 寫 `worker_heartbeats`
- [x] worker_id 自動偵測（env > EC2 IMDSv2 > hostname）
- [ ] **手動**：CloudWatch alarm（5 分鐘無 heartbeat → SNS）
- [ ] **手動**：EC2 StatusCheckFailed auto-recovery action

### B7. Rollback 機制 ✅
- 檔案：`.github/workflows/deploy-aws.yml`、`deploy/rollback.sh`
- [x] deploy artifact 命名 `backend-<sha>.tar.gz`、`frontend-<sha>.tar.gz`、`admin-frontend-<sha>.tar.gz`
- [x] EC2 上保留最近 5 版 tar.gz 於 `/opt/transcriber/releases/`
- [x] `CURRENT` 檔記錄當前版本
- [x] `deploy/rollback.sh` 安裝到 `/usr/local/bin/transcriber-rollback`
- [x] 支援 `sudo transcriber-rollback`（列版本）/ `<sha>` / `--prev`
- [x] 回滾完成自動跑 /health 驗證

### B8. 上傳副檔名 / MIME 白名單 ✅
- 檔案：`src/services/utils/audio_validator.py`（新）、`src/routers/uploads.py`、`src/routers/transcriptions.py`
- [x] 副檔名白名單：`.mp3 .m4a .wav .ogg .oga .flac .aac .webm .mp4 .opus .wma`
- [x] 純 Python magic bytes 檢查（無 libmagic 系統依賴）
- [x] chunked upload init（副檔名）+ complete（magic bytes）
- [x] 直接上傳 / 合併 / 批次三條路徑都驗
- [x] 驗證失敗自動清理 temp_dir，不留垃圾

### B9. 藍新 webhook idempotency ✅
- 檔案：`src/database/repositories/processed_webhook_repo.py`（新）、`src/routers/subscriptions.py`
- [x] `processed_webhooks` collection + `_id` unique 作為原子 claim
- [x] TTL 90 天自動清理
- [x] 定期定額 natural_id = `<order>:<already_times>`（每期獨立）
- [x] MPG natural_id = `<order>`（一次性付款）
- [x] 啟動時自動建索引
- 註：本專案無 Stripe（只有藍新）

### B10. CSP 啟用 + auth/upload rate limit ✅
- 檔案：`deploy/nginx-ec2.conf`
- [x] CSP Report-Only：主站涵蓋 Google OAuth / Stripe / Sentry
- [x] CSP Report-Only：admin 更嚴格（只 Sentry，無 OAuth/Stripe）
- [x] 新增 `auth` zone 3r/m burst 5、`upload` zone 10r/m burst 5
- [x] 主站 auth 包含 login/register/forgot/reset/verify/resend
- [x] 主站 upload 套用 init/complete（chunks/* 不限）
- [x] admin 後台 auth 也限流
- [x] docker nginx -t 文法通過
- [ ] **手動**：上線後一週檢視 CSP 違規報告再切強制模式

---

## 🟡 上線後一個月內補

### M1. Router / Service 邊界整理
- `src/routers/transcriptions.py` (1959 行)、`tasks.py` (1562 行)、`admin.py` (1267 行)
- [ ] 抽出 SQS 簽名、檔案驗證、presigned URL 到 `src/services/utils/`
- [ ] 建立 `src/config/deployment.py`，集中 53 處 `DEPLOY_ENV` 判斷
- [ ] `TranscriptionService` 拆「轉錄計算」與「狀態協調」

### M2. 兩個前端的超大檔案
- [ ] `TranscriptDetailView.vue` (3645 行) 拆 composables + 子元件
- [ ] `UserSettingsView.vue` (2910 行) 同樣處理
- 註：與 `IMPROVEMENT_TASKS.md` T4 重疊，沿用該追蹤

### M3. 前端 TypeScript + ESLint
- [ ] 兩個前端各加 ESLint + Prettier
- [ ] `tsconfig.json` 設 `allowJs: true`，新檔強制 .ts
- [ ] 優先轉 `src/api/services.js`、`src/stores/auth.js`

### M4. 結構化 log + request_id
- [ ] 上 `structlog` 取代 `print()`
- [ ] FastAPI middleware 注入 `request_id` UUID
- [ ] request_id 寫進 Sentry tag

### M5. Sentry 死角補齊
- [ ] `asyncio.create_task()` 包 sentry capture wrapper
- [ ] Worker SQS poll loop 外層加 top-level `capture_exception`
- [ ] 前端兩個 app 用同一 Sentry project + `component` tag 區分

### M6. GitHub Actions 改 OIDC + pin SHA
- [ ] 短期：SSH key 改 `webfactory/ssh-agent`（不落地）
- [ ] 中期：改 AWS OIDC + STS token
- [ ] 所有 actions pin 到 commit SHA（dependabot 自動更新）

### M7. Admin 高權操作通知 + audit 強化
- [ ] 改密碼/email/方案時寄通知信給使用者
- [ ] audit_logs 補 admin IP、user-agent
- [ ] Admin 介面對危險操作加二次確認

### M8. 分享連結權杖
- [ ] `tasks` document 加 `share_token_expires`、`share_token_revoked`
- [ ] 前端 UI 加「設定過期」與「撤銷」按鈕

---

## 🟢 規模到了再做

- **L1. Feature flag / 灰度**：用戶過 500 再做
- **L2. Load test (k6)**：MAU 過 1000 再做
- **L3. Schema migration framework**：先用 `scripts/migrations/` + version registry 撐住
- **L4. ADR (`docs/adr/`)**：團隊超過 1 人再開始補寫

---

## 完工條件

- [ ] 所有 🔴 blocker 完成且驗證
- [ ] staging 跑過完整 E2E 一次無錯
- [ ] 線上監控（health + heartbeat + sentry）能在 5 分鐘內偵測到異常
- [ ] 確認 rollback 腳本能在 2 分鐘內回到上一版
