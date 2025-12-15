# 階段二完成指南：資料遷移 + 配額系統

## 已完成的工作

### ✅ 新增檔案

**資料模型**：
- `src/models/task.py` - 任務資料模型
- `src/models/quota.py` - 配額等級定義

**資料存取層**：
- `src/database/repositories/task_repo.py` - 任務資料操作

**配額系統**：
- `src/auth/quota.py` - 配額管理器（QuotaManager）

**資料遷移**：
- `src/database/migrations/migrate_json_to_mongo.py` - JSON → MongoDB 遷移腳本

**已更新檔案**：
- `src/auth/dependencies.py` - 更新 check_quota 中介層（檢查並發任務數）

---

## 配額系統說明

### 配額等級

| 等級 | 每月次數 | 每月時數 | 並發任務 | 價格 |
|------|----------|----------|----------|------|
| 免費版 | 10 次 | 60 分鐘 | 1 個 | $0 |
| 基礎版 | 100 次 | 600 分鐘 | 2 個 | $9.99/月 |
| 專業版 | 500 次 | 3000 分鐘 | 5 個 | $29.99/月 |
| 企業版 | 無限制 | 無限制 | 10 個 | $99.99/月 |

### 配額檢查邏輯

1. **並發任務數檢查**（`check_quota` 中介層）
   - 自動檢查用戶當前進行中的任務數
   - 超過限制時返回 429 錯誤

2. **轉錄次數檢查**（待整合到轉錄端點）
   - 每次轉錄前檢查本月已使用次數
   - 超限時拒絕請求

3. **轉錄時數檢查**（待整合到轉錄端點）
   - 根據音訊時長檢查是否超過配額
   - 超限時返回剩餘可用時數

4. **自動重置**
   - 每月 1 日自動重置配額
   - 累計統計不會重置

---

## 下一步：資料遷移

### 1. 備份現有資料

```bash
# 備份任務資料
cp output/tasks.json output/tasks.json.manual_backup
cp output/tag_colors.json output/tag_colors.json.manual_backup
cp output/tag_order.json output/tag_order.json.manual_backup
```

### 2. 確保 MongoDB 運行

```bash
# 檢查 MongoDB 狀態
docker ps | grep whisper-mongo

# 如果未運行，啟動 MongoDB
docker start whisper-mongo
```

### 3. 執行遷移腳本

```bash
# 執行遷移
python -m src.database.migrations.migrate_json_to_mongo
```

**預期輸出**：
```
📂 讀取任務資料: /path/to/output/tasks.json
📊 共 15 個任務需要遷移
✅ 找到管理員帳號: admin@example.com (ObjectId(...))
✅ 遷移任務: abc123 - meeting_recording.mp3
✅ 遷移任務: def456 - interview.mp3
...
💾 原檔案已備份至: output/tasks.json.backup
🎉 遷移完成!
  - 成功: 15
  - 跳過: 0
  - 失敗: 0
📊 正在建立索引...
✅ 索引建立完成
```

### 4. 驗證遷移結果

```bash
# 使用 MongoDB CLI 驗證
docker exec -it whisper-mongo mongosh

# 在 mongosh 中執行
use whisper_transcriber
db.tasks.countDocuments()  // 應該與原 tasks.json 數量一致
db.tasks.findOne()  // 查看任務結構
db.tasks.find({user_id: null}).count()  // 檢查未分配用戶的任務數
exit
```

---

## 階段三預覽：轉錄端點整合

階段二建立了配額系統的基礎設施，但尚未完全整合到轉錄端點。階段三將完成：

### 需要修改的部分

1. **POST /transcribe 端點**：
   - 添加 `Depends(check_quota)` 認證
   - 獲取音訊時長後檢查配額
   - 任務建立時關聯 `user_id`
   - 存儲到 MongoDB 而非記憶體

2. **轉錄完成回調**：
   - 調用 `QuotaManager.increment_usage()` 更新配額
   - 更新 MongoDB 中的任務狀態

3. **其他任務端點**：
   - `GET /transcribe/{task_id}` - 添加權限檢查
   - `DELETE /transcribe/{task_id}` - 添加權限檢查
   - `GET /transcribe/active/list` - 只返回當前用戶的任務

### 簡化的整合範例

```python
# POST /transcribe 端點修改示意
@app.post("/transcribe")
async def create_transcription(
    file: UploadFile = File(...),
    current_user: dict = Depends(check_quota),  # 添加認證和配額檢查
    # ... 其他參數
):
    db = current_user["_db"]

    # 1. 獲取音訊時長
    audio_duration = get_audio_duration(file)

    # 2. 檢查轉錄配額
    from src.auth.quota import QuotaManager
    await QuotaManager.check_transcription_quota(current_user, audio_duration)

    # 3. 建立任務（關聯 user_id）
    task_id = str(uuid.uuid4())
    task_data = {
        "_id": task_id,
        "user_id": str(current_user["_id"]),
        "filename": file.filename,
        "status": "pending",
        # ...
    }

    # 4. 存儲到 MongoDB
    await db.tasks.insert_one(task_data)

    # 5. 背景任務處理（完成後更新配額）
    # ...
```

---

## 測試階段二功能

### 1. 測試配額檢查（並發任務）

```bash
# 註冊一個免費版用戶
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"free@example.com","password":"Test@123456"}'

# 獲取 access_token（從上面的響應中）
TOKEN="<your_access_token>"

# 查看當前配額
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

### 2. 檢查 MongoDB 中的用戶配額

```bash
docker exec -it whisper-mongo mongosh

use whisper_transcriber
db.users.findOne({email: "free@example.com"}, {quota: 1, usage: 1})
```

**預期輸出**：
```json
{
  "quota": {
    "tier": "free",
    "max_transcriptions": 10,
    "max_duration_minutes": 60,
    "max_concurrent_tasks": 1
  },
  "usage": {
    "transcriptions": 0,
    "duration_minutes": 0,
    "last_reset": ISODate("2025-12-15T..."),
    "total_transcriptions": 0,
    "total_duration_minutes": 0
  }
}
```

### 3. 手動測試配額管理器

```python
# 創建測試腳本 test_quota.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from src.auth.quota import QuotaManager
from bson import ObjectId

async def test():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["whisper_transcriber"]

    # 獲取用戶
    user = await db.users.find_one({"email": "free@example.com"})

    # 測試配額檢查
    try:
        await QuotaManager.check_transcription_quota(user, 3600)  # 60 分鐘
        print("✅ 配額檢查通過")
    except Exception as e:
        print(f"❌ 配額不足: {e.detail}")

    # 測試增加使用量
    await QuotaManager.increment_usage(db, str(user["_id"]), 1800)  # 30 分鐘
    print("✅ 使用量已更新")

    # 檢查更新後的用戶
    user = await db.users.find_one({"email": "free@example.com"})
    print(f"📊 當前使用量: {user['usage']}")

    client.close()

asyncio.run(test())
```

```bash
# 執行測試
python test_quota.py
```

---

## 已知限制（待階段三完成）

1. ❌ 轉錄端點尚未添加認證
2. ❌ 轉錄端點尚未檢查音訊時長配額
3. ❌ 轉錄完成後尚未自動更新配額
4. ❌ 任務列表尚未按用戶隔離
5. ✅ 並發任務數檢查已實作
6. ✅ 配額管理器已實作
7. ✅ 資料遷移腳本已實作

---

## 下一步

你可以選擇：

1. **測試階段二功能**：執行資料遷移，測試配額系統
2. **繼續階段三**：前端認證整合（建立登入/註冊頁面）
3. **完成轉錄端點整合**：將配額檢查完全整合到現有轉錄功能

建議順序：**測試階段二 → 階段三前端 → 轉錄端點整合**
