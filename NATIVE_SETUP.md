# Plan B: 原生後端 + Docker 前端部署指南

本指南說明如何在 macOS (M1/M2) 上以原生方式運行後端，以獲得最佳性能。

## 為什麼選擇原生運行？

在 M1/M2 Mac 上，Docker 需要通過虛擬化層運行，這會導致：
- faster-whisper 的 M1 優化無法生效
- Apple Neural Engine 無法被訪問
- INT8 量化效果降低
- **預期性能損失：3-5x**

原生運行可以直接使用 M1 芯片的所有優化，預期速度提升 **4-6x**。

## 架構說明

- **後端（Whisper API）**：原生運行在 macOS 上（localhost:8000）
- **前端（Web UI）**：Docker 容器運行（localhost:3000）

## 快速開始

### 1. 停止舊的 Docker 容器（如果有）

```bash
docker-compose down
```

### 2. 設置原生後端環境

```bash
# 創建虛擬環境並安裝依賴
bash setup_native_backend.sh
```

這會：
- 創建 Python 虛擬環境（venv/）
- 安裝所有依賴（faster-whisper、FastAPI 等）
- 創建必要的目錄（output/、temp/）

### 3. 配置 API Keys

確保 `.env` 文件已配置：

```bash
# 如果沒有 .env，從範例複製
cp .env.example .env

# 編輯 .env 填入你的 API keys
nano .env
```

### 4. 啟動後端（原生）

有兩種運行方式：

#### 方式 A：守護進程模式（推薦）

**關閉終端後服務繼續運行**

```bash
# 啟動服務
bash start_backend_daemon.sh

# 查看狀態
bash status_backend.sh

# 查看日誌（實時）
tail -f backend.log

# 停止服務
bash stop_backend.sh

# 重啟服務
bash restart_backend.sh
```

#### 方式 B：前台運行模式

**適合開發調試，關閉終端後服務停止**

```bash
bash run_native_backend.sh
# 按 Ctrl+C 停止
```

**首次運行**：faster-whisper 會下載並轉換模型，需要 40-60 秒。

### 5. 啟動前端（Docker）

在第二個終端運行：

```bash
docker-compose -f docker-compose.frontend-only.yml up
```

或者使用背景運行：

```bash
docker-compose -f docker-compose.frontend-only.yml up -d
```

### 6. 訪問 Web 界面

打開瀏覽器訪問：
```
http://localhost:3000
```

## 性能對比

### Docker 方式（舊）
- 10 分鐘音檔 → 轉錄 13.8 分鐘
- 140 MB / 82 分鐘音檔 → 轉錄 82.5 分鐘
- **加速比**：1.21x（相對於單線程）

### 原生方式（Plan B）
- 預期加速比：**4-6x**（相對於單線程）
- 預期 10 分鐘音檔 → 轉錄 **2-3 分鐘**
- 預期 140 MB / 82 分鐘音檔 → 轉錄 **14-20 分鐘**

## 常見問題

### Q: 如何停止服務？

**後端**：在運行 `run_native_backend.sh` 的終端按 `Ctrl+C`

**前端**：
```bash
docker-compose -f docker-compose.frontend-only.yml down
```

### Q: 如何查看後端日誌？

後端日誌會直接顯示在運行 `run_native_backend.sh` 的終端中。

### Q: 如何更新代碼？

**更新後端**：
```bash
# 停止後端（Ctrl+C）
git pull
source venv/bin/activate
pip install -r requirements.txt
bash run_native_backend.sh
```

**更新前端**：
```bash
docker-compose -f docker-compose.frontend-only.yml down
docker-compose -f docker-compose.frontend-only.yml build
docker-compose -f docker-compose.frontend-only.yml up -d
```

### Q: 如何切換回完全 Docker 模式？

```bash
# 停止 Plan B
docker-compose -f docker-compose.frontend-only.yml down
# 停止原生後端（Ctrl+C）

# 啟動完整 Docker
docker-compose up -d
```

### Q: 虛擬環境在哪裡？

虛擬環境位於項目根目錄的 `venv/` 文件夾。已在 `.gitignore` 中排除。

## 文件結構

```
transcriber/
├── setup_native_backend.sh        # 環境設置腳本
├── run_native_backend.sh          # 後端啟動腳本
├── docker-compose.frontend-only.yml  # 僅前端 Docker 配置
├── venv/                          # Python 虛擬環境（自動創建）
├── output/                        # 轉錄輸出（持久化）
├── temp/                          # 臨時文件
└── src/
    └── whisper_server.py          # 後端主程序
```

## 故障排除

### 錯誤：找不到 .env 文件

```bash
cp .env.example .env
# 然後編輯 .env 填入 API keys
```

### 錯誤：ModuleNotFoundError

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 前端 502 錯誤

1. 確保後端正在運行（http://localhost:8000）
2. 檢查後端終端是否有錯誤
3. 等待模型下載完成（首次運行需要 40-60 秒）

### 性能仍然很慢

1. 確認後端是原生運行（不是 Docker）
2. 檢查 `whisper_server.py` 中的 `max_workers=4`
3. 查看後端日誌確認並行轉錄已啟動：
   ```
   🚀 開始並行轉錄（並行數：4）...
   ```

## 進階配置

### 調整並行數

編輯 `src/whisper_server.py`，找到 `max_workers` 參數：

```python
# 約在第 284 行
with ThreadPoolExecutor(max_workers=4) as executor:
```

M1/M2 建議值：
- M1 (8 核心): `max_workers=4`
- M1 Pro (10 核心): `max_workers=5`
- M1 Max (10 核心): `max_workers=6`

### 切換模型

編輯 `src/whisper_server.py`，修改 `DEFAULT_MODEL`：

```python
# 約在第 28 行
DEFAULT_MODEL = "medium"  # 選項：tiny, base, small, medium, large-v2, large-v3
```

模型大小與性能權衡：
- `tiny`: 最快，準確度最低
- `base`: 快速，準確度低
- `small`: 平衡
- `medium`: 較慢，準確度高（當前使用）
- `large-v3`: 最慢，準確度最高

## 備份和遷移

### 備份任務歷史

任務歷史保存在：
```
output/tasks.json
```

定期備份這個文件以保留轉錄歷史。

### 備份轉錄結果

所有轉錄文本文件保存在：
```
output/*_transcript.txt
```

## 性能監控

查看系統資源使用：

```bash
# CPU 和內存
htop

# 或使用 macOS Activity Monitor
open -a "Activity Monitor"
```

在轉錄過程中，你應該看到：
- 多個 Python 進程並行運行
- CPU 使用率接近 max_workers * 100%
- 內存使用約 4-6GB（medium 模型）
