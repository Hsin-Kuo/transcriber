# 前端 API 端點遷移指南

## 概述

本指南提供從舊端點到新三層架構端點的完整遷移步驟，確保平滑過渡。

---

## 📊 API 端點對照表

### 1. 轉錄任務相關

| 舊端點 | 新端點 | 方法 | 說明 | 優先級 |
|--------|--------|------|------|--------|
| `POST /transcribe` | `POST /transcriptions` | POST | 建立轉錄任務 | 🔴 高 |
| `GET /transcribe/{task_id}/download` | `GET /transcriptions/{task_id}/download` | GET | 下載轉錄結果 | 🔴 高 |
| `GET /transcribe/{task_id}/audio` | `GET /transcriptions/{task_id}/audio` | GET | 下載原始音檔 | 🟡 中 |
| `GET /transcribe/{task_id}/segments` | `GET /transcriptions/{task_id}/segments` | GET | 獲取時間軸片段 | 🟡 中 |
| `PUT /transcribe/{task_id}/content` | `PUT /transcriptions/{task_id}/content` | PUT | 更新轉錄內容 | 🟢 低 |
| `PUT /transcribe/{task_id}/metadata` | `PUT /transcriptions/{task_id}/metadata` | PUT | 更新元數據 | 🟢 低 |

### 2. 任務管理相關

| 舊端點 | 新端點 | 方法 | 說明 | 優先級 |
|--------|--------|------|------|--------|
| `GET /transcribe/active/list` | `GET /tasks?status=active` | GET | 獲取活躍任務列表 | 🔴 高 |
| `GET /transcribe/recent/preview` | `GET /tasks?limit=5` | GET | 獲取最近任務預覽 | 🟡 中 |
| `POST /transcribe/{task_id}/cancel` | `POST /tasks/{task_id}/cancel` | POST | 取消任務 | 🔴 高 |
| `DELETE /transcribe/{task_id}` | `DELETE /tasks/{task_id}` | DELETE | 刪除任務 | 🔴 高 |
| `GET /transcribe/{task_id}/events` | `GET /tasks/{task_id}/events` | GET | SSE 即時狀態 | 🔴 高 |

### 3. 標籤管理相關

| 舊端點 | 新端點 | 方法 | 說明 | 優先級 |
|--------|--------|------|------|--------|
| `PUT /transcribe/{task_id}/tags` | ⚠️ 保持不變（舊端點） | PUT | 更新任務標籤 | 🟢 低 |
| `PUT /transcribe/{task_id}/keep-audio` | ⚠️ 保持不變（舊端點） | PUT | 更新音檔保留狀態 | 🟢 低 |
| `POST /transcribe/batch/delete` | ⚠️ 保持不變（舊端點） | POST | 批次刪除任務 | 🟢 低 |
| `POST /transcribe/batch/tags/add` | ⚠️ 保持不變（舊端點） | POST | 批次添加標籤 | 🟢 低 |
| `POST /transcribe/batch/tags/remove` | ⚠️ 保持不變（舊端點） | POST | 批次移除標籤 | 🟢 低 |

**注意**：標籤管理相關的舊端點目前仍然可用，可以在後續階段遷移。

---

## 🎯 遷移策略

### 階段 1：核心功能遷移（優先級 🔴 高）

**目標**：遷移最常用的任務管理和轉錄端點

**涉及檔案**：
- `frontend/src/views/TranscriptionView.vue`
- `frontend/src/views/TasksView.vue`
- `frontend/src/views/TranscriptDetailView.vue`

**遷移端點**：
1. ✅ `POST /transcribe` → `POST /transcriptions`
2. ✅ `GET /transcribe/{task_id}/download` → `GET /transcriptions/{task_id}/download`
3. ✅ `POST /transcribe/{task_id}/cancel` → `POST /tasks/{task_id}/cancel`
4. ✅ `DELETE /transcribe/{task_id}` → `DELETE /tasks/{task_id}`
5. ✅ `GET /transcribe/active/list` → `GET /tasks?status=active`
6. ✅ `GET /transcribe/{task_id}/events` → `GET /tasks/{task_id}/events`

### 階段 2：次要功能遷移（優先級 🟡 中）

**涉及檔案**：
- `frontend/src/views/TranscriptionView.vue`
- `frontend/src/components/shared/Navigation.vue`

**遷移端點**：
1. ✅ `GET /transcribe/{task_id}/audio` → `GET /transcriptions/{task_id}/audio`
2. ✅ `GET /transcribe/{task_id}/segments` → `GET /transcriptions/{task_id}/segments`
3. ✅ `GET /transcribe/recent/preview` → `GET /tasks?limit=5`

### 階段 3：編輯功能和批次操作（優先級 🟢 低）

**涉及檔案**：
- `frontend/src/views/TranscriptionView.vue`
- `frontend/src/views/TranscriptDetailView.vue`
- `frontend/src/components/TaskList.vue`

**遷移端點**：
1. ⏸️ `PUT /transcribe/{task_id}/content` → `PUT /transcriptions/{task_id}/content`
2. ⏸️ `PUT /transcribe/{task_id}/metadata` → `PUT /transcriptions/{task_id}/metadata`
3. ⏸️ 批次操作端點（保持舊端點，後續考慮）

---

## 📝 詳細遷移步驟

### 步驟 1：創建 API 常量檔案

創建 `frontend/src/api/endpoints.js` 統一管理端點：

```javascript
// frontend/src/api/endpoints.js

/**
 * 新架構 API 端點
 */
export const NEW_ENDPOINTS = {
  // 轉錄相關
  transcriptions: {
    create: '/transcriptions',
    download: (taskId) => `/transcriptions/${taskId}/download`,
    audio: (taskId) => `/transcriptions/${taskId}/audio`,
    segments: (taskId) => `/transcriptions/${taskId}/segments`,
    updateContent: (taskId) => `/transcriptions/${taskId}/content`,
    updateMetadata: (taskId) => `/transcriptions/${taskId}/metadata`,
  },

  // 任務管理
  tasks: {
    list: '/tasks',
    get: (taskId) => `/tasks/${taskId}`,
    cancel: (taskId) => `/tasks/${taskId}/cancel`,
    delete: (taskId) => `/tasks/${taskId}`,
    events: (taskId) => `/tasks/${taskId}/events`,
  },

  // 標籤管理
  tags: {
    list: '/api/tags',
    get: (tagId) => `/api/tags/${tagId}`,
    create: '/api/tags',
    update: (tagId) => `/api/tags/${tagId}`,
    delete: (tagId) => `/api/tags/${tagId}`,
    updateOrder: '/api/tags/order',
    statistics: '/api/tags/statistics',
  },
}

/**
 * 舊端點（向後兼容，逐步棄用）
 */
export const OLD_ENDPOINTS = {
  transcribe: '/transcribe',
  transcribeDownload: (taskId) => `/transcribe/${taskId}/download`,
  transcribeAudio: (taskId) => `/transcribe/${taskId}/audio`,
  transcribeSegments: (taskId) => `/transcribe/${taskId}/segments`,
  transcribeCancel: (taskId) => `/transcribe/${taskId}/cancel`,
  transcribeDelete: (taskId) => `/transcribe/${taskId}`,
  transcribeActiveList: '/transcribe/active/list',
  transcribeRecentPreview: '/transcribe/recent/preview',
  transcribeEvents: (taskId) => `/transcribe/${taskId}/events`,
  transcribeUpdateContent: (taskId) => `/transcribe/${taskId}/content`,
  transcribeUpdateMetadata: (taskId) => `/transcribe/${taskId}/metadata`,
  transcribeUpdateTags: (taskId) => `/transcribe/${taskId}/tags`,
  transcribeUpdateKeepAudio: (taskId) => `/transcribe/${taskId}/keep-audio`,
  transcribeBatchDelete: '/transcribe/batch/delete',
  transcribeBatchTagsAdd: '/transcribe/batch/tags/add',
  transcribeBatchTagsRemove: '/transcribe/batch/tags/remove',
}

/**
 * 遷移輔助函數：使用新端點，失敗時回退到舊端點
 */
export function useEndpoint(newEndpoint, oldEndpoint) {
  // 可以通過環境變數控制是否使用新端點
  const USE_NEW_API = import.meta.env.VITE_USE_NEW_API !== 'false'
  return USE_NEW_API ? newEndpoint : oldEndpoint
}
```

### 步驟 2：創建 API 服務層

創建 `frontend/src/api/services.js`：

```javascript
// frontend/src/api/services.js
import api from '@/utils/axios'
import { NEW_ENDPOINTS } from './endpoints'

/**
 * 轉錄服務
 */
export const transcriptionService = {
  /**
   * 建立轉錄任務
   */
  async create(formData) {
    const response = await api.post(NEW_ENDPOINTS.transcriptions.create, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
  },

  /**
   * 下載轉錄結果
   */
  async download(taskId) {
    const response = await api.get(NEW_ENDPOINTS.transcriptions.download(taskId), {
      responseType: 'blob'
    })
    return response
  },

  /**
   * 獲取音檔 URL
   */
  getAudioUrl(taskId, token) {
    const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?token=${encodeURIComponent(token)}`
  },

  /**
   * 獲取時間軸片段
   */
  async getSegments(taskId) {
    const response = await api.get(NEW_ENDPOINTS.transcriptions.segments(taskId))
    return response.data
  },

  /**
   * 更新轉錄內容
   */
  async updateContent(taskId, content) {
    const response = await api.put(NEW_ENDPOINTS.transcriptions.updateContent(taskId), {
      content
    })
    return response.data
  },

  /**
   * 更新元數據
   */
  async updateMetadata(taskId, metadata) {
    const response = await api.put(NEW_ENDPOINTS.transcriptions.updateMetadata(taskId), metadata)
    return response.data
  },
}

/**
 * 任務服務
 */
export const taskService = {
  /**
   * 獲取任務列表
   */
  async list(params = {}) {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, { params })
    return response.data
  },

  /**
   * 獲取活躍任務列表
   */
  async getActiveList() {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, {
      params: { status: 'active' }
    })
    // 轉換為舊格式以保持兼容性
    return {
      all_tasks: response.data.tasks || response.data,
      total: response.data.total || (response.data.tasks?.length || 0)
    }
  },

  /**
   * 獲取最近任務預覽
   */
  async getRecentPreview() {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, {
      params: { limit: 5 }
    })
    return response.data
  },

  /**
   * 取消任務
   */
  async cancel(taskId) {
    const response = await api.post(NEW_ENDPOINTS.tasks.cancel(taskId))
    return response.data
  },

  /**
   * 刪除任務
   */
  async delete(taskId) {
    const response = await api.delete(NEW_ENDPOINTS.tasks.delete(taskId))
    return response.data
  },

  /**
   * 獲取 SSE 事件 URL
   */
  getEventsUrl(taskId, token) {
    const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    return `${API_BASE}${NEW_ENDPOINTS.tasks.events(taskId)}?token=${token}`
  },
}

/**
 * 標籤服務
 */
export const tagService = {
  /**
   * 獲取所有標籤
   */
  async list() {
    const response = await api.get(NEW_ENDPOINTS.tags.list)
    return response.data
  },

  /**
   * 建立標籤
   */
  async create(tagData) {
    const response = await api.post(NEW_ENDPOINTS.tags.create, tagData)
    return response.data
  },

  /**
   * 更新標籤
   */
  async update(tagId, tagData) {
    const response = await api.put(NEW_ENDPOINTS.tags.update(tagId), tagData)
    return response.data
  },

  /**
   * 刪除標籤
   */
  async delete(tagId) {
    const response = await api.delete(NEW_ENDPOINTS.tags.delete(tagId))
    return response.data
  },

  /**
   * 獲取標籤統計
   */
  async getStatistics() {
    const response = await api.get(NEW_ENDPOINTS.tags.statistics)
    return response.data
  },
}
```

### 步驟 3：更新 TranscriptionView.vue

**修改建立轉錄任務的函數**：

```javascript
// 修改前
import api from '@/utils/axios'

async function submitTranscription() {
  const formData = new FormData()
  // ... 添加表單資料

  try {
    const response = await api.post('/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    // ...
  } catch (error) {
    // ...
  }
}
```

```javascript
// 修改後
import { transcriptionService } from '@/api/services'

async function submitTranscription() {
  const formData = new FormData()
  // ... 添加表單資料

  try {
    const response = await transcriptionService.create(formData)
    // ...
  } catch (error) {
    // ...
  }
}
```

**修改刷新任務列表的函數**：

```javascript
// 修改前
async function refreshTasks() {
  try {
    const response = await api.get('/transcribe/active/list')
    const serverTasks = response.data.all_tasks || []
    // ...
  }
}
```

```javascript
// 修改後
import { taskService } from '@/api/services'

async function refreshTasks() {
  try {
    const response = await taskService.getActiveList()
    const serverTasks = response.all_tasks || []
    // ...
  }
}
```

**修改下載轉錄結果的函數**：

```javascript
// 修改前
async function downloadTranscript(taskId) {
  try {
    const response = await api.get(`/transcribe/${taskId}/download`, {
      responseType: 'blob'
    })
    // ...
  }
}
```

```javascript
// 修改後
async function downloadTranscript(taskId) {
  try {
    const response = await transcriptionService.download(taskId)
    // ...
  }
}
```

**修改取消任務的函數**：

```javascript
// 修改前
async function cancelTask(taskId) {
  await api.post(`/transcribe/${taskId}/cancel`)
}
```

```javascript
// 修改後
async function cancelTask(taskId) {
  await taskService.cancel(taskId)
}
```

**修改刪除任務的函數**：

```javascript
// 修改前
async function deleteTask(taskId) {
  await api.delete(`/transcribe/${taskId}`)
}
```

```javascript
// 修改後
async function deleteTask(taskId) {
  await taskService.delete(taskId)
}
```

**修改 SSE 連接 URL**：

```javascript
// 修改前
const url = `${API_BASE}/transcribe/${taskId}/events?token=${token}`
```

```javascript
// 修改後
import { taskService } from '@/api/services'

const url = taskService.getEventsUrl(taskId, token)
```

**修改獲取音檔 URL**：

```javascript
// 修改前
function getAudioUrl(taskId) {
  const token = localStorage.getItem('access_token')
  if (!token || !taskId) {
    return ''
  }
  return `${API_BASE}/transcribe/${taskId}/audio?token=${encodeURIComponent(token)}`
}
```

```javascript
// 修改後
import { transcriptionService } from '@/api/services'

function getAudioUrl(taskId) {
  const token = localStorage.getItem('access_token')
  if (!token || !taskId) {
    return ''
  }
  return transcriptionService.getAudioUrl(taskId, token)
}
```

### 步驟 4：更新 TasksView.vue

類似的修改，使用 `taskService` 和 `transcriptionService`。

### 步驟 5：更新 TranscriptDetailView.vue

類似的修改，使用 `taskService` 和 `transcriptionService`。

### 步驟 6：更新 Navigation.vue

```javascript
// 修改前
const response = await api.get('/transcribe/recent/preview')
```

```javascript
// 修改後
import { taskService } from '@/api/services'

const response = await taskService.getRecentPreview()
```

---

## 🧪 測試計劃

### 1. 單元測試

為每個 API 服務函數編寫測試：

```javascript
// tests/api/services.test.js
import { describe, it, expect, vi } from 'vitest'
import { transcriptionService, taskService } from '@/api/services'

describe('transcriptionService', () => {
  it('should create transcription task', async () => {
    const formData = new FormData()
    formData.append('file', new Blob(['test']))

    const result = await transcriptionService.create(formData)
    expect(result).toBeDefined()
  })

  it('should download transcription result', async () => {
    const result = await transcriptionService.download('test123')
    expect(result).toBeDefined()
  })
})

describe('taskService', () => {
  it('should get active task list', async () => {
    const result = await taskService.getActiveList()
    expect(result.all_tasks).toBeDefined()
  })

  it('should cancel task', async () => {
    const result = await taskService.cancel('test123')
    expect(result).toBeDefined()
  })
})
```

### 2. 集成測試

測試前端與新端點的完整流程：

1. ✅ 上傳音檔 → 建立轉錄任務
2. ✅ 監聽 SSE → 獲取即時進度
3. ✅ 下載結果 → 驗證文件完整性
4. ✅ 取消任務 → 驗證狀態更新
5. ✅ 刪除任務 → 驗證任務移除

### 3. 手動測試檢查清單

- [ ] 上傳音檔並建立轉錄任務
- [ ] 查看任務列表（活躍任務）
- [ ] 觀察即時進度更新（SSE）
- [ ] 下載轉錄結果
- [ ] 播放原始音檔
- [ ] 查看時間軸片段
- [ ] 編輯轉錄內容
- [ ] 更新任務元數據
- [ ] 取消進行中的任務
- [ ] 刪除已完成的任務

---

## 🔄 回退計劃

如果新端點出現問題，可以快速回退到舊端點：

### 方法 1：環境變數控制

在 `.env` 中設定：

```env
# 使用新 API（預設）
VITE_USE_NEW_API=true

# 回退到舊 API
VITE_USE_NEW_API=false
```

### 方法 2：條件判斷

在 `endpoints.js` 中添加：

```javascript
export function getEndpoint(feature) {
  const USE_NEW_API = import.meta.env.VITE_USE_NEW_API !== 'false'

  if (USE_NEW_API) {
    return NEW_ENDPOINTS
  } else {
    return OLD_ENDPOINTS
  }
}
```

---

## 📅 遷移時程表

| 階段 | 時間 | 任務 | 負責人 |
|------|------|------|--------|
| **第 1 週** | - | 建立 API 服務層 | - |
| **第 2 週** | - | 遷移核心功能（階段 1） | - |
| **第 3 週** | - | 遷移次要功能（階段 2） | - |
| **第 4 週** | - | 測試與驗證 | - |
| **第 5 週** | - | 遷移編輯功能（階段 3）| - |
| **第 6 週** | - | 最終測試與部署 | - |

---

## ✅ 完成檢查清單

### 階段 1：準備工作
- [ ] 創建 `frontend/src/api/endpoints.js`
- [ ] 創建 `frontend/src/api/services.js`
- [ ] 配置環境變數 `VITE_USE_NEW_API`

### 階段 2：核心功能遷移
- [ ] TranscriptionView.vue - 建立轉錄任務
- [ ] TranscriptionView.vue - 刷新任務列表
- [ ] TranscriptionView.vue - 下載轉錄結果
- [ ] TranscriptionView.vue - 取消任務
- [ ] TranscriptionView.vue - 刪除任務
- [ ] TranscriptionView.vue - SSE 連接
- [ ] TasksView.vue - 任務列表
- [ ] TasksView.vue - 任務操作

### 階段 3：次要功能遷移
- [ ] TranscriptionView.vue - 獲取音檔 URL
- [ ] TranscriptionView.vue - 獲取時間軸片段
- [ ] Navigation.vue - 最近任務預覽

### 階段 4：測試驗證
- [ ] 單元測試
- [ ] 集成測試
- [ ] 手動測試
- [ ] 效能測試

### 階段 5：部署上線
- [ ] 更新部署腳本
- [ ] 更新環境變數
- [ ] 灰度發布（10% → 50% → 100%）
- [ ] 監控與日誌

---

## 📞 支援與問題回報

如果在遷移過程中遇到問題：

1. 檢查 `.env` 配置是否正確
2. 查看瀏覽器控制台錯誤訊息
3. 檢查後端日誌（`/health` 端點）
4. 回退到舊端點（設定 `VITE_USE_NEW_API=false`）

---

## 📚 參考資源

- [ARCHITECTURE.md](./ARCHITECTURE.md) - 後端架構說明
- [REFACTORING_SUMMARY.md](./REFACTORING_SUMMARY.md) - 重構總結
- [FastAPI 文檔](https://fastapi.tiangolo.com/)
- [Vue 3 文檔](https://vuejs.org/)

---

**最後更新**：2025-12-23
**版本**：v1.0.0
