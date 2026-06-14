# 上線前修改計畫（Launch Readiness）

> 建立日期：2026-05-17
> 最後更新：2026-05-22
> 目標：把 SoundLite 從「可運行」推到「可公開導流」的狀態
> 範圍：資安、可維護性、開發/測試/運維三個維度的 launch blocker

---

## 整體進度總覽

```
🔴 Blocker（上線前必補）9/10  完成
🟡 中期負債（一個月內）   8/8  完成
🟢 規模到了再做           0/4  暫不啟動
```

### 剩餘待辦
- ~~**B1** Staging 環境~~ ✅ **2026-06-14 完成並端到端驗過**（獨立環境 + 三層分支；見 [`STAGING_PLAN.md`](./STAGING_PLAN.md) / [`DEPLOYMENT.md`](./DEPLOYMENT.md)）
- **M1 #2** DeploymentMode adapter — 剩 SSE polling / 模型載入等非派發 `is_aws()`（派發分支已由 M1.6 收斂），可選
- 一些 manual follow-ups（見下方「手動 todo」段落）

### 已部署到 prod 的 commit 範圍
- `bc69c85`（LAUNCH_READINESS_PLAN 建立）→ `b31fd25`（M3 前端 TS）
- 共 39 個 commit、24 個 feature/refactor 改動已上 prod

---

## 🔴 Blocker 清單（9/10）

### B1. 建立 staging 環境 ✅（2026-06-14 完成，端到端驗過）
- 詳細計畫見 **[STAGING_PLAN.md](./STAGING_PLAN.md)**、日常操作見 **[DEPLOYMENT.md](./DEPLOYMENT.md)**
- 最終設計（與原規劃不同）：**獨立環境**（非共用 prod GPU）、**獨立 on-demand GPU worker**、Atlas **M0**（非 M2）、**三層分支** main→staging→aws + Promotion Guard、新開 t3.micro
- 已完成：AWS 資源 / Atlas / Cloudflare DNS+Access / 部署 / 金流 sandbox / 轉錄+diarization 端到端 / 資料隔離 + Sentry 無污染驗證 / ML 依賴鎖定 + 乾淨重建驗證
- **實際月費**：~$16/月（staging；M0 免費）。prod 升 Flex 取得備份 = 獨立任務

### B2. CI lint/test gate + 補核心測試 ✅
- [x] `pyproject.toml` 集中 ruff + pytest 設定
- [x] `requirements-dev.txt` 開發依賴（pytest / ruff）
- [x] `.github/workflows/test.yml` PR 階段跑 ruff + pytest + nginx -t + 前端 ESLint/type-check
- [x] 新增 121 個單元測試（base 31 + 安全 38 + WorkerDispatch 9 + WorkerJob 7 + Orchestrator 16 + logger 4 + others 16）
- [x] 順手修 ruff 揭露的 4 個真實 bug（typo / closure / shadow）
- [ ] Playwright E2E 4 條黃金路徑 — 依賴 B1 staging 環境

### B3. Refresh token 改用 httpOnly cookie ✅
- 詳見原計畫；前後端 + admin 三邊更新完畢
- 上線後現有用戶被踢一次（已預期）

### B4. MongoDB 明確驗證 TLS CA ✅
- `src/database/mongodb.py` + `src/database/sync_client.py` 都套
- startup 黑名單檢查 `tlsInsecure` 等不安全參數

### B5. JWT secret 熵檢查 ✅
- Shannon entropy + 格式雙重檢查（hex 門檻 3.5、base64 門檻 4.5）
- prod SSM 現有 secret 已驗證可通過

### B6. /health 真檢查 + GPU worker heartbeat ✅
- `/health` ping DB + `/readiness` 含 model 載入檢查
- Worker `worker_heartbeats` collection 60 秒 keep-alive
- CloudWatch alarm（SQS oldest age）+ Route53 health check + EC2 auto-recover
- 詳見 **[MONITORING_SETUP.md](./MONITORING_SETUP.md)**

### B7. Rollback 機制 ✅
- artifact 命名 `<component>-<sha>.tar.gz`、`/opt/transcriber/releases/` 保留最近 5 版
- `sudo transcriber-rollback --prev` 兩分鐘回上一版

### B8. 上傳副檔名 / MIME 白名單 ✅
- 11 種副檔名白名單 + 純 Python magic bytes（7 種音訊容器）
- 四條上傳路徑都驗（chunked init / chunked complete / 直接 / 合併 / 批次）

### B9. 藍新 webhook idempotency ✅
- `processed_webhooks` collection + `_id` unique 原子 claim + TTL 90 天
- claim 後處理失敗會 release + 送 Sentry + 拋 500 讓藍新重發

### B10. CSP 啟用 + auth/upload rate limit ✅
- CSP Report-Only（含 OAuth / Sentry / 藍新 form-action）
- auth zone 3r/m、upload zone 10r/m、`/subscriptions/notify/*` bypass
- [x] **手動**：CSP 違規報告檢視後已切強制模式（2026-05-25）

---

## 🟡 中期負債（8/8）

### M1. Router / Service 邊界整理 ✅（部分）

完成 5 刀，剩 1 刀可選：

| 切片 | 狀態 | 行數變化 |
|------|------|---------|
| **M1.1** WorkerDispatch seam（S3 + HMAC + SQS） | ✅ | router −135 |
| **M1.3** TranscriptionOrchestrator B 範圍（run lifecycle） | ✅ | service 1145 → 399（−65%） |
| **M1.4** Sync DB seam（取代 9 處 inline MongoClient） | ✅ | service & router 合計 −150 |
| **M1.5** TranscriptionWorkerJob typed schema（Pydantic） | ✅ | server↔worker 合約 typed |
| **M1.6** Task dispatch seam（local/AWS 派發統一為 TaskDispatch） | ✅ | 刪 transcription_service、router 去重 2 份派發分支 |
| **M1.2** DeploymentMode adapter（剩餘非派發 is_aws() 收斂） | ⏳ 大 PR 可選 | — |

> **M1.6**（2026-05-22，commit `91e64b3`）：架構審查產出。intake router 兩處複製的
> `is_aws()` 派發分支收進 `TaskDispatch` seam（`LocalDispatch` / `WorkerDispatch` 兩
> adapter）；舊淺殼 `transcription_service.py` 併入 `LocalDispatch` 後刪除；佇列查詢
> 下沉到 `task_repo`。M1.2 剩 SSE polling、模型載入等非派發 `is_aws()`。

### M2. 前端超大檔（TranscriptDetailView）✅（部分）

完成 3 刀：

| 切片 | 狀態 | 行數變化 |
|------|------|---------|
| **M2 #5** ShareDialog 元件 | ✅ | parent −200 |
| **M2 #2** useDisplayPreferences composable | ✅ | parent −23（隱藏 24 處 sync machinery） |
| **M2 #1** searchMatching 純函數抽取 | ✅ | parent −25（4 處重複收成 1 處） |
| **M2 #3/#4** AudioPlayback wrapper / Editing controller | ❌ 評估後不做 | shallow / 高風險低收益 |

3645 → 3397 行（−7%）

### M3. 前端 TypeScript + ESLint ✅
- ESLint 9 flat config（vue3-strongly-recommended）+ TypeScript（allowJs 漸進）
- 兩前端各自設定，CI matrix 跑兩邊 lint + type-check
- 轉 4 個關鍵檔到 .ts：searchMatching / endpoints / api（×2 前端）
- 順手修 `@keydown.comma` 隱性 bug 與 self-assign

### M4. 結構化 log + request_id ✅
- structlog + `RequestIdMiddleware` 注入 uuid → contextvars + Sentry tag
- X-Request-Id 支援 client 帶入（外部追蹤）

### M5. Sentry 死角補齊 ✅
- `create_background_task` 包 asyncio.create_task（6 處替換）
- Worker SQS poll loop + transcription_job 失敗都送 Sentry
- 前端兩 app 加 `component` tag

### M6. GitHub Actions ssh-agent + pin SHA ✅
- webfactory/ssh-agent 取代 key 落地
- 4 個 actions 釘完整 commit SHA
- Dependabot 自動週更（actions / pip / npm）

### M7. Admin 高權操作通知 + audit 強化 ✅
- 6 種 admin 高權操作寄通知信給用戶（reset_password / disable / role / tier / reset-quota / extra-quota）
- `log_admin_action` 收 Request 抽真實 IP + UA
- email 走 `create_background_task` 不阻擋 endpoint latency

### M8. 分享連結權杖過期 ✅
- `share_token_expires` unix 秒數，None=永久
- 過期回 410 Gone；PATCH `/expiry` 不換 token 改時間
- 前端 1/7/30/90 天下拉

---

## 🟢 規模到了再做（暫不啟動）

- **L1. Feature flag / 灰度**：用戶過 500 再做
- **L2. Load test (k6)**：MAU 過 1000 再做
- **L3. Schema migration framework**：先用 `scripts/migrations/` + version registry 撐住
- **L4. ADR (`docs/adr/`)**：團隊超過 1 人再開始補寫

---

## 手動 todo（需你動手）

1. ~~CSP Report-Only → Enforce 切換~~ ✅ 已切（2026-05-25）
2. ~~B1 staging 環境~~ ✅ 已完成（2026-06-14，含金流 sandbox）
3. **prod 升 Atlas Flex 取得備份**（prod 還在 M0、無備份；Atlas 已用 Flex 取代 M2/M5）。注意：staging 用 M0、未做 M2 演練（見 STAGING_PLAN 決策）
4. **prod 其他待辦**：`admin@example.com` 弱密碼、後端 Sentry 未啟用、BACKEND_URL 未設、web 非 EIP（建 staging 時連帶發現）

---

## 完工條件

- [x] 所有 🔴 blocker 完成且驗證（10/10，B1 staging 已完成）
- [x] staging 跑過完整 E2E（上傳→轉錄+diarization）一次無錯（2026-06-14）
- [x] 線上監控（health + heartbeat + sentry）能在 5 分鐘內偵測到異常
- [x] 確認 rollback 腳本能在 2 分鐘內回到上一版

---

## 部署現況

- main 最新 `fc57f25`（fix: 統一 API_BASE + SSE/auth/shared 回歸測試）
- prod 自開工以來部署成功 8 次（不含 dependabot 自動）
- CI gate（ruff / pytest / nginx -t / 兩前端 ESLint / 兩前端 type-check）全綠
- 後端 165 tests / 前端 31 tests 全過
