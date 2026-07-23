# CLAUDE.md — Transcriber (SoundLite)

語音轉文字平台（多語言、說話者辨識、AI 標點強化）。https://soundlite.app
後端 Python/FastAPI，前端 Vue 3 + Pinia，資料庫 MongoDB Atlas。

## Session 紀律（每個 session 先讀這四條）

1. **先路由再動手**：下方「路由表」列出各類任務該先讀哪個檔。委派 subagent、選 model、判斷完成與否，都有既定規則，不要憑感覺。
2. **指揮官不下場**：掃 repo、讀 >3 個檔案、網頁研究 → 一律派 subagent，主對話只收結論；輸出可能很長的指令（測試/build/log）用 `| tail`/`grep` 收斂或背景執行。細節與門檻見 `.claude/docs/model-dispatch.md`。
3. **Memory 先驗證再引用**：memory 提到的 branch / 檔案 / 資源，先用一條指令確認存在（`git branch -a | grep X`、`ls`）。驗不到就當歷史線索，不是現況。
4. **收尾要落檔**：session 結束時有未完成的工作，照 `.claude/docs/judgment-rubrics.md` §8 寫 memory（階梯位置 + 分支/PR + 一條驗證指令）。

## 路由表（做 X 之前先讀 Y）

| 情境 | 先讀 |
|------|------|
| 要派 subagent / 選 model / 升降級 / 驗收 | `.claude/docs/model-dispatch.md` |
| 判斷「完成了沒」「該不該問使用者」「方向對不對」 | `.claude/docs/judgment-rubrics.md` |
| 撰寫委派 prompt（搜尋/實作/重構/研究/審查） | `.claude/docs/delegation-templates.md` |
| 想修改本檔（CLAUDE.md）或 `.claude/docs/` 底下任何制度檔 | `.claude/docs/maintenance-protocol.md` |
| 新 session 第一次接手、或覺得環境狀態怪怪的 | `.claude/docs/letter-to-future-sessions.md` |
| Persistent vs transient state 劃分、領域詞彙 | `CONTEXT.md` |
| 部署細節 / staging 規劃 / 金流 API | `docs/DEPLOYMENT.md`、`docs/STAGING_PLAN.md`、`docs/NEWEBPAY_PERIOD_API.md` |

## 目錄結構（節選；完整結構直接 `ls` 對應目錄）

```
src/                  # 後端 FastAPI
  main.py             # Web 入口；worker.py = GPU Worker 入口（APP_ROLE=worker）
  worker_core/        # sqs_consumer / transcription_job / spot_monitor / heartbeat / model_cache
  routers/            # API 路由（auth, oauth, tasks, transcriptions, uploads, audio,
                      #   tags, summaries, shared, subscriptions, email_webhooks, admin）
  services/           # 業務邏輯（intake_service, task_service, task_dispatch,
                      #   worker_dispatch, progress_store, …）
  services/utils/     # 無狀態 processor（whisper / punctuation / diarization / audio_validator）
  transcription/      # 轉錄 pipeline（orchestrator + audio_source；Web 與 Worker 共用）
  utils/              # storage_service, config_loader, newebpay_service, email_service, logger…
  database/repositories/  # MongoDB CRUD
  auth/  models/
frontend/             # 使用者前端 (Vue3+Vite, dev 3000 / docker 3000)
admin-frontend/       # 管理後台 (dev 3001 / docker 3003)
deploy/               # 部署腳本 + nginx / systemd canonical 檔（禁止 SSH 直接改 EC2 上的檔）
docs/                 # 深度文件（部署、staging、金流、postmortem…）
```

## 啟動方式

```bash
# Docker Compose（推薦）
cp .env.example .env && docker-compose up -d
# frontend:3000  admin:3003  api:8000  mongo:27020

# 原生開發：MongoDB 要 single-node replica set（支援 transaction）
docker run -d --name mongo -p 27020:27017 mongo:7.0 mongod --replSet rs0 --bind_ip_all
docker exec mongo mongosh --quiet --eval "rs.initiate({_id:'rs0',members:[{_id:0,host:'localhost:27017'}]})"
# 連線字串需含 ?replicaSet=rs0&directConnection=true

pip install -r requirements.txt && ./start_backend_daemon.sh   # 後端 daemon
npm run dev / npm run dev:admin / npm run dev:all              # 前端
npm run backend:status / backend:restart                        # 後端管理
tail -f backend.log                                             # 後端 log（大檔，用 grep/tail，別整檔讀）
```

API 文件：後端啟動後 http://localhost:8000/docs

## 環境變數（完整見 `.env.example`）

關鍵：`MONGODB_URL`、`JWT_SECRET_KEY`（≥32字元）、`GOOGLE_API_KEY_1`（Gemini 標點）、
`HF_TOKEN`（diarization）、`GOOGLE_CLIENT_ID`、`DEPLOY_ENV`（local|aws）、
`NEWEBPAY_*`（藍新金流）、`EMAIL_PROVIDER`（生產用 resend，非 SES）。
AWS 部署另需：`S3_BUCKET`、`SQS_QUEUE_URL`、`WORKER_SECRET`、`APP_ROLE`。

## 架構重點

- **三層**：Routers（HTTP/驗證/權限）→ Services（業務邏輯）→ Repositories（MongoDB CRUD）。
- **任務流**：上傳音檔 → 建 Task → Worker 處理 → SSE 推進度 → 完成。
- **雙環境**：`DEPLOY_ENV=local` Whisper 同進程；`DEPLOY_ENV=aws` Web Server（APP_ROLE=server）發 SQS → GPU Worker（`src/worker.py`）long poll。**Lambda `transcriber-gpu-starter` 負責喚醒 GPU；worker 空閒 5 分鐘自行 shutdown（關機不經 Lambda）**。
- **prod/staging 隔離**：`APP_ENV=staging` 讓 `config_loader` 改讀 SSM `/transcriber-staging/*`（單點路由）。staging 物理隔離（獨立 EC2/SQS/S3/Atlas），網址 staging.soundlite.app。
- **CI/CD 三層分支**：`feature → main → staging → aws`。main 不部署；push staging/aws 各觸發對應 workflow；Promotion Guard 強制來源分支。**只用 merge commit（禁 squash/rebase）**。systemd/nginx/.env 全部 sync from repo，禁止 SSH 手改。
- **SSE 進度**：local 同進程讀 `task_progress`；aws 下 Worker 寫、Web Server 每 2 秒 poll 同 collection。
- **uvicorn --workers 2**：per-worker semaphore，全機並行上限 = 設定值 × 2。

### MongoDB collections（一行速查）
`users`(帳號/配額/訂閱) `tasks`(persistent state) `task_progress`(transient, TTL 6h)
`transcriptions` `segments` `tags` `summaries` `audit_logs` `orders`
`processed_webhooks`(idempotency) `rate_limits` `reservations`(配額預留)
`chunk_uploads`(分片上傳, 3h sweep) `worker_heartbeats`(GPU keep-alive)

## AWS 生產環境速查（ap-northeast-1）

- Web EC2：`3.112.209.96`（t3.small + Nginx；SSH：`ssh -i ~/.ssh/transcriber-key.pem ec2-user@3.112.209.96`）
- S3：`transcriber-files-696637902131`；SQS：`transcriber-tasks`
- GPU Worker：g4dn.xlarge（Spot `i-0d133cca8e6ce23c2`，On-Demand 備援 `i-058f381c59210c00a`）
- 密鑰統一在 SSM Parameter Store `/transcriber/*`（staging 為 `/transcriber-staging/*`）
- Staging Web EIP：`52.196.120.189`
- GPU worker 佈建/重建：`bash deploy/deploy-gpu-worker.sh [prod|staging]`

## 安全規範（修改相關程式時必須維持）

JWT 密鑰 ≥32 字元；SQS 訊息 HMAC-SHA256 簽名；path traversal 防護（UUID 驗證 + 目錄白名單）；
生產 CORS 強制設定；輸入白名單（language、punct_provider 等）；email enumeration 防護；
S3 presigned URL 域名驗證。凡動到 auth / payment / IAM / webhook 的 diff，
走 `judgment-rubrics.md` §5 的高風險驗收流程。
