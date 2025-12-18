# GIL 問題：根本性架構限制

## 問題根源

**Python 的 GIL (Global Interpreter Lock)** 是根本原因：

### 當前架構

```
同一個 Python 進程：
├─ FastAPI (async event loop) ← 需要 GIL 處理 HTTP 請求
└─ ThreadPoolExecutor
   └─ process_transcription_task
      └─ transcribe_single_chunk
         └─ model.transcribe()  ← CPU 密集，長時間佔用 GIL（數分鐘）
```

### GIL 如何導致超時

1. Whisper 模型在 executor 線程中執行 `model.transcribe()`
2. 這是 **CPU 密集運算**（深度學習推理），持續佔用 GIL
3. FastAPI 的 async event loop 需要 GIL 來處理 HTTP 請求
4. **GIL 被 Whisper 佔用 → Event loop 無法獲得 GIL → HTTP 請求超時**

### 測試結果總結

| 嘗試的修復 | 結果 | 原因 |
|-----------|------|------|
| 增加 executor workers | ❌ 仍超時 | GIL 仍被佔用 |
| 移除巢狀 ThreadPoolExecutor | ❌ 仍超時 | GIL 問題不變 |
| 非阻塞式 DB 更新 | ❌ 仍超時 | GIL 才是瓶頸 |
| 循序處理 chunks | ❌ 仍超時 | 只要轉錄就佔 GIL |
| 關閉說話者辨識 | ❌ 仍超時 | Whisper 本身就佔 GIL |
| 移除所有阻塞式 DB 查詢 | ❌ 仍超時 | `model.transcribe()` 無法避免 |

## 為什麼之前的版本（main branch）能用？

需要對比 main branch 的實作方式，看是否有不同的架構設計。可能：

1. Main branch 沒有使用 MongoDB（減少了一些操作）
2. Main branch 的輪詢機制不同
3. Main branch 使用了不同的並發模型
4. 或者 main branch 也有同樣問題，只是沒被發現

## 真正的解決方案

### 方案 1：使用 ProcessPoolExecutor（推薦）

```python
from concurrent.futures import ProcessPoolExecutor

# 進程不共享 GIL！
executor = ProcessPoolExecutor(max_workers=2)
```

**優點**：
- ✅ 進程間不共享 GIL
- ✅ FastAPI 可以正常處理請求
- ✅ 真正的並行處理

**挑戰**：
- ⚠️ 需要序列化所有參數（Whisper 模型、任務數據）
- ⚠️ 不能共享記憶體字典（需要使用 Manager 或 Redis）
- ⚠️ 需要重構 `process_transcription_task` 函數
- ⚠️ 每個進程需要獨立載入模型（記憶體佔用增加）

### 方案 2：使用 Celery 任務隊列

```python
# 將轉錄任務放到 Celery worker
@celery.task
def transcribe_task(task_id, audio_path, ...):
    # 在獨立進程中執行
    ...
```

**優點**：
- ✅ 完全分離轉錄和 API 服務
- ✅ 可以水平擴展 workers
- ✅ 內建任務重試、監控

**挑戰**：
- ⚠️ 需要引入 Redis/RabbitMQ
- ⚠️ 架構變複雜
- ⚠️ 需要重構整個轉錄流程

### 方案 3：獨立轉錄服務

```
API 服務 (FastAPI) ← 處理 HTTP 請求
    ↓ HTTP/gRPC
轉錄服務 (獨立進程) ← 專門處理轉錄
```

**優點**：
- ✅ 完全隔離，不互相影響
- ✅ 可以用不同語言/技術實作
- ✅ 易於部署和擴展

**挑戰**：
- ⚠️ 需要設計服務間通訊
- ⚠️ 部署複雜度增加

### 方案 4：增加 Uvicorn Workers（部分緩解）

```bash
uvicorn whisper_server:app --workers 4
```

**優點**：
- ✅ 簡單，只需改啟動參數
- ✅ 多個進程可以分擔請求

**缺點**：
- ⚠️ **無法完全解決 GIL 問題**
- ⚠️ 每個 worker 仍然會在轉錄時無法回應
- ⚠️ 記憶體佔用倍增（每個 worker 載入模型）

## 臨時緩解方案（trade-off）

如果無法立即重構，可以考慮：

### 選項 A：接受較長的輪詢超時

```typescript
// frontend
const response = await api.get(`/transcribe/${task.task_id}`, {
  timeout: 120000  // 增加到 2 分鐘
})
```

**說明**：等 Whisper 完成一個 chunk 後再回應

**缺點**：前端體驗差，看起來像卡住

### 選項 B：使用 WebSocket

```python
# 建立 WebSocket 連接，推送進度
@app.websocket("/ws/task/{task_id}")
async def task_progress(websocket: WebSocket, task_id: str):
    while task.status in ["pending", "processing"]:
        await websocket.send_json(task_status)
        await asyncio.sleep(2)
```

**優點**：Server-push，不需要輪詢

**缺點**：仍然無法解決 GIL 問題，WebSocket 也會卡

### 選項 C：降級為純後台任務

```python
# 不支援即時進度，完成後通知
POST /transcribe → 返回 task_id
GET /transcribe/{task_id} → "processing" (無詳細進度)
完成後 → Webhook 或 Email 通知
```

**優點**：不需要輪詢

**缺點**：無法看到即時進度

## 建議的行動方案

### 短期（1-2 天）

1. **對比 main branch**：看之前如何處理這個問題
2. **增加 Uvicorn workers**：至少讓部分請求能回應
3. **調整前端超時**：臨時緩解體驗問題

### 中期（1-2 週）

1. **實作 ProcessPoolExecutor**：
   - 重構 `process_transcription_task` 為可序列化函數
   - 使用 Redis 或 multiprocessing.Manager 共享狀態
   - 每個進程獨立載入模型

### 長期（1-2 月）

1. **引入 Celery**：
   - 完整的任務隊列系統
   - 獨立 worker 進程
   - 支援分散式部署

## 總結

**目前的架構（ThreadPoolExecutor + FastAPI）根本上無法避免 GIL 導致的超時問題。**

唯一真正的解決方案是：**將 CPU 密集的轉錄工作放到獨立的進程中**（ProcessPoolExecutor、Celery 或獨立服務）。

其他所有優化（移除阻塞、優化查詢等）都只是減少問題的嚴重程度，無法從根本上解決。
