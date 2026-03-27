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
  routers/            # API 路由 (auth, tasks, transcriptions, uploads, subscriptions...)
  services/           # 業務邏輯
    utils/            # Whisper、diarization、標點處理
  database/
    repositories/     # MongoDB CRUD
  auth/               # JWT、密碼、依賴注入
  models/             # Pydantic 資料模型
frontend/             # 使用者前端 (Vue 3 + Vite, port 5173/3000)
admin-frontend/       # 管理後台 (Vue 3 + Vite, port 5174/3003)
deploy/               # AWS 部署腳本
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
# MongoDB
docker run -d --name mongo -p 27020:27017 mongo:7.0

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
| `EMAIL_PROVIDER` | `console` / `smtp` / `ses` |

AWS 部署時額外需要：`S3_BUCKET`, `SQS_QUEUE_URL`, `WORKER_SECRET`, `APP_ROLE`

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
                    SQS 佇列 → Lambda 自動啟動 GPU → 空閒 5 分鐘後關機
```

### MongoDB Collections
- `users` — 帳號、角色、使用配額
- `tasks` — 轉錄任務記錄
- `transcriptions` — 轉錄文字與中繼資料
- `tags` — 使用者標籤
- `summaries` — AI 摘要
- `audit_logs` — 管理員操作記錄

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
