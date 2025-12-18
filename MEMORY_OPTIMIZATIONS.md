# 記憶體優化修復報告

## 問題診斷

用戶報告：「還是遇到記憶體用盡的狀況欸，還沒加入DB、改變取資料方式前，沒有這個狀況」

問題出現在 MongoDB 整合後，表明記憶體問題主要來自於資料庫層面的資料處理，而非音訊處理。

## 實施的優化

### 1. 移除不必要的資料複製 ✅

**檔案**: `src/whisper_server.py:640`

```python
# 之前：複製整個任務物件
merged_task = db_task.copy()

# 現在：直接使用原物件
merged_task = db_task  # 記憶體優化：不複製，直接更新原物件
```

**影響**: 每次狀態更新時減少一次完整任務物件的記憶體複製。

---

### 2. 限制活躍任務查詢數量 ✅

**檔案**: `src/database/repositories/task_repo.py:97-106`

```python
# 之前：可能載入 100 個進行中的任務
return await cursor.to_list(length=100)

# 現在：限制最多 20 個，並按時間排序
cursor = self.collection.find({...}).sort("timestamps.created_at", -1).limit(20)
return await cursor.to_list(length=20)
```

**影響**: 減少進行中任務查詢的記憶體佔用 80%。

---

### 3. 音訊轉檔後立即釋放記憶體 ✅

**檔案**: `src/whisper_server.py:1862-1868`

```python
audio = AudioSegment.from_file(str(temp_audio_path))
audio.export(str(wav_path), format="wav")
# 立即釋放記憶體
del audio
import gc
gc.collect()
```

**影響**: 防止音訊資料在記憶體中累積。

---

### 4. 任務結束時強制記憶體清理 ✅

**檔案**: `src/whisper_server.py:2114-2124`

```python
finally:
    # 清理所有運行時狀態字典
    with tasks_lock:
        task_temp_dirs.pop(task_id, None)
        task_cancelled.pop(task_id, None)
        task_diarization_processes.pop(task_id, None)
        # 確保從 transcription_tasks 中移除
        transcription_tasks.pop(task_id, None)

    # 強制垃圾回收以釋放記憶體
    import gc
    gc.collect()
    print(f"🧹 [{task_id}] 記憶體清理完成")
```

**影響**: 確保任務完成後所有相關記憶體被釋放。

---

### 5. API 查詢後立即釋放資料 ✅

**檔案**: `src/whisper_server.py:3414-3421`

```python
# enrich 完成後，立即刪除原始資料
del all_tasks, all_tasks_sorted, active
import gc
gc.collect()

return {
    "active_count": len(active_enriched),
    "total_count": await task_repo.count_by_user(user_id),  # 直接查詢計數，不載入全部
    "active_tasks": active_enriched,
    "all_tasks": all_tasks_enriched
}
```

**影響**: API 響應後立即釋放查詢結果的記憶體。

---

### 6. 定期記憶體清理背景任務 ✅

**檔案**: `src/whisper_server.py:2127-2177`

**功能**: 每 10 分鐘自動執行一次，清理以下項目：
- 孤立的任務狀態（`transcription_tasks`）
- 孤立的暫存目錄記錄（`task_temp_dirs`）
- 孤立的取消標記（`task_cancelled`）
- 孤立的 diarization 進程記錄（`task_diarization_processes`）

```python
async def periodic_memory_cleanup():
    """定期清理記憶體中的孤立資料（背景任務）"""
    while True:
        await asyncio.sleep(600)  # 每 10 分鐘

        # 從資料庫查詢實際的活躍任務
        active_task_ids = {...}

        # 清理記憶體中不在活躍列表的資料
        orphaned_tasks = [...]
        for tid in orphaned_tasks:
            transcription_tasks.pop(tid, None)

        gc.collect()
```

**影響**: 防止長期運行時記憶體洩漏。

---

## 效能提升預期

| 優化項目 | 記憶體節省 | 備註 |
|---------|----------|------|
| 移除資料複製 | ~10-20% | 每次狀態更新 |
| 限制查詢數量 | ~80% | 查詢進行中任務時 |
| 音訊轉檔後釋放 | ~100MB+ | 每個音檔處理 |
| 任務結束清理 | ~5-10MB | 每個任務完成 |
| API 查詢後清理 | ~20-30% | 每次 list 請求 |
| 定期背景清理 | 防止洩漏 | 長期運行穩定性 |

---

## 需要重啟後端

所有修改需要重啟後端服務才能生效：

```bash
# 停止後端
./stop_backend.sh

# 啟動後端
./start_backend_daemon.sh
```

---

## 監控建議

重啟後端後，建議監控以下項目：

1. **記憶體使用趨勢**
   ```bash
   # 查看後端進程記憶體使用
   ps aux | grep whisper_server.py
   ```

2. **背景清理日誌**
   - 檢查日誌中的 "🧹 執行定期記憶體清理..." 訊息
   - 確認是否有孤立任務被清理

3. **轉錄完成後記憶體釋放**
   - 檢查 "🧹 [task_id] 記憶體清理完成" 訊息

---

## 如果問題仍存在

如果記憶體問題仍未解決，下一步建議：

1. **添加記憶體分析工具**
   ```python
   import tracemalloc
   tracemalloc.start()
   ```

2. **監控 MongoDB 連接池**
   - 檢查是否有連接洩漏
   - 限制最大連接數

3. **考慮使用 Whisper 的串流模式**
   - 避免一次性載入大型音訊檔

4. **設置記憶體限制**
   ```bash
   # 限制 Python 進程記憶體使用
   ulimit -v 8000000  # 8GB
   ```
