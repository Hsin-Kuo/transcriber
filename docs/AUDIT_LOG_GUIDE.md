# Audit Log 使用指南

## 概述

Audit Log 系統會自動記錄所有重要操作到 MongoDB `audit_logs` collection 中。

## 資料庫結構

```javascript
{
  "_id": ObjectId,
  "user_id": String,              // 用戶 ID（可為 null，如登入失敗）
  "log_type": String,             // 日誌類型：auth, task, transcription, tag, admin, file
  "action": String,               // 操作動作
  "ip_address": String,           // IP 地址
  "path": String,                 // 請求路徑
  "method": String,               // HTTP 方法
  "status_code": Number,          // HTTP 狀態碼
  "request_body": Object,         // 請求內容（已清理敏感資訊）
  "response_message": String,     // 回應訊息
  "resource_id": String,          // 資源 ID（如 task_id）
  "user_agent": String,           // User-Agent
  "duration_ms": Number,          // 處理時間（毫秒）
  "timestamp": String             // 時間戳記（UTC+8）
}
```

## 在 Router 中使用

### 1. 引入必要的模組

```python
from fastapi import Request
from ..utils.audit_logger import get_audit_logger
```

### 2. 在函數簽名中加入 Request

```python
@router.post("/some-endpoint")
async def some_function(
    request: Request,  # 加入此參數
    # ... 其他參數
):
    audit_logger = get_audit_logger()
    # ... 函數邏輯
```

### 3. 記錄操作

#### 認證相關操作

```python
await audit_logger.log_auth(
    request=request,
    action="login",              # login, logout, register, token_refresh
    user_id=str(user["_id"]),
    status_code=200,
    message="登入成功"
)
```

#### 任務相關操作

```python
await audit_logger.log_task_operation(
    request=request,
    action="create",            # create, update, delete, cancel, view
    user_id=str(current_user["_id"]),
    task_id=task_id,
    status_code=200,
    message="任務建立成功",
    request_body={"filename": "test.mp3"}  # 可選
)
```

#### 轉錄相關操作

```python
await audit_logger.log_transcription_operation(
    request=request,
    action="download",          # create, download, update_content, update_metadata
    user_id=str(current_user["_id"]),
    task_id=task_id,
    status_code=200,
    message="下載轉錄結果"
)
```

#### 檔案相關操作

```python
await audit_logger.log_file_operation(
    request=request,
    action="download",          # download, upload, delete
    user_id=str(current_user["_id"]),
    resource_id=file_id,
    status_code=200,
    message="下載音檔"
)
```

#### 標籤相關操作

```python
await audit_logger.log_tag_operation(
    request=request,
    action="create",            # create, update, delete, reorder
    user_id=str(current_user["_id"]),
    tag_id=tag_id,
    status_code=200,
    message="標籤建立成功",
    request_body={"name": "工作", "color": "#FF0000"}  # 可選
)
```

#### 管理員操作

```python
await audit_logger.log_admin_operation(
    request=request,
    action="view_statistics",   # view_statistics, manage_users, etc.
    user_id=str(current_user["_id"]),
    status_code=200,
    message="查看統計資料"
)
```

## 完整範例

### 登入功能（含失敗記錄）

```python
@router.post("/login")
async def login(
    request: Request,
    credentials: UserLogin,
    db=Depends(get_database)
):
    audit_logger = get_audit_logger()
    user = await user_repo.get_by_email(credentials.email)

    # 登入失敗
    if not user or not verify_password(credentials.password, user["password_hash"]):
        await audit_logger.log_auth(
            request=request,
            action="login_failed",
            user_id=str(user["_id"]) if user else None,
            status_code=401,
            message=f"登入失敗: {credentials.email}"
        )
        raise HTTPException(status_code=401, detail="Email 或密碼錯誤")

    # 登入成功
    access_token = create_access_token(user)
    await audit_logger.log_auth(
        request=request,
        action="login",
        user_id=str(user["_id"]),
        status_code=200,
        message="登入成功"
    )

    return {"access_token": access_token}
```

### 刪除任務

```python
@router.delete("/tasks/{task_id}")
async def delete_task(
    request: Request,
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    audit_logger = get_audit_logger()

    # 執行刪除
    success = await task_service.delete_task(task_id)

    # 記錄操作
    await audit_logger.log_task_operation(
        request=request,
        action="delete",
        user_id=str(current_user["_id"]),
        task_id=task_id,
        status_code=200 if success else 500,
        message="任務刪除成功" if success else "任務刪除失敗"
    )

    return {"success": success}
```

## 查詢 Audit Log API

### 獲取操作記錄

```
GET /api/admin/audit-logs?limit=100&skip=0&log_type=auth&user_id=xxx
```

### 獲取失敗操作記錄

```
GET /api/admin/audit-logs/failed?days=7&limit=100
```

### 獲取操作統計

```
GET /api/admin/audit-logs/statistics?days=30
```

### 獲取特定資源的操作記錄

```
GET /api/admin/audit-logs/resource/{resource_id}?limit=50
```

## 建議記錄的操作

### 必須記錄（高優先級）

- ✅ **認證操作**：登入、登出、註冊、Token 刷新（包含失敗）
- ✅ **資料刪除**：刪除任務、刪除標籤
- ✅ **資料修改**：更新任務、更新標籤、更新轉錄內容
- ✅ **權限變更**：修改用戶權限、停用帳號

### 應該記錄（中優先級）

- 🔸 **資料建立**：建立任務、建立標籤、上傳檔案
- 🔸 **檔案下載**：下載轉錄結果、下載音檔
- 🔸 **批次操作**：批次刪除、批次更新標籤

### 可選記錄（低優先級）

- 🔹 **查詢操作**：查看任務列表、查看統計資料
- 🔹 **系統操作**：查看健康狀態

## 注意事項

1. **敏感資訊過濾**：`sanitize_request_body()` 會自動過濾 password, token, secret 等敏感欄位
2. **IP 地址獲取**：優先從 `X-Forwarded-For` header 獲取（通過代理時）
3. **時區**：所有時間戳記使用 UTC+8（台北時間）
4. **索引優化**：已在 `user_id`, `log_type`, `timestamp`, `resource_id` 上建立索引

## MongoDB 查詢範例

### 查詢某用戶的所有登入記錄

```javascript
db.audit_logs.find({
  user_id: "xxx",
  log_type: "auth",
  action: "login"
}).sort({ timestamp: -1 })
```

### 查詢最近 24 小時的失敗操作

```javascript
db.audit_logs.find({
  timestamp: { $gte: "2025-01-01 00:00:00" },
  status_code: { $gte: 400 }
}).sort({ timestamp: -1 })
```

### 查詢特定 IP 的所有操作

```javascript
db.audit_logs.find({
  ip_address: "192.168.1.100"
}).sort({ timestamp: -1 })
```

### 統計各類型操作數量

```javascript
db.audit_logs.aggregate([
  { $group: { _id: "$log_type", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
])
```
