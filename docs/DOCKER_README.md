# Whisper 轉錄服務 - Docker 部署指南

使用 Docker 部署 Whisper 轉錄服務，模型只需載入一次，可重複使用。

## 快速開始

### 1. 設定環境變數

```bash
# 複製範例檔案
cp .env.example .env

# 編輯 .env 檔案，填入你的 API Keys
# GOOGLE_API_KEY=your_google_api_key_here
# OPENAI_API_KEY=your_openai_api_key_here (可選)
```

### 2. 建立並啟動服務

```bash
# 建立 Docker 映像並啟動服務
docker-compose up -d

# 查看日誌（確認模型載入完成）
docker-compose logs -f
```

### 3. 測試服務

```bash
# 方法 1：使用瀏覽器
open http://localhost:8000/docs

# 方法 2：使用客戶端腳本
python3 transcribe_client.py -i your_audio_file.m4a

# 方法 3：使用 curl
curl -X POST "http://localhost:8000/transcribe" \
  -F "file=@your_audio_file.m4a" \
  -F "punct_provider=gemini" \
  -F "chunk_audio=true" \
  -o transcript.txt
```

## Docker 指令

### 管理服務

```bash
# 啟動服務
docker-compose up -d

# 停止服務
docker-compose down

# 重啟服務
docker-compose restart

# 查看日誌
docker-compose logs -f

# 查看服務狀態
docker-compose ps
```

### 重新建立映像

```bash
# 重新建立映像（程式碼更新後）
docker-compose build

# 或直接重新建立並啟動
docker-compose up -d --build
```

### 清理

```bash
# 停止並刪除容器、網路
docker-compose down

# 同時刪除 volumes（模型快取也會被刪除）
docker-compose down -v

# 刪除映像
docker rmi whisper-transcriber
```

## 進階設定

### 修改模型

預設使用 `medium` 模型，如需修改：

```yaml
# 編輯 docker-compose.yml
environment:
  - WHISPER_MODEL=large-v2  # 或 tiny/base/small/medium/large-v2
```

或在 Dockerfile 中修改 CMD：

```dockerfile
CMD ["python", "whisper_server.py", "--model", "large-v2"]
```

### 資源限制

在 `docker-compose.yml` 中調整：

```yaml
deploy:
  resources:
    limits:
      cpus: '4'      # CPU 核心數
      memory: 8G     # 記憶體限制
```

### 掛載本地目錄

如需直接從容器內訪問本地檔案：

```yaml
volumes:
  - ./data_file:/app/data_file:ro  # 唯讀掛載音檔目錄
  - ./output:/app/output           # 輸出目錄
```

## 遠端訪問

### 使用 Tailscale

1. 在主機上安裝 Tailscale
2. 從其他裝置透過 Tailscale IP 訪問服務

```bash
# 查看 Tailscale IP
tailscale ip -4

# 從其他裝置訪問
python3 transcribe_client.py \
  -i audio.m4a \
  --server http://100.64.1.1:8000
```

### 修改綁定端口

編輯 `docker-compose.yml`：

```yaml
ports:
  - "8080:8000"  # 主機端口:容器端口
```

## 效能優化

### 預先下載模型

在 Dockerfile 中取消註解：

```dockerfile
RUN python -c "import whisper; whisper.load_model('medium')"
```

這會在建立映像時就下載模型，但會增加映像大小。

### GPU 支援

如有 NVIDIA GPU，修改 `docker-compose.yml`：

```yaml
services:
  whisper-server:
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
```

需要先安裝 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。

## 故障排除

### 服務無法啟動

```bash
# 查看詳細日誌
docker-compose logs

# 進入容器內部檢查
docker-compose exec whisper-server bash
```

### 模型載入失敗

檢查記憶體是否足夠：

```bash
# 查看容器資源使用
docker stats
```

`medium` 模型需要約 5GB 記憶體。

### API Key 錯誤

確認 `.env` 檔案格式正確，且 docker-compose 已重啟：

```bash
docker-compose down
docker-compose up -d
```

## API 端點

- `GET /` - 服務狀態
- `GET /health` - 健康檢查
- `POST /transcribe` - 上傳音檔進行轉錄
- `GET /docs` - 互動式 API 文檔（Swagger UI）

## 架構說明

```
客戶端 → Docker Container → Whisper 模型（常駐記憶體）
                           ↓
                        Gemini/OpenAI API
                           ↓
                        轉錄結果
```

## 注意事項

1. **首次啟動較慢**：需要下載 Whisper 模型（約 1.5GB for medium）
2. **記憶體需求**：medium 模型約需 5GB 記憶體
3. **API Key**：使用標點功能需要設定 GOOGLE_API_KEY 或 OPENAI_API_KEY
4. **持久化**：模型快取保存在 Docker volume 中，重啟不會重新下載

## 相關檔案

- `Dockerfile` - Docker 映像定義
- `docker-compose.yml` - 服務編排
- `.dockerignore` - Docker 建立時忽略的檔案
- `.env` - 環境變數（API Keys）
- `whisper_server.py` - FastAPI 服務端
- `transcribe_client.py` - 客戶端腳本
