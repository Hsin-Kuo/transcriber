# 前端 API 端點遷移進度

## ✅ 已完成的文件

### 1. TranscriptionView.vue（核心功能）

**遷移日期**：2025-12-23

**已替換的 API 調用**：

| 原 API 調用 | 新方法 | 行號 | 狀態 |
|-------------|--------|------|------|
| `api.post('/transcribe', formData)` | `transcriptionService.create(formData)` | 270 | ✅ 完成 |
| `api.get('/transcribe/active/list')` | `taskService.getActiveList()` | 410 | ✅ 完成 |
| `api.get('/transcribe/{id}/download')` | `transcriptionService.download(taskId)` | 320, 1050 | ✅ 完成 |
| `api.post('/transcribe/{id}/cancel')` | `taskService.cancel(taskId)` | 367 | ✅ 完成 |
| `api.delete('/transcribe/{id}')` | `taskService.delete(taskId)` | 392 | ✅ 完成 |
| `${API_BASE}/transcribe/{id}/audio` | `transcriptionService.getAudioUrl()` | 1088 | ✅ 完成 |
| `api.get('/transcribe/{id}/segments')` | `transcriptionService.getSegments()` | 1053 | ✅ 完成 |
| `api.put('/transcribe/{id}/content')` | `transcriptionService.updateContent()` | 1164 | ✅ 完成 |

**遷移統計**：
- ✅ 已遷移：8 個 API 調用
- 📊 覆蓋率：100%（核心功能）
- 🎯 優先級：🔴 高優先級完成

**影響的功能**：
- ✅ 上傳音檔建立轉錄任務
- ✅ 刷新任務列表
- ✅ 下載轉錄結果
- ✅ 取消進行中的任務
- ✅ 刪除已完成的任務
- ✅ 獲取音檔 URL
- ✅ 獲取時間軸片段
- ✅ 編輯並保存轉錄內容

---

## ⏳ 待遷移的文件

### 2. TasksView.vue（任務管理頁面）

**需要遷移的 API 調用**：

| 原 API 調用 | 新方法 | 估計行號 | 優先級 |
|-------------|--------|----------|--------|
| `api.get('/transcribe/active/list')` | `taskService.getActiveList()` | ~38 | 🔴 高 |
| `api.get('/transcribe/{id}/download')` | `transcriptionService.download()` | ~113 | 🔴 高 |
| `api.delete('/transcribe/{id}')` | `taskService.delete()` | ~143 | 🔴 高 |
| `${API_BASE}/transcribe/{id}/events` | `taskService.getEventsUrl()` | ~175 | 🔴 高 |

**估計工作量**：15-20 分鐘

---

### 3. TranscriptDetailView.vue（轉錄詳情頁面）

**需要遷移的 API 調用**：

| 原 API 調用 | 新方法 | 估計行號 | 優先級 |
|-------------|--------|----------|--------|
| `api.get('/transcribe/active/list')` | `taskService.getActiveList()` | ~467 | 🟡 中 |
| `api.get('/transcribe/{id}/download')` | `transcriptionService.download()` | ~488 | 🟡 中 |
| `api.get('/transcribe/{id}/segments')` | `transcriptionService.getSegments()` | ~491 | 🟡 中 |
| `api.put('/transcribe/{id}/metadata')` | `transcriptionService.updateMetadata()` | ~568 | 🟡 中 |
| `api.put('/transcribe/{id}/content')` | `transcriptionService.updateContent()` | ~598 | 🟡 中 |
| `${API_BASE}/transcribe/{id}/audio` | `transcriptionService.getAudioUrl()` | ~645 | 🟡 中 |

**估計工作量**：20-25 分鐘

---

### 4. Navigation.vue（導航欄組件）

**需要遷移的 API 調用**：

| 原 API 調用 | 新方法 | 估計行號 | 優先級 |
|-------------|--------|----------|--------|
| `api.get('/transcribe/recent/preview')` | `taskService.getRecentPreview()` | ~133 | 🟡 中 |

**估計工作量**：5 分鐘

---

### 5. TaskList.vue（任務列表組件）

**需要遷移的 API 調用**：

⚠️ **注意**：此組件使用舊端點進行標籤和批次操作，可在後續階段遷移

| 原 API 調用 | 新方法/保持 | 估計行號 | 優先級 |
|-------------|-------------|----------|--------|
| `api.put('/transcribe/{id}/tags')` | `legacyService.updateTaskTags()` | ~927 | 🟢 低 |
| `api.put('/transcribe/{id}/keep-audio')` | `legacyService.updateKeepAudio()` | ~1402 | 🟢 低 |
| `api.post('/transcribe/batch/delete')` | `legacyService.batchDelete()` | ~1467 | 🟢 低 |
| `api.post('/transcribe/batch/tags/add')` | `legacyService.batchAddTags()` | ~1501 | 🟢 低 |
| `api.post('/transcribe/batch/tags/remove')` | `legacyService.batchRemoveTags()` | ~1536 | 🟢 低 |

**估計工作量**：10-15 分鐘（可選，低優先級）

---

## 📊 總體進度

### 遷移統計

| 狀態 | 文件數 | API 調用數 | 百分比 |
|------|--------|-----------|--------|
| ✅ 已完成 | 1 | 8 | 33% |
| ⏳ 待遷移 | 4 | 16 | 67% |
| **總計** | **5** | **24** | **100%** |

### 按優先級分類

| 優先級 | API 調用數 | 狀態 |
|--------|-----------|------|
| 🔴 高 | 12 | 8/12 完成 (67%) |
| 🟡 中 | 7 | 0/7 完成 (0%) |
| 🟢 低 | 5 | 0/5 完成 (0%) |

---

## 🎯 下一步計劃

### 階段 2：次要功能遷移

1. **TasksView.vue**（估計 15-20 分鐘）
   - 任務管理核心功能
   - SSE 事件連接

2. **TranscriptDetailView.vue**（估計 20-25 分鐘）
   - 轉錄詳情查看
   - 元數據編輯

3. **Navigation.vue**（估計 5 分鐘）
   - 最近任務預覽

### 階段 3：低優先級功能（可選）

4. **TaskList.vue**（估計 10-15 分鐘）
   - 標籤管理（使用 legacyService）
   - 批次操作

---

## ✅ 測試檢查清單

### TranscriptionView.vue 測試項目

- [x] 上傳音檔並建立轉錄任務
- [x] 查看任務列表
- [x] 下載轉錄結果
- [x] 取消進行中的任務
- [x] 刪除已完成的任務
- [x] 播放音檔
- [x] 查看時間軸片段
- [x] 編輯並保存轉錄內容

### 待測試

- [ ] TasksView.vue - 任務管理頁面
- [ ] TranscriptDetailView.vue - 詳情頁面
- [ ] Navigation.vue - 導航欄
- [ ] TaskList.vue - 任務列表組件

---

## 🔧 技術細節

### 導入語句

所有遷移的組件都需要添加以下導入：

```javascript
import { transcriptionService, taskService, legacyService } from '../api/services'
```

### 環境變數

確保在 `.env` 中設定：

```env
VITE_USE_NEW_API=true
VITE_API_BASE_URL=http://localhost:8000
```

### 回退計劃

如果遇到問題，可以設定：

```env
VITE_USE_NEW_API=false
```

立即回退到舊 API 端點。

---

## 📝 備註

- ✅ TranscriptionView.vue 已完成遷移，所有核心功能測試通過
- ⚠️ 部分舊端點（標籤、批次操作）暫時保留，使用 `legacyService` 封裝
- 🎯 下一步建議優先遷移 TasksView.vue（任務管理核心功能）

---

**最後更新**：2025-12-23
**遷移負責人**：Claude Code
**狀態**：進行中（33% 完成）
