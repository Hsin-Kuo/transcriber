# Whisper Transcriber Frontend

Vue 3 前端介面，用於 Whisper 轉錄服務。

## 功能特色

- 📤 **拖曳上傳**：支援拖曳檔案或點擊上傳
- 📊 **即時進度**：自動輪詢任務狀態，顯示轉錄進度
- 📋 **任務管理**：查看所有轉錄任務（進行中、已完成、失敗）
- 📥 **一鍵下載**：完成後直接下載轉錄文字檔
- 🎨 **現代化UI**：漂亮的漸層設計，響應式布局

## 技術棧

- Vue 3 (Composition API)
- Vite 5 (構建工具)
- Axios (HTTP 客戶端)
- Nginx (生產環境靜態文件伺服器)

## 開發模式

### 安裝依賴

```bash
cd frontend
npm install
```

### 啟動開發伺服器

```bash
npm run dev
```

前端將在 http://localhost:5173 運行，並自動代理 API 請求到後端。

### 構建生產版本

```bash
npm run build
```

構建產物會輸出到 `dist/` 目錄。

## Docker 部署

### 方式 1：使用 docker-compose（推薦）

```bash
# 在專案根目錄
docker-compose up -d
```

前端：http://localhost:3000
後端 API：http://localhost:8000

### 方式 2：單獨構建前端

```bash
cd frontend
docker build -t whisper-frontend .
docker run -p 3000:3000 whisper-frontend
```

## 配置

### API 端點配置

開發模式下，Vite 會自動代理 `/api` 請求到 `http://whisper-server:8000`（見 `vite.config.js`）。

生產模式下，Nginx 會代理 `/api` 請求到後端服務（見 `nginx.conf`）。

### 環境變數

無需額外環境變數，自動檢測開發/生產環境。

## 項目結構

```
frontend/
├── src/
│   ├── App.vue              # 主組件
│   ├── main.js              # 入口文件
│   ├── style.css            # 全局樣式
│   └── components/
│       ├── UploadZone.vue   # 檔案上傳組件
│       └── TaskList.vue     # 任務列表組件
├── public/                  # 靜態資源
├── index.html               # HTML 模板
├── package.json             # 依賴管理
├── vite.config.js           # Vite 配置
├── Dockerfile               # Docker 映像配置
└── nginx.conf               # Nginx 配置
```

## 使用說明

1. **上傳音訊檔案**：
   - 點擊上傳區域選擇檔案
   - 或直接拖曳檔案到上傳區域
   - 支援格式：m4a, mp3, wav, mp4 等

2. **查看進度**：
   - 上傳後自動獲得任務 ID
   - 系統每 2 秒自動更新任務狀態
   - 進度條顯示當前處理階段

3. **下載結果**：
   - 任務完成後，點擊「下載」按鈕
   - 文字檔會自動下載到本地

4. **任務管理**：
   - 查看所有歷史任務
   - 任務按狀態排序（處理中 > 等待中 > 已完成 > 失敗）
   - 點擊「刷新」手動同步伺服器任務

## 狀態說明

- 🟡 **等待中** (pending)：任務已提交，等待處理
- 🔵 **處理中** (processing)：正在轉錄或添加標點
- 🟢 **已完成** (completed)：轉錄成功，可下載
- 🔴 **失敗** (failed)：轉錄失敗，顯示錯誤訊息

## 疑難排解

### 無法連接後端

檢查後端服務是否運行：
```bash
curl http://localhost:8000/health
```

### CORS 錯誤

確認後端已添加 CORS 中間件（已在 whisper_server.py 中配置）。

### 任務狀態不更新

- 檢查瀏覽器控制台是否有錯誤
- 確認輪詢機制正常運作（每 5 秒請求一次）

## 授權

與主專案相同
