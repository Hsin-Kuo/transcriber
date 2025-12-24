# 後端三層架構說明

## 概述

本專案已成功重構為清晰的三層架構設計，提升了代碼的可維護性、可測試性和可擴展性。

## 架構圖

```
┌─────────────────────────────────────────────────────────┐
│                    API 層 (Routers)                      │
│  /auth, /tasks, /transcriptions, /api/tags              │
│  負責：HTTP 請求處理、參數驗證、權限檢查                   │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                業務邏輯層 (Services)                      │
│  TaskService, TranscriptionService, TagService,          │
│  AudioService + Processors (Whisper, Punctuation, etc.)  │
│  負責：業務規則、流程協調、狀態管理                        │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│               資料存取層 (Repositories)                   │
│  TaskRepository, TagRepository, UserRepository           │
│  負責：資料庫操作、查詢、索引管理                          │
└─────────────────────────────────────────────────────────┘
```

## 目錄結構

```
/src
├── main.py                          # 新應用入口（推薦使用）
├── whisper_server.py                # 舊應用入口（向後兼容）
├── dependencies.py                  # 統一依賴注入
│
├── routers/                         # API 層
│   ├── auth.py                      # 認證 API
│   ├── tasks.py                     # 任務管理 API
│   ├── transcriptions.py            # 轉錄 API
│   └── tags.py                      # 標籤管理 API
│
├── services/                        # 業務邏輯層
│   ├── task_service.py              # 任務狀態管理
│   ├── transcription_service.py     # 轉錄流程協調
│   ├── tag_service.py               # 標籤管理
│   ├── audio_service.py             # 音檔處理
│   └── utils/                       # 工具類（無狀態）
│       ├── whisper_processor.py     # Whisper 轉錄
│       ├── punctuation_processor.py # 標點處理
│       └── diarization_processor.py # 說話者辨識
│
└── database/
    └── repositories/                # 資料存取層
        ├── task_repo.py             # 任務資料存取
        ├── tag_repo.py              # 標籤資料存取
        └── user_repo.py             # 用戶資料存取
```

## 啟動方式

### 使用新的 main.py（推薦）

```bash
# 開發模式
python src/main.py

# 或使用 uvicorn
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 使用舊的 whisper_server.py（向後兼容）

```bash
python src/whisper_server.py
```

## API 端點

### 認證相關
- `POST /auth/register` - 註冊
- `POST /auth/login` - 登入
- `POST /auth/refresh` - 刷新 Token
- `GET /auth/me` - 獲取當前用戶資訊

### 任務管理（新架構）
- `GET /tasks/{task_id}` - 獲取任務狀態
- `GET /tasks/{task_id}/events` - SSE 即時狀態更新
- `POST /tasks/{task_id}/cancel` - 取消任務
- `DELETE /tasks/{task_id}` - 刪除任務

### 轉錄服務（新架構）
- `POST /transcriptions` - 建立轉錄任務
- `GET /transcriptions/{task_id}/download` - 下載轉錄結果
- `GET /transcriptions/{task_id}/audio` - 下載原始音檔
- `GET /transcriptions/{task_id}/segments` - 獲取時間軸片段

### 標籤管理（新架構）
- `POST /api/tags` - 建立標籤
- `GET /api/tags` - 獲取所有標籤
- `GET /api/tags/{tag_id}` - 獲取單個標籤
- `PUT /api/tags/{tag_id}` - 更新標籤
- `DELETE /api/tags/{tag_id}` - 刪除標籤
- `PUT /api/tags/order` - 更新標籤順序
- `GET /api/tags/statistics` - 獲取標籤統計

### 舊端點（向後兼容）
- `POST /transcribe` - 建立轉錄任務（舊版）
- `GET /transcribe/{task_id}` - 獲取任務狀態（舊版）
- 其他舊端點仍可正常使用

## 核心服務說明

### TaskService
**職責**：任務狀態管理
- 封裝全域狀態（記憶體中的運行時狀態）
- 管理任務取消標記
- 處理臨時目錄清理
- 線程安全的狀態訪問

**關鍵方法**：
- `create_task()` - 建立任務
- `get_task()` - 獲取任務（合併 DB + 記憶體狀態）
- `update_task_status()` - 更新任務狀態
- `cancel_task()` - 取消任務
- `cleanup_task_memory()` - 清理記憶體

### TranscriptionService
**職責**：轉錄流程協調
- 協調音檔轉換、轉錄、標點、儲存流程
- 管理轉錄任務生命週期
- 更新任務進度

**使用的 Processors**：
- `WhisperProcessor` - Whisper 轉錄
- `PunctuationProcessor` - 標點處理
- `DiarizationProcessor` - 說話者辨識

### TagService
**職責**：標籤管理
- 標籤 CRUD 操作
- 標籤重命名（自動更新所有任務）
- 批次標籤操作
- 標籤統計

### AudioService
**職責**：音檔處理
- 音檔格式轉換
- 音檔裁切和合併
- 音檔資訊獲取
- 靜音檢測

## 依賴注入

使用 `src/dependencies.py` 統一管理所有依賴：

```python
from src.dependencies import (
    get_task_repository,
    get_tag_repository,
    get_tag_service,
    get_audio_service
)

@router.get("/example")
async def example(
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    # 使用 tag_service
    tags = await tag_service.get_all_tags(str(current_user["_id"]))
    return tags
```

## 設計原則

### 1. 單一職責原則
每個服務和類別都有明確的單一職責：
- **Router（API 層）**：只處理 HTTP 請求、參數驗證、響應格式化
- **Service（業務邏輯層）**：處理業務規則、資料轉換、驗證邏輯、流程協調
- **Repository（資料存取層）**：只處理純資料庫操作（CRUD、查詢）

### 2. Repository 層純粹性
Repository 層已完全重構，確保只包含純資料存取操作：
- ✅ **保留**：CRUD 操作、查詢、索引管理、批次操作
- ❌ **已移除**：業務邏輯、資料驗證、計算、轉換

**已移至 Service 層的方法**：
- `update_content()` → `TaskService.update_transcription_content()` （含文字長度計算）
- `update_metadata()` → `TaskService.update_task_metadata()` （含檔名驗證）
- `update_tags()` → `TaskService.update_task_tags()` （含權限驗證）
- `update_keep_audio()` → `TaskService.update_keep_audio()` （含權限驗證）
- `mark_as_cancelled()` → `TaskService.mark_task_as_cancelled()` （含狀態轉換邏輯）

### 3. 依賴注入
使用 FastAPI 的 Depends 機制，統一管理依賴

### 4. 向後兼容
保留舊端點，確保前端不會中斷

### 5. 狀態共享
新舊代碼共享相同的全域狀態，確保一致性

## 測試建議

### 單元測試
```python
# 測試 TagService
async def test_create_tag():
    tag_repo = MockTagRepository()
    task_repo = MockTaskRepository()
    tag_service = TagService(tag_repo, task_repo)

    tag = await tag_service.create_tag(
        user_id="user123",
        name="測試標籤",
        color="#FF0000"
    )

    assert tag["name"] == "測試標籤"
```

### API 測試
```python
# 使用 TestClient
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_create_tag_api():
    response = client.post(
        "/api/tags",
        json={"name": "測試標籤", "color": "#FF0000"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
```

## 擴展指南

### 添加新功能

1. **創建 Service**（如果需要新的業務邏輯）
   ```python
   # src/services/new_service.py
   class NewService:
       def __init__(self, repo: Repository):
           self.repo = repo
   ```

2. **創建 Router**
   ```python
   # src/routers/new_router.py
   router = APIRouter(prefix="/api/new", tags=["New"])

   @router.get("/")
   async def get_items(
       service: NewService = Depends(get_new_service)
   ):
       return await service.get_items()
   ```

3. **註冊 Router**
   ```python
   # src/main.py
   from src.routers import new_router
   app.include_router(new_router.router)
   ```

## 效能優化

### 1. 快取
可在 Service 層添加快取：
```python
from functools import lru_cache

class TagService:
    @lru_cache(maxsize=128)
    async def get_popular_tags(self, user_id: str):
        # 快取熱門標籤
        pass
```

### 2. 批次操作
使用 Service 層的批次方法：
```python
# 批次添加標籤（一次 DB 操作）
await tag_service.add_tags_to_tasks(
    user_id=user_id,
    task_ids=["id1", "id2", "id3"],
    tag_names=["標籤A", "標籤B"]
)
```

### 3. 非同步處理
TranscriptionService 使用 ThreadPoolExecutor 進行背景處理

## 遷移指南

### 從舊代碼遷移到新架構

1. **API 調用更新**（前端）
   ```javascript
   // 舊端點
   POST /transcribe

   // 新端點（推薦）
   POST /transcriptions
   ```

2. **保持向後兼容**
   - 舊端點仍然可用
   - 可以逐步遷移，不需要一次性更新

3. **利用新功能**
   - 使用新的 `/tasks/*` 端點獲得更好的任務管理
   - 使用 `/api/tags/*` 進行標籤管理

## 維護指南

### 日常維護
1. 定期清理記憶體（已自動化）
2. 監控資料庫索引效能
3. 檢查日誌中的錯誤和警告

### 資料庫遷移
使用 MongoDB 遷移腳本（在 `src/database/migrations/` 目錄）

### 升級依賴
```bash
pip install --upgrade -r requirements.txt
```

## 常見問題

### Q: 為什麼保留 whisper_server.py？
A: 為了向後兼容。可以使用新的 main.py，也可以繼續使用舊的入口。

### Q: 新舊端點有什麼區別？
A: 新端點使用三層架構，代碼更清晰。舊端點為了兼容性保留。

### Q: 如何選擇使用哪個入口？
A: 推薦使用新的 main.py，它更清晰、更易於維護。

## 版本歷史

- **v3.0.0** - 完成三層架構重構
- **v2.0.0** - MongoDB 遷移
- **v1.0.0** - 初始版本

## 貢獻

歡迎貢獻！請遵循以下規範：
1. 保持三層架構的清晰分離
2. 為新功能添加測試
3. 更新相關文檔
4. 遵循現有的代碼風格

## 授權

[您的授權資訊]
