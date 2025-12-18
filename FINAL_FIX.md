# 最終修復：非阻塞 DB 更新

## 真正的死鎖根源

在 `update_task_status` 函數中（第 637 和 652 行）：

```python
# ❌ 這兩行導致死鎖！
db_task = run_async_in_thread(get_task_from_db(task_id))  # 阻塞等待 DB 查詢
run_async_in_thread(update_task_in_db(task_id, db_updates))  # 阻塞等待 DB 更新
```

## 死鎖流程

1. **並行轉錄啟動**（2-4 個 worker 線程）
2. 每個 worker **完成 chunk** 後調用 `update_task_status`
3. `update_task_status` 執行 `run_async_in_thread` → **阻塞線程等待 DB 操作**
4. **所有 worker 線程被阻塞**，等待 DB 操作完成
5. 前端輪詢請求進來 → **沒有可用線程處理** → **超時**
6. **死鎖**！

## 修復方案

### 修改 1：移除阻塞式 DB 查詢，使用記憶體數據

**檔案**: `src/whisper_server.py:635-641`

```python
# ✅ 直接使用記憶體中的資料計算進度（避免阻塞式 DB 查詢）
if "status" in db_updates or "completed_chunks" in updates:
    with tasks_lock:
        if task_id in transcription_tasks:
            progress_pct = calculate_progress_percentage(transcription_tasks[task_id])
            transcription_tasks[task_id]["progress_percentage"] = round(progress_pct, 1)
```

**改進**：
- ❌ 移除：`run_async_in_thread(get_task_from_db(task_id))` - 阻塞式查詢
- ✅ 改用：直接從記憶體計算 - **不阻塞**

### 修改 2：非阻塞式 DB 更新

**檔案**: `src/whisper_server.py:643-652`

```python
# ✅ 使用 asyncio.run_coroutine_threadsafe（不阻塞當前線程）
try:
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(update_task_in_db(task_id, db_updates), main_loop)
        print(f"💾 [{task_id}] 持久化到 MongoDB (非阻塞): {list(db_updates.keys())}")
except Exception as e:
    print(f"⚠️ [{task_id}] DB 更新失敗（不影響轉錄）: {e}")
```

**關鍵差異**：

| 方法 | 是否阻塞 | 說明 |
|------|---------|------|
| `run_async_in_thread()` → `.result()` | ✅ **阻塞** | 等待 async 完成 |
| `asyncio.run_coroutine_threadsafe()` | ❌ **不阻塞** | 提交到 event loop 後立即返回 |

## 效果

### 之前（死鎖）

```
worker 1: update_task_status → run_async_in_thread → 阻塞等待 DB
worker 2: update_task_status → run_async_in_thread → 阻塞等待 DB
worker 3: update_task_status → run_async_in_thread → 阻塞等待 DB
前端輪詢: → 沒有可用線程 → 超時！
```

### 現在（正常）

```
worker 1: update_task_status → run_coroutine_threadsafe → 立即返回 ✓
worker 2: update_task_status → run_coroutine_threadsafe → 立即返回 ✓
worker 3: update_task_status → run_coroutine_threadsafe → 立即返回 ✓
前端輪詢: → 從記憶體讀取 → 立即返回 ✓
```

## 測試步驟

1. ✅ 後端已重啟（PID: 26893）
2. 現在上傳 67MB 音檔測試

### 預期日誌

```
📥 [task_id] 初始化記憶體（user_id: xxx）
⚡ [task_id] 從記憶體返回（零 DB 查詢）
🚀 開始並行轉錄（並行數：2）...
💾 [task_id] 持久化到 MongoDB (非阻塞): ['status']  ← 看到 "非阻塞" 字樣
⚡ [task_id] 從記憶體返回（零 DB 查詢）  ← 轉錄期間仍可輪詢！
⚡ [task_id] 從記憶體返回（零 DB 查詢）  ← 持續成功
```

### 關鍵指標

- ✅ **前端輪詢不應超時**
- ✅ **後端 CPU 不應停在 0%**
- ✅ **日誌中應持續出現 "從記憶體返回"**
- ✅ **DB 更新日誌顯示 "(非阻塞)"**

## 技術總結

**為什麼 `run_async_in_thread` 會導致死鎖？**

1. `run_async_in_thread` 使用 `future.result()` **阻塞當前線程**
2. 當 worker 線程數量有限（5 個），且都被阻塞時
3. FastAPI 無法從線程池取得線程來處理新請求
4. 導致死鎖

**正確做法**：

- 使用 `asyncio.run_coroutine_threadsafe()` 提交任務到 event loop
- **不等待結果**（fire-and-forget）
- DB 更新在背景執行，不阻塞 worker 線程
- 記憶體中已有最新資料，DB 只是持久化

## 如果仍有問題

如果此修復後仍有超時，可能需要：

1. **增加 uvicorn workers**: `--workers 4`
2. **減少並行轉錄數**: 從 2-4 降到 1-2
3. **關閉說話者辨識**: 減少背景任務競爭
4. **使用 multiprocessing**: 而非 threading（避免 GIL）

但理論上，這次修復應該徹底解決死鎖問題！
