# 快速啟動指南

## 🚀 一鍵啟動（推薦）

### 1. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 填入您的 API 金鑰
```

`.env` 內容：
```
GOOGLE_API_KEY=your_google_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
```

### 2. 啟動所有服務

```bash
docker-compose up -d
```

### 3. 訪問應用

- **前端介面**：http://localhost:3000
- **後端 API**：http://localhost:8000
- **API 文檔**：http://localhost:8000/docs

就是這麼簡單！🎉

## 📱 使用前端介面

1. 打開瀏覽器訪問 http://localhost:3000
2. 拖曳音訊檔案到上傳區域（或點擊選擇檔案）
3. 等待轉錄完成（會自動更新進度）
4. 點擊「下載」按鈕獲取文字檔

### 支援的檔案格式

- M4A
- MP3
- WAV
- MP4
- 其他 FFmpeg 支援的音訊格式

## 🔧 常用命令

### 查看日誌

```bash
# 所有服務
docker-compose logs -f

# 只看後端
docker-compose logs -f whisper-server

# 只看前端
docker-compose logs -f frontend
```

### 停止服務

```bash
docker-compose down
```

### 重新構建

```bash
docker-compose up -d --build
```

### 查看服務狀態

```bash
docker-compose ps
```

## 🧪 測試 API（可選）

### 使用 curl

```bash
# 1. 檢查健康狀態
curl http://localhost:8000/health

# 2. 提交轉錄任務
curl -X POST http://localhost:8000/transcribe \
  -F "file=@data/your-audio.m4a" \
  -F "punct_provider=gemini"

# 3. 查詢任務狀態（替換 YOUR_TASK_ID）
curl http://localhost:8000/transcribe/YOUR_TASK_ID

# 4. 下載結果
curl http://localhost:8000/transcribe/YOUR_TASK_ID/download -o transcript.txt
```

## 💡 使用技巧

### 1. 選擇合適的模型

在 `docker-compose.yml` 中修改：

```yaml
whisper-server:
  command: python src/whisper_server.py --model small  # 更快，但準確度較低
  # 或
  command: python src/whisper_server.py --model large-v2  # 最準確，但較慢
```

### 2. 調整並發數

編輯 `src/whisper_server.py`：

```python
executor = ThreadPoolExecutor(max_workers=2)  # 改為 2 可同時處理 2 個任務
```

注意：增加並發數會增加記憶體使用。

### 3. 本地開發（不使用 Docker）

#### 後端：

```bash
pip install -r requirements.txt
python src/whisper_server.py --model small
```

#### 前端：

```bash
cd frontend
npm install
npm run dev
```

## 🐛 疑難排解

### 問題：前端無法連接後端

**解決方法：**
1. 確認後端服務運行：`curl http://localhost:8000/health`
2. 檢查 Docker 網路：`docker network ls`
3. 查看後端日誌：`docker-compose logs whisper-server`

### 問題：記憶體不足

**解決方法：**
1. 使用較小的模型（small 或 base）
2. 調整 docker-compose.yml 中的記憶體限制
3. 確保 Docker 分配足夠記憶體（建議 8GB+）

### 問題：首次啟動很慢

**原因：**
首次啟動需要下載 Whisper 模型（約 1.5GB）。

**解決方法：**
等待模型下載完成，之後會快取在 Docker volume 中。

### 問題：轉錄失敗

**檢查清單：**
1. ✅ .env 檔案是否設定正確
2. ✅ GOOGLE_API_KEY 是否有效
3. ✅ 音訊檔案格式是否支援
4. ✅ 查看任務詳情中的錯誤訊息

## 📊 資源使用

### 最低需求

- CPU: 2 核心
- RAM: 4GB
- 磁碟: 5GB

### 建議配置

- CPU: 4 核心
- RAM: 8GB
- 磁碟: 10GB

## 🎯 下一步

- 閱讀 [README.md](README.md) 了解完整功能
- 查看 [API 文檔](http://localhost:8000/docs) 了解 API 詳情
- 閱讀 [frontend/README.md](frontend/README.md) 了解前端開發

祝使用愉快！ 🎉
