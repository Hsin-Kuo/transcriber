# Whisper Transcriber

> 企業級多語言語音轉錄系統，支援用戶認證、標籤管理、審計日誌與管理後台

## 專案簡介

Whisper Transcriber v3.0 是一個功能完整的多語言語音轉錄平台，基於 OpenAI Whisper 進行高精度語音辨識，支援中文、英文、日文、韓文等多種語言。系統整合 Google Gemini 和 OpenAI API 自動添加標點符號，採用前後端分離架構，提供完整的用戶認證、任務管理、標籤系統與管理後台。

## 主要功能

### 核心轉錄功能
- **語音轉文字**：使用 faster-whisper 進行高精度多語言語音辨識（支援 99+ 種語言）
- **智慧音檔切割**：自動偵測靜音點分段處理長音檔（>10分鐘）
- **標點符號服務**：整合 Google Gemini（預設）或 OpenAI API，支援多 API Key 輪詢
- **Speaker Diarization**：使用 pyannote.audio 自動識別多個說話者

### 用戶系統
- **用戶認證**：註冊 / 登入 / 登出，JWT Token 認證
- **Email 驗證**：註冊後 Email 驗證流程
- **密碼管理**：忘記密碼、重設密碼功能
- **Google OAuth**：支援 Google 第三方登入與帳戶綁定

### 任務管理
- **異步轉錄**：任務在背景執行，不阻塞其他請求
- **狀態追蹤**：即時查看任務進度（pending → processing → completed）
- **SSE 推送**：Server-Sent Events 即時狀態更新
- **任務取消**：支援取消進行中的轉錄任務
- **標籤系統**：建立、編輯、刪除標籤，為任務分類

### 管理後台
- **用戶管理**：查看所有用戶、修改狀態 / 角色 / 配額、重設密碼
- **任務管理**：查看、取消、刪除任務，批量操作
- **審計日誌**：記錄所有重要操作，支援篩選與統計
- **系統統計**：用戶數、任務數、使用量統計

## 技術架構

### 後端（Python / FastAPI）

```
src/
├── main.py                 # FastAPI 應用入口
├── routers/                # API 路由層
│   ├── auth.py             # 認證 API
│   ├── oauth.py            # OAuth API
│   ├── tasks.py            # 任務管理 API
│   ├── transcriptions.py   # 轉錄 API
│   ├── tags.py             # 標籤管理 API
│   ├── summaries.py        # 摘要生成 API
│   └── admin.py            # 管理後台 API
├── services/               # 業務邏輯層
│   ├── task_service.py
│   ├── transcription_service.py
│   └── utils/
│       ├── whisper_processor.py      # Whisper 轉錄處理
│       ├── punctuation_processor.py  # 標點符號處理
│       └── diarization_processor.py  # 說話者辨識
├── database/               # 資料存取層
│   ├── mongodb.py          # MongoDB 連接
│   └── repositories/       # 數據操作
└── auth/                   # 認證模組
    ├── jwt_handler.py
    ├── password.py
    └── dependencies.py
```

### 前端（Vue 3 / Vite）

```
frontend/                   # 用戶前端
├── src/
│   ├── views/              # 頁面組件
│   ├── components/         # 可複用組件
│   ├── composables/        # Vue 3 組合函數
│   ├── stores/             # Pinia 狀態管理
│   └── router/             # 路由配置
└── ...

admin-frontend/             # 管理後台
├── src/
│   ├── views/              # 管理頁面
│   └── ...
└── ...
```

### 技術棧

| 類別 | 技術 |
|------|------|
| 後端框架 | FastAPI + Uvicorn |
| 語音辨識 | faster-whisper + PyTorch |
| 說話者辨識 | pyannote.audio |
| 標點服務 | Google Gemini / OpenAI API |
| 資料庫 | MongoDB (Motor 異步驅動) |
| 認證 | JWT + bcrypt |
| 前端框架 | Vue 3 + Vite |
| 狀態管理 | Pinia |
| HTTP 客戶端 | Axios |
| 音頻播放 | WaveSurfer.js |
| 國際化 | Vue I18n |
| 容器化 | Docker + Docker Compose |

## 目錄結構

```
transcriber/
├── src/                      # 後端原始碼
├── frontend/                 # 用戶前端 (Vue 3)
├── admin-frontend/           # 管理後台 (Vue 3)
├── output/                   # 轉錄結果輸出
├── uploads/                  # 上傳文件存儲
├── requirements.txt          # Python 依賴
├── requirements_auth.txt     # 認證相關依賴
├── .env.example              # 環境變數範本
├── Dockerfile                # 後端 Docker 配置
├── docker-compose.yml        # 多容器編排
├── start_backend_daemon.sh   # 啟動後端腳本
├── stop_backend.sh           # 停止後端腳本
├── restart_backend.sh        # 重啟後端腳本
└── status_backend.sh         # 查看後端狀態
```

## 快速開始

### 系統需求

- Python 3.10+
- Node.js 16+
- MongoDB 7.0+
- FFmpeg（音頻編解碼）
- 8-12GB RAM（使用 medium 模型）

### 1. 環境設定

```bash
# 克隆專案
git clone <repository-url>
cd transcriber

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入您的配置
```

### 2. 環境變數配置

在 `.env` 檔案中設定以下變數：

```bash
# MongoDB
MONGODB_URL=mongodb://127.0.0.1:27020
MONGODB_DB_NAME=whisper_transcriber

# JWT 認證
JWT_SECRET_KEY=your_jwt_secret_key_here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=30

# Google Gemini API（支援多個 Key 輪詢）
GOOGLE_API_KEY_1=your_gemini_api_key_1
GOOGLE_API_KEY_2=your_gemini_api_key_2

# OpenAI API（選填）
OPENAI_API_KEY=your_openai_api_key

# Hugging Face Token（Speaker Diarization 必填）
HF_TOKEN=your_huggingface_token

# Google OAuth（選填）
GOOGLE_CLIENT_ID=your_google_client_id

# Email 服務（選填，用於驗證郵件）
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
FRONTEND_URL=http://localhost:3000

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:5173
```

### 3. 啟動服務

#### 方式一：使用 Docker Compose（推薦）

```bash
# 啟動所有服務
docker-compose up -d

# 服務端口：
# - 前端：http://localhost:3000
# - 管理後台：http://localhost:3003
# - 後端 API：http://localhost:8000
# - MongoDB：localhost:27020
```

#### 方式二：原生運行

**啟動 MongoDB：**
```bash
# 使用 Docker 運行 MongoDB
docker run -d --name mongo -p 27020:27017 mongo:7.0
```

**啟動後端：**
```bash
# 安裝依賴
pip install -r requirements.txt

# 背景執行（推薦）
./start_backend_daemon.sh

# 或前景執行（開發用）
python src/main.py --host 0.0.0.0 --port 8000 --model medium
```

**啟動前端：**
```bash
# 用戶前端
cd frontend
npm install
npm run dev  # http://localhost:5173

# 管理後台
cd admin-frontend
npm install
npm run dev  # http://localhost:5174
```

### 4. 後端管理腳本

```bash
./start_backend_daemon.sh   # 啟動後端（背景執行）
./status_backend.sh         # 查看後端狀態
./stop_backend.sh           # 停止後端
./restart_backend.sh        # 重啟後端
tail -f backend.log         # 查看即時日誌
```

## API 端點

### 認證相關

| 方法 | 端點 | 描述 |
|------|------|------|
| POST | `/auth/register` | 用戶註冊 |
| POST | `/auth/login` | 用戶登入 |
| POST | `/auth/logout` | 用戶登出 |
| POST | `/auth/refresh` | 刷新 Token |
| GET | `/auth/me` | 獲取當前用戶資訊 |
| GET | `/auth/verify-email` | Email 驗證 |
| POST | `/auth/forgot-password` | 忘記密碼 |
| POST | `/auth/reset-password` | 重設密碼 |

### OAuth 相關

| 方法 | 端點 | 描述 |
|------|------|------|
| POST | `/oauth/google` | Google OAuth 登入 |
| POST | `/oauth/google/bind` | 綁定 Google 帳戶 |
| DELETE | `/oauth/google/unbind` | 解綁 Google 帳戶 |

### 轉錄相關

| 方法 | 端點 | 描述 |
|------|------|------|
| POST | `/transcriptions` | 建立轉錄任務 |
| GET | `/tasks/{task_id}` | 獲取任務狀態 |
| GET | `/tasks/{task_id}/events` | SSE 即時狀態更新 |
| POST | `/tasks/{task_id}/cancel` | 取消任務 |
| DELETE | `/tasks/{task_id}` | 刪除任務 |
| GET | `/transcriptions/{task_id}/download` | 下載轉錄結果 |
| GET | `/transcriptions/{task_id}/segments` | 獲取時間軸片段 |

### 標籤管理

| 方法 | 端點 | 描述 |
|------|------|------|
| POST | `/api/tags` | 建立標籤 |
| GET | `/api/tags` | 獲取所有標籤 |
| PUT | `/api/tags/{tag_id}` | 更新標籤 |
| DELETE | `/api/tags/{tag_id}` | 刪除標籤 |
| GET | `/api/tags/statistics` | 獲取標籤統計 |

### 管理後台

| 方法 | 端點 | 描述 |
|------|------|------|
| GET | `/admin/users` | 列出所有用戶 |
| PUT | `/admin/users/{user_id}/status` | 修改用戶狀態 |
| PUT | `/admin/users/{user_id}/role` | 修改用戶角色 |
| GET | `/admin/tasks` | 列出所有任務 |
| GET | `/admin/statistics` | 獲取系統統計 |
| GET | `/admin/audit-logs` | 獲取審計日誌 |

完整 API 文檔請訪問：
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## 使用流程

### 1. 用戶註冊與登入

1. 訪問前端 `http://localhost:3000`
2. 點擊「註冊」建立帳戶
3. 檢查 Email 並點擊驗證連結
4. 使用帳號密碼登入，或使用 Google 第三方登入

### 2. 上傳音檔轉錄

1. 在主頁面上傳音檔（支援 m4a, mp3, wav, mp4, flac 等）
2. 選擇標點服務（Gemini / OpenAI / 無）
3. 選擇是否啟用說話者辨識
4. 提交後可即時查看轉錄進度
5. 完成後可下載結果或在線編輯

### 3. 管理轉錄結果

- 在「我的任務」頁面查看所有任務
- 使用標籤功能分類管理
- 點擊任務查看詳細內容與時間軸
- 支援下載 txt 格式

## 常見問題

### Q: 支援哪些音訊格式？
A: 支援所有 FFmpeg 可處理的格式，包括 m4a, mp3, wav, mp4, flac 等。

### Q: 支援哪些語言？
A: 支援 Whisper 模型支援的所有語言（99+ 種），包括中文、英文、日文、韓文、法文、德文、西班牙文等。系統會自動偵測語言，也可手動指定。

### Q: 哪個 Whisper 模型最好？
A: `medium` 模型提供良好的準確度與速度平衡。若需最高準確度選 `large-v2`，若需快速處理選 `small`。對於非英語語言，建議使用 `medium` 以上的模型。

### Q: 標點符號服務選哪個？
A: Google Gemini 速度較快且成本較低，OpenAI GPT 品質稍好但較貴。兩者都能提供良好結果。

### Q: 如何處理長音檔？
A: 系統會自動偵測靜音點並分段處理，預設超過 10 分鐘的音檔會自動切割。

### Q: 可以同時轉錄多個檔案嗎？
A: 支援。目前並發數限制為 2，超過的請求會自動排隊。

### Q: Speaker Diarization 需要什麼？
A: 需要 Hugging Face Token，並同意 pyannote 模型的使用條款。

### Q: 忘記密碼怎麼辦？
A: 在登入頁面點擊「忘記密碼」，輸入 Email 後系統會發送重設連結。

## 更新日誌

### v3.0.0 (2025-02)
- **用戶認證系統**：完整的註冊 / 登入 / Email 驗證流程
- **Google OAuth**：支援 Google 第三方登入與帳戶綁定
- **密碼管理**：新增忘記密碼、重設密碼功能
- **管理後台**：獨立的管理介面，用戶 / 任務 / 審計日誌管理
- **標籤系統**：為任務建立分類標籤
- **審計日誌**：記錄所有重要操作
- **三層架構**：Router → Service → Repository 清晰分層
- **MongoDB 整合**：使用 Motor 異步驅動

### v2.1.0 (2025-01)
- **Speaker Diarization**：使用獨立進程執行，可被立即終止
- **效能優化**：調整 Whisper 模型並行配置
- **前端改進**：任務卡片顯示 Diarization 狀態

### v2.0.0 (2024-12)
- **異步轉錄**：任務在背景執行，不阻塞其他請求
- **SSE 推送**：Server-Sent Events 即時狀態更新
- **Vue 3 前端**：全新的用戶介面

### v1.0.0 (2024-11)
- 初始版本發布
- 支援多語言語音轉錄
- 整合 Gemini 和 OpenAI 標點服務

## 授權

[請在此添加您的授權資訊]

## 貢獻

歡迎提交 Issue 和 Pull Request！
