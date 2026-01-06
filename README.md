# Whisper Transcriber

> AI-powered Chinese audio transcription system with automatic punctuation

## 專案簡介

Whisper Transcriber 是一個基於 OpenAI Whisper 的中文語音轉錄系統，整合 Google Gemini 和 OpenAI API 自動添加標點符號與文字格式化，支援獨立使用或伺服器部署。

## 主要功能

- **語音轉文字**：使用 Whisper 模型進行高精度中文語音辨識
- **智慧音檔切割**：自動偵測靜音點分段處理長音檔（>10分鐘）
- **標點符號服務**：整合 Google Gemini 或 OpenAI API 自動添加標點
- **文稿精煉**：提供 4 種風格的文字後處理（書面化、精簡、正式化等）
- **REST API**：FastAPI 伺服器支援遠端呼叫
- **Docker 部署**：完整的容器化配置

## 目錄結構

```
transcriber/
├── src/                    # 原始碼
│   ├── whisper_server.py   # FastAPI 伺服器
│   └── refine_transcript.py # 文稿精煉工具
├── frontend/               # Vue 前端界面
├── docs/                   # 文檔
│   └── DOCKER_README.md    # Docker 部署說明
├── data/                   # 音訊檔案（被 git 忽略）
├── output/                 # 轉錄結果（被 git 忽略）
├── .env.example            # 環境變數範本
├── requirements.txt        # Python 依賴套件
├── Dockerfile              # Docker 映像檔配置
└── docker-compose.yml      # Docker Compose 配置
```

## 快速開始

### 1. 環境設定

```bash
# 克隆專案
git clone <repository-url>
cd transcriber

# 安裝依賴
pip install -r requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入您的 API 金鑰
```

### 2. 使用方式

#### 系統架構

本系統採用混合部署方式：
- **後端**：使用背景執行模式（daemon），原生運行以獲得最佳性能
- **前端**：使用 Docker 容器化部署，方便管理與更新

#### 步驟 1：啟動後端服務（背景執行）

**使用管理腳本（推薦）：**

```bash
# 初次設定（安裝依賴、設定環境）
./setup_native_backend.sh

# 啟動後端（背景執行）
./start_backend_daemon.sh

# 查看後端狀態
./status_backend.sh

# 查看即時日誌
tail -f backend.log

# 停止後端
./stop_backend.sh

# 重新部署後端（應用程式碼更新）
./restart_backend.sh
```

**手動啟動（開發測試）：**

```bash
# 前景執行（按 Ctrl+C 停止）
python src/whisper_server.py --host 0.0.0.0 --port 8000 --model medium
```

#### 步驟 2：啟動前端服務（Docker）

```bash
# 使用 Docker Compose 啟動前端容器
docker-compose up -d

# 查看前端日誌
docker-compose logs -f frontend

# 訪問前端界面
# http://localhost:3000
```

**停止前端服務：**

```bash
docker-compose down
```

#### 開發模式（不使用 Docker）

如果您想在開發時不使用 Docker，可以直接運行前端開發服務器：

```bash
cd frontend
npm install
npm run dev
# 訪問 http://localhost:5173
```

詳細說明請參考 [Docker 部署文檔](docs/DOCKER_README.md)

### 3. 文稿精煉

```bash
python src/refine_transcript.py -i output/transcript.txt --style podcast
```

**精煉風格：**
- `book_guide`：書面化，移除口語贅詞（預設）
- `podcast`：提取核心觀點與金句
- `concise`：濃縮成條列式摘要
- `formal`：正式化書面文字

## 技術架構

### 核心技術棧

- **AI/ML**: OpenAI Whisper, PyTorch
- **音訊處理**: pydub (格式轉換、靜音偵測)
- **網頁框架**: FastAPI + Uvicorn
- **LLM API**: Google Gemini, OpenAI GPT
- **容器化**: Docker + docker-compose

### 系統需求

- Python 3.10+
- FFmpeg（音訊編解碼）
- 8-12GB RAM（使用 medium 模型）

### 環境變數

在 `.env` 檔案中設定：

```bash
GOOGLE_API_KEY=your_google_api_key_here  # 必填
OPENAI_API_KEY=your_openai_api_key_here  # 選填
```

## API 文檔

伺服器啟動後，可透過以下端點存取：

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **健康檢查**: `http://localhost:8000/health`

### 檔案儲存機制

**FastAPI 伺服器採用混合模式處理檔案：**

- ✅ **轉錄文字檔**：自動保存到 `output/` 目錄，永久保留
  - 檔名格式：`{原檔名}_{時間戳}_transcript.txt`
  - 例如：`audio_20241111_143025_transcript.txt`

- 🗑️ **上傳的音訊檔**：處理完成後自動清理，不占用磁碟空間
  - 臨時儲存在系統臨時目錄
  - 使用 BackgroundTasks 在回應後自動刪除

### ⚡️ 異步轉錄模式

**v2.0 新功能：異步非阻塞轉錄**

轉錄任務在背景線程執行，不會阻塞其他 API 請求。適合前端應用輪詢查詢進度。

**工作流程：**
1. **提交任務**：上傳音檔，立即獲得 `task_id`
2. **輪詢狀態**：定期查詢任務進度
3. **下載結果**：完成後下載轉錄文字檔

**並發控制：**
- 最多同時處理 **1 個**轉錄任務（避免記憶體溢出）
- 超過限制的請求會排隊等待

### API 端點

#### POST /transcribe

上傳音訊檔案進行轉錄（異步模式）

**參數：**
- `file`: 音訊檔案（支援 m4a, mp3, wav, mp4 等）
- `punct_provider`: 標點服務（openai/gemini/none，預設 gemini）
- `chunk_audio`: 啟用音檔切割（true/false，預設 true）
- `chunk_minutes`: 切割長度（分鐘，預設 10）

**回傳範例：**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "message": "轉錄任務已提交，請使用 task_id 查詢狀態",
  "filename": "audio.m4a",
  "created_at": "2024-11-11 14:30:00",
  "status_url": "/transcribe/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "download_url": "/transcribe/a1b2c3d4-e5f6-7890-abcd-ef1234567890/download"
}
```

#### GET /transcribe/{task_id}

查詢轉錄任務狀態

**回傳範例：**
```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "processing",
  "filename": "audio.m4a",
  "file_size_mb": 140.5,
  "progress": "正在轉錄音訊...",
  "punct_provider": "gemini",
  "created_at": "2024-11-11 14:30:00",
  "updated_at": "2024-11-11 14:31:25"
}
```

**狀態說明：**
- `pending`: 等待處理
- `processing`: 處理中
- `completed`: 已完成
- `failed`: 失敗

#### GET /transcribe/{task_id}/download

下載轉錄結果（僅 status=completed 時可用）

**回傳：** 文字檔案下載

#### GET /transcribe/active/list

列出所有任務（含進行中的任務）

**回傳範例：**
```json
{
  "active_count": 1,
  "total_count": 5,
  "active_tasks": [
    {
      "task_id": "...",
      "status": "processing",
      "filename": "audio.m4a",
      "progress": "正在轉錄音訊..."
    }
  ],
  "all_tasks": [...]
}
```

#### GET /transcripts

列出所有已保存的轉錄文字檔

**回傳範例：**
```json
{
  "total": 5,
  "output_dir": "output",
  "transcripts": [
    {
      "filename": "audio_20241111_143025_transcript.txt",
      "size_kb": 12.5,
      "created": "2024-11-11 14:30:25",
      "path": "output/audio_20241111_143025_transcript.txt"
    }
  ]
}
```

## 使用範例

### 範例 1：使用 curl 提交轉錄任務

```bash
# 1. 提交任務
curl -X POST http://localhost:8000/transcribe \
  -F "file=@data/audio.m4a" \
  -F "punct_provider=gemini"

# 回傳：
# {
#   "task_id": "abc-123",
#   "status": "pending",
#   ...
# }

# 2. 查詢狀態（每 5 秒查一次）
watch -n 5 curl -s http://localhost:8000/transcribe/abc-123

# 3. 下載結果
curl http://localhost:8000/transcribe/abc-123/download -o transcript.txt

# 4. 查看目前進行中的任務
curl http://localhost:8000/transcribe/active/list
```

### 範例 2：Python 腳本自動輪詢

```python
import requests
import time

# 1. 上傳音檔
with open('data/audio.m4a', 'rb') as f:
    response = requests.post('http://localhost:8000/transcribe',
                            files={'file': f})
    task_id = response.json()['task_id']
    print(f"任務 ID: {task_id}")

# 2. 輪詢狀態
while True:
    status_response = requests.get(f'http://localhost:8000/transcribe/{task_id}')
    task = status_response.json()

    print(f"狀態: {task['status']} - {task['progress']}")

    if task['status'] == 'completed':
        print("轉錄完成！")
        break
    elif task['status'] == 'failed':
        print(f"轉錄失敗：{task.get('error')}")
        break

    time.sleep(5)  # 每 5 秒查詢一次

# 3. 下載結果
if task['status'] == 'completed':
    download_response = requests.get(f'http://localhost:8000/transcribe/{task_id}/download')
    with open('transcript.txt', 'wb') as f:
        f.write(download_response.content)
    print("已下載到 transcript.txt")
```

### 範例 3：前端 JavaScript（適合 React/Vue）

```javascript
async function transcribeAudio(audioFile) {
  // 1. 提交任務
  const formData = new FormData();
  formData.append('file', audioFile);
  formData.append('punct_provider', 'gemini');

  const response = await fetch('http://localhost:8000/transcribe', {
    method: 'POST',
    body: formData
  });
  const { task_id } = await response.json();

  // 2. 輪詢狀態
  return new Promise((resolve, reject) => {
    const interval = setInterval(async () => {
      const statusRes = await fetch(`http://localhost:8000/transcribe/${task_id}`);
      const task = await statusRes.json();

      // 更新 UI 進度
      updateProgress(task.progress);

      if (task.status === 'completed') {
        clearInterval(interval);
        resolve(task_id);
      } else if (task.status === 'failed') {
        clearInterval(interval);
        reject(new Error(task.error));
      }
    }, 5000);  // 每 5 秒查詢
  });
}

// 使用範例
const task_id = await transcribeAudio(selectedFile);
window.location = `http://localhost:8000/transcribe/${task_id}/download`;
```

## 常見問題

### Q: 支援哪些音訊格式？
A: 支援所有 FFmpeg 可處理的格式，包括 m4a, mp3, wav, mp4, flac 等。

### Q: 哪個 Whisper 模型最好？
A: `medium` 模型提供良好的準確度與速度平衡。若需最高準確度選 `large-v2`，若需快速處理選 `small`。

### Q: 標點符號服務選哪個？
A: Google Gemini 速度較快且成本較低，OpenAI GPT 品質稍好但較貴。兩者都能提供良好結果。

### Q: 如何處理長音檔？
A: 啟用 `chunk_audio=true` 參數，系統會自動偵測靜音點並分段處理。

### Q: 轉錄時其他 API 還能用嗎？
A: **可以！** v2.0 採用異步架構，轉錄在背景線程執行，不會阻塞 `/health`、`/transcripts` 等其他端點。

### Q: 可以同時轉錄多個檔案嗎？
A: 目前並發數限制為 1，超過的請求會自動排隊。可修改 `executor = ThreadPoolExecutor(max_workers=1)` 增加並發數（需注意記憶體）。

### Q: 任務記錄會永久保存嗎？
A: 任務狀態儲存在記憶體中，重啟伺服器會清空。文字檔會永久保存在 `output/` 目錄。\

## 開發指南

### 安裝開發依賴

```bash
pip install -r requirements.txt
```

### 執行測試

```bash
# 測試伺服器
python src/whisper_server.py --model small

# 測試 API（使用 curl）
curl -X POST http://localhost:8000/transcribe -F "file=@data/test.m4a"

# 或使用前端界面上傳測試檔案
```

### 程式碼風格

- 遵循 PEP 8 規範
- 使用有意義的變數名稱
- 添加適當的註解與文檔字串

## 授權

[請在此添加您的授權資訊]

## 貢獻

歡迎提交 Issue 和 Pull Request！

## 作者

[請在此添加作者資訊]

## 更新日誌

### v2.1.0 (2025-01-19)
- 🔧 **效能優化**：調整 Whisper 模型並行配置
  - `cpu_threads=1, num_workers=4`：優化核心使用效率
  - 避免與 Speaker Diarization 的資源競爭
  - 在 8 核 M1 Mac 上達到最佳平衡
- 🎤 **Speaker Diarization 增強**：
  - 使用獨立進程執行，可被立即終止
  - 支援取消正在執行的說話者辨識
  - 新增 `diarization_status` 即時狀態追蹤
  - 顯示識別到的講者人數和耗時
- 📊 **前端改進**：
  - 在任務卡片中顯示 Diarization 狀態
  - 支援取消時立即停止所有進程
  - 更詳細的進度資訊
- ⚡ **資源管理**：
  - 模型權重共享，不會隨並行數倍增
  - 優化內存使用（~2.7 GB 總內存）
  - 更好的背景執行管理腳本

**重新部署後端以應用優化：**
```bash
./restart_backend.sh
```

### v1.0.0 (2024-11-11)
- 初始版本發布
- 支援中文語音轉錄
- 整合 Gemini 和 OpenAI 標點服務
- 提供 Docker 部署方案
- 新增文稿精煉功能
