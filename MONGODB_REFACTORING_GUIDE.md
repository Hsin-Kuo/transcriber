# MongoDB 重構指南

## 架構概覽

```
whisper_server.py (業務邏輯層)
        ↓ 調用
TaskRepository (數據訪問層 - src/database/repositories/task_repo.py)
        ↓ 操作
MongoDB (數據庫)
```

**核心原則**: 所有數據庫操作都通過 TaskRepository，業務邏輯層不直接操作 MongoDB

---

## 已完成的工作

### ✅ 數據訪問層 (TaskRepository)

已實現的方法：

**基礎 CRUD**:
- `create(task_data)` - 創建任務
- `get_by_id(task_id)` - 獲取任務
- `get_by_id_and_user(task_id, user_id)` - 獲取任務（權限檢查）
- `update(task_id, updates)` - 更新任務
- `delete(task_id, user_id)` - 刪除任務

**查詢方法**:
- `find_by_user(user_id, skip, limit, status, sort)` - 查詢用戶任務列表
- `find_active_by_user(user_id)` - 查詢進行中的任務
- `count_by_user(user_id, status)` - 計數任務
- `count_by_status(user_id, status)` - 按狀態計數

**專用更新方法**:
- `update_content(task_id, user_id, content)` - 更新轉錄內容
- `update_metadata(task_id, user_id, custom_name)` - 更新元數據
- `update_tags(task_id, user_id, tags)` - 更新標籤
- `update_keep_audio(task_id, user_id, keep_audio)` - 更新音檔保留狀態
- `mark_as_cancelled(task_id, user_id)` - 標記為已取消

**批次操作**:
- `bulk_update_tags_add(task_ids, user_id, tags)` - 批次添加標籤
- `bulk_update_tags_remove(task_ids, user_id, tags)` - 批次移除標籤
- `bulk_delete(task_ids, user_id)` - 批次刪除

**工具方法**:
- `get_all_user_tags(user_id)` - 獲取所有標籤
- `count_keep_audio_tasks(user_id)` - 計數保留音檔的任務
- `clear_audio_files_except_kept(user_id)` - 清除未保留的音檔記錄

### ✅ 基礎設施

- MongoDB 連接已初始化
- TaskRepository 已在 startup 事件中初始化為全域變數 `task_repo`
- 已移除 14 處 `save_tasks_to_disk()` 調用
- 已註解掉記憶體字典 `transcription_tasks`（待完全移除）

---

## 重構模式對照表

### 1. 查詢單個任務

#### 舊模式：
```python
with tasks_lock:
    task = transcription_tasks.get(task_id)
if not task:
    raise HTTPException(status_code=404, detail="任務不存在")
```

#### 新模式：
```python
task = await task_repo.get_by_id(task_id)
if not task:
    raise HTTPException(status_code=404, detail="任務不存在")
```

**注意**:
- 移除 `with tasks_lock`（MongoDB 操作自帶事務）
- 所有端點都應該已經是 `async`，直接使用 `await`

---

### 2. 查詢單個任務（含權限檢查）

#### 舊模式：
```python
with tasks_lock:
    task = transcription_tasks.get(task_id)
if not task:
    raise HTTPException(status_code=404, detail="任務不存在")
if str(task.get("user_id")) != str(current_user["_id"]):
    raise HTTPException(status_code=403, detail="無權訪問此任務")
```

#### 新模式：
```python
task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))
if not task:
    raise HTTPException(status_code=404, detail="任務不存在或無權訪問")
```

---

### 3. 創建任務

#### 舊模式：
```python
with tasks_lock:
    transcription_tasks[task_id] = {
        "task_id": task_id,
        "user_id": str(current_user["_id"]),
        "status": "pending",
        # ... 其他欄位
    }
```

#### 新模式：
```python
task_data = {
    "_id": task_id,  # MongoDB 使用 _id
    "task_id": task_id,
    "user_id": str(current_user["_id"]),
    "status": "pending",
    # ... 其他欄位
}
await task_repo.create(task_data)
```

**注意**: 使用 `_id` 作為 MongoDB 的主鍵

---

### 4. 更新任務

#### 舊模式：
```python
with tasks_lock:
    if task_id in transcription_tasks:
        transcription_tasks[task_id].update(updates)
        transcription_tasks[task_id]["updated_at"] = get_current_time()
```

#### 新模式：
```python
# updated_at 會自動添加，不需要手動設置
await task_repo.update(task_id, updates)
```

---

### 5. 刪除任務

#### 舊模式：
```python
with tasks_lock:
    task = transcription_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任務不存在")
    # 權限檢查
    del transcription_tasks[task_id]
```

#### 新模式：
```python
deleted = await task_repo.delete(task_id, user_id)
if not deleted:
    raise HTTPException(status_code=404, detail="任務不存在或無權刪除")
```

---

### 6. 查詢任務列表

#### 舊模式：
```python
with tasks_lock:
    user_tasks = [
        task for task in transcription_tasks.values()
        if str(task.get("user_id")) == str(current_user["_id"])
    ]
    active = [
        task for task in user_tasks
        if task["status"] in ["pending", "processing"]
    ]
```

#### 新模式：
```python
# 查詢所有任務
user_tasks = await task_repo.find_by_user(str(current_user["_id"]))

# 或查詢活躍任務
active_tasks = await task_repo.find_active_by_user(str(current_user["_id"]))
```

---

### 7. 更新轉錄內容

#### 舊模式：
```python
with tasks_lock:
    if task_id in transcription_tasks:
        transcription_tasks[task_id]["text_length"] = len(new_content)
        transcription_tasks[task_id]["updated_at"] = get_current_time()
save_tasks_to_disk()
```

#### 新模式：
```python
await task_repo.update_content(task_id, user_id, new_content)
```

---

### 8. 更新標籤

#### 舊模式：
```python
with tasks_lock:
    if task_id in transcription_tasks:
        transcription_tasks[task_id]["tags"] = tag_update.tags
        transcription_tasks[task_id]["updated_at"] = get_current_time()
save_tasks_to_disk()
```

#### 新模式：
```python
await task_repo.update_tags(task_id, user_id, tag_update.tags)
```

---

### 9. 批次刪除

#### 舊模式：
```python
deleted_tasks = []
for task_id in request.task_ids:
    with tasks_lock:
        task = transcription_tasks.get(task_id)
        if task and task["user_id"] == user_id:
            del transcription_tasks[task_id]
            deleted_tasks.append(task_id)
save_tasks_to_disk()
```

#### 新模式：
```python
deleted_count, deleted_ids = await task_repo.bulk_delete(
    request.task_ids,
    user_id
)
```

---

### 10. 背景任務處理（特殊情況）

背景任務在 ThreadPoolExecutor 中運行，需要特殊處理：

#### 舊模式：
```python
def process_transcription_task(...):
    # 同步函數
    with tasks_lock:
        task = transcription_tasks.get(task_id)
    # ... 處理
    with tasks_lock:
        transcription_tasks[task_id].update(...)
```

#### 新模式（方法 1 - 推薦）：
```python
def process_transcription_task(...):
    # 使用 run_async_in_thread 輔助函數
    def update_progress(updates):
        run_async_in_thread(task_repo.update(task_id, updates))

    # 獲取任務
    task = run_async_in_thread(task_repo.get_by_id(task_id))

    # ... 處理

    # 更新任務
    run_async_in_thread(task_repo.update(task_id, updates))
```

#### 新模式（方法 2 - 改為 async）：
```python
async def process_transcription_task(...):
    # 改為 async 函數
    task = await task_repo.get_by_id(task_id)
    # ... 處理
    await task_repo.update(task_id, updates)

# 在 executor 中調用時：
executor.submit(lambda: asyncio.run(process_transcription_task(...)))
```

---

## 需要修改的檔案位置

### 關鍵函數

1. **`update_task_progress()`** (約 Line 320-370)
   - 背景任務更新進度的核心函數
   - 需改為使用 `run_async_in_thread()` 或改為 async

2. **`process_transcription_task()`** (約 Line 400-1650)
   - 主要的轉錄處理邏輯
   - 多處更新任務狀態
   - 需系統性地改為使用 TaskRepository

3. **定期清理音檔** (約 Line 1300-1410)
   - 遍歷所有任務清理音檔
   - 改為使用 `task_repo.clear_audio_files_except_kept()`

### API 端點 (所有已經是 async)

1. **GET /** (Line ~1806) - 顯示服務狀態
   - 改為使用 `task_repo.count_by_status()`

2. **POST /transcribe** (Line ~1843) - 創建轉錄任務
   - 改為使用 `task_repo.create()`

3. **GET /transcribe/{task_id}** (Line ~1959) - 查詢任務狀態
   - 改為使用 `task_repo.get_by_id_and_user()`

4. **GET /transcribe/{task_id}/download** (Line ~1979)
   - 改為使用 `task_repo.get_by_id_and_user()`

5. **GET /transcribe/{task_id}/audio** (Line ~2035)
   - 改為使用 `task_repo.get_by_id_and_user()`

6. **GET /transcribe/{task_id}/segments** (Line ~2084)
   - 改為使用 `task_repo.get_by_id_and_user()`

7. **PUT /transcribe/{task_id}/content** (Line ~2123)
   - 改為使用 `task_repo.update_content()`

8. **PUT /transcribe/{task_id}/metadata** (Line ~2189)
   - 改為使用 `task_repo.update_metadata()`

9. **PUT /transcribe/{task_id}/tags** (Line ~2232)
   - 改為使用 `task_repo.update_tags()`

10. **PUT /transcribe/{task_id}/keep-audio** (Line ~2270)
    - 改為使用 `task_repo.update_keep_audio()`

11. **POST /transcribe/{task_id}/cancel** (Line ~2401)
    - 改為使用 `task_repo.mark_as_cancelled()`

12. **DELETE /transcribe/{task_id}** (Line ~2453)
    - 改為使用 `task_repo.delete()`

13. **POST /transcribe/batch/delete** (Line ~2529)
    - 改為使用 `task_repo.bulk_delete()`

14. **POST /transcribe/batch/tags/add** (Line ~2609)
    - 改為使用 `task_repo.bulk_update_tags_add()`

15. **POST /transcribe/batch/tags/remove** (Line ~2663)
    - 改為使用 `task_repo.bulk_update_tags_remove()`

16. **GET /transcribe/active/list** (Line ~2738)
    - 改為使用 `task_repo.find_by_user()` 和 `task_repo.find_active_by_user()`

17. **GET /tags** (Line ~2270左右)
    - 改為使用 `task_repo.get_all_user_tags()`

---

## 實施步驟建議

### 階段 1：查詢端點（最簡單）

修改所有 GET 端點，因為它們：
- 已經是 async
- 只涉及讀取操作
- 風險最低

**端點列表**:
- GET /
- GET /transcribe/{task_id}
- GET /transcribe/{task_id}/download
- GET /transcribe/{task_id}/audio
- GET /transcribe/{task_id}/segments
- GET /transcribe/active/list
- GET /tags

### 階段 2：創建端點

修改創建相關的端點：
- POST /transcribe

### 階段 3：更新端點

修改所有 PUT 端點：
- PUT /transcribe/{task_id}/content
- PUT /transcribe/{task_id}/metadata
- PUT /transcribe/{task_id}/tags
- PUT /transcribe/{task_id}/keep-audio

### 階段 4：刪除和批次操作

修改刪除相關的端點：
- POST /transcribe/{task_id}/cancel
- DELETE /transcribe/{task_id}
- POST /transcribe/batch/delete
- POST /transcribe/batch/tags/add
- POST /transcribe/batch/tags/remove

### 階段 5：背景任務處理（最複雜）

修改背景任務處理函數：
- `update_task_progress()`
- `process_transcription_task()`
- 定期清理音檔的邏輯

---

## 測試檢查清單

每個階段完成後測試：

### ✅ 階段 1 測試
- [ ] 啟動服務無錯誤
- [ ] GET / 返回正確的統計
- [ ] GET /transcribe/active/list 返回任務列表
- [ ] GET /transcribe/{task_id} 返回任務詳情
- [ ] 權限檢查正常（用戶只能看到自己的任務）

### ✅ 階段 2 測試
- [ ] POST /transcribe 成功創建任務
- [ ] 任務寫入 MongoDB
- [ ] 任務 ID 正確
- [ ] user_id 正確關聯

### ✅ 階段 3 測試
- [ ] 更新轉錄內容成功
- [ ] 更新元數據成功
- [ ] 更新標籤成功
- [ ] 更新音檔保留狀態成功

### ✅ 階段 4 測試
- [ ] 刪除任務成功
- [ ] 取消任務成功
- [ ] 批次操作成功

### ✅ 階段 5 測試
- [ ] 完整的轉錄流程成功
- [ ] 進度更新正確
- [ ] 配額更新正確
- [ ] 任務狀態正確

---

## 故障排除

### 問題：`task_repo` 未定義

**原因**: TaskRepository 未初始化

**解決**: 確保在 startup 事件中正確初始化：
```python
@app.on_event("startup")
async def startup_event():
    global task_repo
    db = MongoDB.get_db()
    task_repo = TaskRepository(db)
```

### 問題：Cannot call async function from sync context

**原因**: 在同步函數中直接調用 async 函數

**解決**: 使用 `run_async_in_thread()` 輔助函數：
```python
result = run_async_in_thread(task_repo.get_by_id(task_id))
```

### 問題：任務查詢返回 None

**原因**: 可能使用了錯誤的任務 ID 格式（`task_id` vs `_id`）

**解決**: 確保在 MongoDB 中任務的 `_id` 欄位等於 `task_id`

### 問題：權限檢查失敗

**原因**: user_id 類型不匹配（str vs ObjectId）

**解決**: 統一使用字串：
```python
str(current_user["_id"])
```

---

## 還原方案

如果遇到嚴重問題需要還原：

```bash
# 還原 whisper_server.py
cp src/whisper_server.py.backup_before_mongo_refactor src/whisper_server.py

# 重啟服務
bash stop_backend.sh
bash start_backend_daemon.sh
```

---

## 參考資源

- **TaskRepository 原始碼**: `src/database/repositories/task_repo.py`
- **MongoDB 連接**: `src/database/mongodb.py`
- **備份檔案**: `src/whisper_server.py.backup_before_mongo_refactor`
- **任務模型**: `src/models/task.py`

---

## 完成標準

所有以下項目都完成後，MongoDB 遷移即完成：

- [ ] 移除所有 `transcription_tasks` 字典引用（58 處）
- [ ] 移除所有 `with tasks_lock`（MongoDB 操作部分）
- [ ] 所有 API 端點使用 TaskRepository
- [ ] 背景任務處理使用 TaskRepository
- [ ] 所有測試通過
- [ ] 完整轉錄流程正常運作
- [ ] 配額系統正常運作
- [ ] 權限隔離正常運作

---

**最後更新**: 2025-12-16
**作者**: Claude Code Assistant
