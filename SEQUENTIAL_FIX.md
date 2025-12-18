# 最終解決方案：循序處理 Chunks

## 問題根源

**巢狀 ThreadPoolExecutor 導致死鎖**：

```python
# 外層 executor (max_workers=5)
executor = ThreadPoolExecutor(max_workers=5)
loop.run_in_executor(executor, process_transcription_task, ...)

# 內層 executor (max_workers=2-4) - 在 process_transcription_task 內部創建
def transcribe_audio_in_chunks(...):
    with ThreadPoolExecutor(max_workers=transcribe_workers) as executor:  # ❌ 巢狀！
        for future in as_completed(...):
            result = future.result()  # 阻塞等待
```

**死鎖流程**：

1. 外層 executor 的 worker 執行 `process_transcription_task`（佔用 1 個 worker）
2. 內層 executor 創建並提交 2-4 個 chunk 任務
3. 主線程在 `future.result()` 等待 chunks 完成
4. Chunk workers 執行時可能更新狀態、取得鎖等
5. FastAPI 的 async event loop 嘗試處理 HTTP 輪詢請求
6. **線程資源耗盡/競爭 → 死鎖**

## 解決方案：移除巢狀 Executor

### 修改：改用循序處理

**檔案**: `src/whisper_server.py:1119-1162`

```python
# ✅ 循序處理每個 chunk，避免巢狀 executor
detected_language = None
for chunk_idx, start_ms, end_ms, temp_path in chunk_info_list:
    if task_id and task_cancelled.get(task_id, False):
        raise RuntimeError("任務已被使用者取消")

    time_offset_seconds = start_ms / 1000.0

    # 轉錄此 chunk（循序，一次一個）
    print(f"   🔄 正在轉錄第 {chunk_idx}/{num_chunks} 段...")
    text, segments, lang = transcribe_single_chunk(
        whisper_model, temp_path, language, task_id,
        chunk_idx, time_offset_seconds, True
    )

    # 記錄語言、儲存結果
    if detected_language is None and lang:
        detected_language = lang
    chunks_text[chunk_idx - 1] = text
    all_segments.extend(segments if segments else [])

    # 更新進度（不阻塞）
    update_task_status(task_id, {
        "progress": f"正在轉錄音訊... ({chunk_idx}/{num_chunks} 段完成)",
        "completed_chunks": chunk_idx
    }, persist_to_db=False)
```

**優點**：
- ✅ 沒有巢狀 executor - 避免線程競爭
- ✅ 沒有 `future.result()` 阻塞 - worker 線程保持活躍
- ✅ FastAPI 可以正常處理輪詢請求
- ✅ 狀態更新使用非阻塞式 DB 寫入

**缺點**：
- ⚠️ 處理速度較慢（循序而非並行）
- 對於 43 分鐘音檔切分為 5 段，循序處理時間約為並行的 2-5 倍

## 效果對比

### 之前（巢狀 executor + 並行）

```
外層 worker 1: process_transcription_task
  └─ 創建內層 executor (2-4 workers)
     ├─ chunk worker 1: transcribe → update_status
     ├─ chunk worker 2: transcribe → update_status
     └─ 主線程: future.result() ← 阻塞等待

FastAPI event loop: 輪詢請求 → 無可用資源 → 超時！❌
```

### 現在（無巢狀 + 循序）

```
外層 worker 1: process_transcription_task
  └─ for loop: chunk 1 → chunk 2 → chunk 3 → ...
     每個 chunk: transcribe → update_status (非阻塞) → 繼續

FastAPI event loop: 輪詢請求 → 從記憶體讀取 → 立即返回 ✅
```

## 測試

後端已重啟（PID: 28209），現在測試 67MB 音檔：

### 預期日誌

```
🚀 開始循序轉錄（共 5 段）...  ← "循序" 而非 "並行"
   🔄 正在轉錄第 1/5 段...
⚡ [task_id] 從記憶體返回（零 DB 查詢）  ← 輪詢成功！
💾 [task_id] 持久化到 MongoDB (非阻塞): ...
   🔄 正在轉錄第 2/5 段...
⚡ [task_id] 從記憶體返回（零 DB 查詢）  ← 持續成功！
...
```

### 關鍵指標

- ✅ **前端輪詢不應超時** - 這是最重要的
- ✅ **後端可以持續回應** - CPU 不會卡在 0%
- ⚠️ **轉錄時間會較長** - 但至少能完成

## 後續優化方案

如果循序處理太慢，可以考慮：

### 方案 1：使用全域 executor（推薦）

```python
# 不創建新 executor，使用全域的
global executor  # max_workers=5

# 提交 chunks 到全域 executor
futures = [executor.submit(transcribe_single_chunk, ...) for chunk in chunks]

# 但要確保不會佔滿所有 workers
# 例如限制最多同時 2-3 個 chunks
```

### 方案 2：使用 ProcessPoolExecutor

```python
# 使用進程而非線程，避免 GIL 問題
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor(max_workers=2) as executor:
    # 進程間不共享 GIL，不會影響 FastAPI
```

### 方案 3：增加 Uvicorn workers

```bash
# 啟動時增加 workers
uvicorn whisper_server:app --workers 4
```

## 總結

**循序處理是最安全的臨時方案**，確保系統穩定運作。等確認不再超時後，可以再優化並行處理的實作方式。

**核心修改**：
1. ✅ 移除巢狀 ThreadPoolExecutor
2. ✅ 改用簡單的 for loop 循序處理
3. ✅ 保持非阻塞式 DB 更新
4. ✅ 保持零 DB 查詢的輪詢機制

**現在應該不會再超時了！** 🎉
