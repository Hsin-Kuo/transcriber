# 問題診斷計畫

## 已確認

✅ **Main branch 運作正常**
- 轉錄順利
- 說話者辨識正常
- 輪詢不超時
- 成功產生逐字稿

❌ **Feature branch 持續超時**
- 即使套用 main branch 的配置仍超時
- 問題出在分支的某些改動

## 關鍵差異分析

讓我檢查 feature branch 引入的主要改動：

### 1. 認證系統
- 新增 `Depends(get_current_user)` 到端點
- JWT token 驗證
- 每個請求都需要驗證

### 2. MongoDB 整合
- 從 JSON 檔案改為 MongoDB
- 新增 `run_async_in_thread` 函數
- 任務資料結構變更（巢狀 vs 扁平）

### 3. Task Repository
- 新增 TaskRepository 層
- 資料庫查詢透過 async 函數

### 4. 端點變更
- `/transcribe` 端點加入認證
- `get_task_status` 端點加入權限檢查

## 排查策略

### 方案 A：逐步回退（推薦）

在 feature branch 上逐步移除功能，找出問題點：

1. **測試 1**：暫時移除端點的認證檢查
   - 移除 `Depends(get_current_user)`
   - 看是否還超時

2. **測試 2**：如果仍超時，檢查 `get_task_status` 端點
   - 對比 main branch 的實作
   - 看是否有額外的查詢或處理

3. **測試 3**：檢查任務初始化
   - 對比 main branch 的任務建立流程
   - 看是否有額外的 DB 操作

### 方案 B：對比關鍵端點

直接對比 main 和 feature branch 的關鍵差異：

```bash
# 對比 /transcribe 端點
git diff main feature_add_account_system -- src/whisper_server.py | grep -A50 "@app.post.*transcribe"

# 對比 get_task_status
git diff main feature_add_account_system -- src/whisper_server.py | grep -A50 "def get_task_status"
```

## 下一步

1. 切回 feature branch
2. 開始系統性測試
3. 找出導致超時的確切改動
