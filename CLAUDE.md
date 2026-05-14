# CLAUDE.md — Transcriber (SoundLite)

## 專案簡介

語音轉文字平台，支援多語言、說話者辨識、AI 標點強化。
- 網站：https://soundlite.app
- 後端：Python / FastAPI
- 前端：Vue 3 + Pinia
- 資料庫：MongoDB Atlas

---

## 目錄結構

```
src/                  # 後端 (FastAPI)
  main.py             # 應用入口（uvicorn）
  worker.py           # AWS GPU Worker（SQS consumer，APP_ROLE=worker 時啟動）
  routers/            # API 路由
    auth.py           # 認證（註冊/登入/email驗證/密碼重設）
    oauth.py          # Google OAuth
    tasks.py          # 任務狀態、SSE 進度推送
    transcriptions.py # 上傳音檔、建立轉錄任務
    uploads.py        # 批次上傳
    audio.py          # 音檔下載
    tags.py           # 標籤管理
    summaries.py      # AI 摘要
    shared.py         # 分享連結（無需登入可看）
    subscriptions.py  # Stripe 訂閱付款
    admin.py          # 管理後台 API
  services/           # 業務邏輯
    utils/            # 工具類
      whisper_processor.py      # faster-whisper 轉錄
      punctuation_processor.py  # Gemini 標點強化
      diarization_processor.py  # pyannote 說話者辨識
      storage_service.py        # 檔案存取（local/S3 自動切換）
      config_loader.py          # 密鑰讀取（SSM / .env fallback）
  database/
    repositories/     # MongoDB CRUD
  auth/               # JWT、密碼、依賴注入
  models/             # Pydantic 資料模型
frontend/             # 使用者前端 (Vue 3 + Vite, port 5173/3000)
admin-frontend/       # 管理後台 (Vue 3 + Vite, port 5174/3003)
deploy/               # AWS 部署腳本
  nginx-ec2.conf      # Nginx 設定（生產用）
  deploy-web.sh       # Web Server 初始部署腳本
  deploy-gpu-worker.sh# GPU Worker 初始部署腳本
```

---

## 啟動方式

### Docker Compose（推薦）
```bash
cp .env.example .env   # 填入 API keys
docker-compose up -d
# Frontend:       http://localhost:3000
# Admin:          http://localhost:3003
# Backend API:    http://localhost:8000
# MongoDB:        localhost:27020
```

### 原生開發
```bash
# MongoDB（single-node replica set，支援 transaction）
docker run -d --name mongo -p 27020:27017 mongo:7.0 \
  mongod --replSet rs0 --bind_ip_all
# 第一次啟動需 init replica set：
docker exec mongo mongosh --quiet --eval \
  "rs.initiate({_id: 'rs0', members: [{_id: 0, host: 'localhost:27017'}]})"
# 連線字串需含 ?replicaSet=rs0&directConnection=true

# 後端
pip install -r requirements.txt
./start_backend_daemon.sh

# 前端（各自開新 terminal）
cd frontend && npm install && npm run dev
cd admin-frontend && npm install && npm run dev
```

### 常用 npm scripts（根目錄）
```bash
npm run dev            # 使用者前端
npm run dev:admin      # 管理後台
npm run dev:all        # 兩個前端同時啟動
npm run backend        # 啟動後端 daemon
npm run backend:status # 查看後端狀態
npm run backend:restart
```

### 後端管理腳本
```bash
./start_backend_daemon.sh
./status_backend.sh
./stop_backend.sh
./restart_backend.sh
tail -f backend.log    # 即時 log
```

---

## 重要環境變數

見 `.env.example`，關鍵項目：

| 變數 | 說明 |
|------|------|
| `MONGODB_URL` | MongoDB 連線字串 |
| `JWT_SECRET_KEY` | 最少 32 字元 |
| `GOOGLE_API_KEY_1` | Gemini API（標點強化） |
| `HF_TOKEN` | HuggingFace（speaker diarization） |
| `GOOGLE_CLIENT_ID` | Google OAuth |
| `DEPLOY_ENV` | `local` 或 `aws` |
| `STRIPE_SECRET_KEY` | Stripe 訂閱付款 |
| `EMAIL_PROVIDER` | `console` / `smtp` / `resend`（生產用 Resend，非 SES） |

AWS 部署時額外需要：`S3_BUCKET`, `SQS_QUEUE_URL`, `WORKER_SECRET`, `APP_ROLE`

AWS 生產環境實際值（ap-northeast-1）：
- `S3_BUCKET` = `transcriber-files-696637902131`
- `SQS_QUEUE_URL` = `https://sqs.ap-northeast-1.amazonaws.com/696637902131/transcriber-tasks`
- Web Server EC2 Elastic IP = `3.112.209.96`
- 敏感密鑰由 SSM Parameter Store 統一管理（`/transcriber/*`）

---

## 架構重點

### 三層架構
1. **Routers** — HTTP 請求、驗證、權限
2. **Services** — 核心業務邏輯
3. **Repositories** — MongoDB CRUD

### 非同步任務流程
```
上傳音檔 → 建立 Task → 背景 Worker 處理 → SSE 推送進度 → 完成
```

### AWS 雙環境
```
DEPLOY_ENV=local  → Whisper 在同一進程執行
DEPLOY_ENV=aws    → Web Server (APP_ROLE=server) + GPU Worker (APP_ROLE=worker) 分離
                    Web Server 發 SQS 訊息 → GPU Worker (src/worker.py) Long Poll 接收
                    GPU Worker 空閒 5 分鐘後自行呼叫 shutdown（無 Lambda）
```

### AWS 生產部署架構
- **Web Server**：EC2 t3.small + Nginx（反向代理 + 靜態檔案 serve）
- **前端**：build 後直接部署到 EC2 `/var/www/transcriber`（非 S3+CloudFront）
- **GPU Worker**：EC2 g4dn.xlarge Spot，`src/worker.py` 作為 SQS consumer
- **CI/CD**：GitHub Actions，push 到 **`aws` 分支**觸發部署（非 `main`）

### MongoDB Collections
- `users` — 帳號、角色、使用配額、Stripe 訂閱 ID
- `tasks` — 轉錄任務記錄（含 AWS 模式下的 progress 供 SSE polling）
- `transcriptions` — 轉錄文字與中繼資料
- `tags` — 使用者標籤
- `summaries` — AI 摘要
- `audit_logs` — 管理員操作記錄

### SSE 進度推送（本地 vs AWS 行為不同）
- `DEPLOY_ENV=local`：in-memory dict，Worker 直接更新
- `DEPLOY_ENV=aws`：Web Server SSE endpoint 每 2 秒 poll MongoDB，GPU Worker 寫入進度

---

## 安全規範

已實施的安全措施（修改時需維持）：
- JWT 密鑰強制 32 字元以上
- SQS 訊息用 HMAC-SHA256 簽名
- Path traversal 防護（UUID 驗證 + 目錄白名單）
- CORS 在生產環境強制設定
- 輸入驗證白名單（language、punct_provider 等）
- Email enumeration 防護
- S3 presigned URL 域名驗證

---

## API 文件

啟動後端後可瀏覽：
- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc
