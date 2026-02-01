<template>
  <div class="audit-logs-container">
    <!-- 導航 -->
    <AdminNav />

    <h1 class="page-title">操作記錄 Audit Logs</h1>

    <!-- 過濾器 -->
    <div class="filters">
      <div class="filter-item">
        <label>日誌類型：</label>
        <select v-model="filters.log_type" @change="resetAndFetch" class="filter-select">
          <option value="">全部</option>
          <option value="auth">認證 (auth)</option>
          <option value="task">任務 (task)</option>
          <option value="transcription">轉錄 (transcription)</option>
          <option value="tag">標籤 (tag)</option>
          <option value="admin">管理 (admin)</option>
          <option value="file">檔案 (file)</option>
        </select>
      </div>

      <div class="filter-item">
        <label>用戶 ID：</label>
        <input
          v-model="filters.user_id"
          @keyup.enter="resetAndFetch"
          placeholder="輸入用戶 ID"
          class="filter-input"
        />
      </div>

      <button @click="resetAndFetch" class="filter-btn">🔍 套用篩選</button>
      <button @click="clearFilters" class="filter-btn secondary">✕ 清除</button>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入操作記錄中...</p>
    </div>

    <!-- 錯誤訊息 -->
    <div v-else-if="error" class="error-message">
      ❌ {{ error }}
    </div>

    <!-- 記錄列表 -->
    <div v-else class="logs-section">
      <div class="logs-header">
        <span class="total-count">共 {{ logs.length }} 筆記錄（第 {{ currentPage }} 頁）</span>
        <button @click="fetchLogs" class="refresh-btn">🔄 刷新</button>
      </div>

      <div v-if="logs.length === 0" class="empty-state">
        📭 目前沒有操作記錄
      </div>

      <div v-else class="logs-table-wrapper">
        <table class="logs-table">
          <thead>
            <tr>
              <th>時間</th>
              <th>類型</th>
              <th>操作</th>
              <th>用戶 ID</th>
              <th>狀態碼</th>
              <th>IP 地址</th>
              <th>路徑</th>
              <th>訊息</th>
              <th>處理時間</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="log in logs"
              :key="log._id"
              :class="{'failed-row': log.status_code >= 400}"
            >
              <td class="timestamp">{{ formatTimestamp(log.timestamp) }}</td>
              <td>
                <span class="log-type-badge" :class="`type-${log.log_type}`">
                  {{ log.log_type }}
                </span>
              </td>
              <td class="action">{{ log.action }}</td>
              <td>
                <code v-if="log.user_id" class="user-id">{{ truncateId(log.user_id) }}</code>
                <span v-else class="null-value">-</span>
              </td>
              <td>
                <span class="status-badge" :class="getStatusClass(log.status_code)">
                  {{ log.status_code }}
                </span>
              </td>
              <td class="ip">{{ log.ip_address }}</td>
              <td class="path" :title="log.path">{{ truncatePath(log.path) }}</td>
              <td class="message">{{ log.response_message || '-' }}</td>
              <td class="duration">
                {{ log.duration_ms ? `${log.duration_ms}ms` : '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分頁控制 -->
      <div class="pagination">
        <button
          @click="previousPage"
          :disabled="currentPage === 1"
          class="page-btn"
        >
          ← 上一頁
        </button>

        <span class="page-info">
          第 {{ currentPage }} 頁（每頁 {{ pageSize }} 筆）
        </span>

        <button
          @click="nextPage"
          :disabled="logs.length < pageSize"
          class="page-btn"
        >
          下一頁 →
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

// 狀態
const logs = ref([])
const loading = ref(true)
const error = ref(null)
const currentPage = ref(1)
const pageSize = ref(50)

// 過濾條件
const filters = ref({
  log_type: '',
  user_id: ''
})

// 獲取 audit logs
async function fetchLogs() {
  loading.value = true
  error.value = null

  try {
    const skip = (currentPage.value - 1) * pageSize.value
    const params = {
      limit: pageSize.value,
      skip: skip
    }

    // 添加過濾條件
    if (filters.value.log_type) {
      params.log_type = filters.value.log_type
    }
    if (filters.value.user_id) {
      params.user_id = filters.value.user_id.trim()
    }

    const response = await api.get('/api/admin/audit-logs', { params })
    logs.value = response.data.logs || []
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
    console.error('載入 audit logs 失敗:', err)
  } finally {
    loading.value = false
  }
}

// 重置並重新獲取
function resetAndFetch() {
  currentPage.value = 1
  fetchLogs()
}

// 清除過濾器
function clearFilters() {
  filters.value.log_type = ''
  filters.value.user_id = ''
  resetAndFetch()
}

// 上一頁
function previousPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    fetchLogs()
  }
}

// 下一頁
function nextPage() {
  if (logs.value.length === pageSize.value) {
    currentPage.value++
    fetchLogs()
  }
}

// 格式化時間戳記
function formatTimestamp(timestamp) {
  if (!timestamp) return '-'

  // 處理 Unix timestamp（數字）或字串格式
  let date
  if (typeof timestamp === 'number') {
    // Unix timestamp（秒）
    date = new Date(timestamp * 1000)
  } else if (typeof timestamp === 'string') {
    // 字串格式，直接返回
    return timestamp
  } else {
    return '-'
  }

  // 格式化為本地時間
  return date.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

// 截斷用戶 ID（顯示前 8 位）
function truncateId(id) {
  if (!id) return '-'
  return id.length > 8 ? `${id.substring(0, 8)}...` : id
}

// 截斷路徑
function truncatePath(path) {
  if (!path) return '-'
  return path.length > 40 ? `...${path.substring(path.length - 37)}` : path
}

// 獲取狀態碼樣式類別
function getStatusClass(statusCode) {
  if (statusCode >= 200 && statusCode < 300) return 'status-success'
  if (statusCode >= 300 && statusCode < 400) return 'status-redirect'
  if (statusCode >= 400 && statusCode < 500) return 'status-client-error'
  if (statusCode >= 500) return 'status-server-error'
  return ''
}

onMounted(() => {
  fetchLogs()
})
</script>

<style scoped>
.audit-logs-container {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 20px 40px;
}

.page-title {
  text-align: center;
  color: var(--color-text, rgb(145, 106, 45));
  margin-bottom: 24px;
  font-weight: 700;
  font-size: 1.75rem;
}

/* 過濾器 */
.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  background: white;
  padding: 16px 20px;
  border-radius: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(163, 177, 198, 0.2);
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-item label {
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  white-space: nowrap;
  font-size: 14px;
}

.filter-select,
.filter-input {
  padding: 8px 12px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 8px;
  background: white;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.filter-select { min-width: 140px; }
.filter-input { min-width: 180px; }

.filter-select:focus,
.filter-input:focus {
  border-color: var(--color-primary, #dd8448);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.12);
}

.filter-btn {
  padding: 8px 16px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}

.filter-btn:hover {
  background: var(--color-primary-dark, #b8762d);
}

.filter-btn.secondary {
  background: #fff5f5;
  color: #c62828;
  border: 1px solid rgba(198, 40, 40, 0.2);
}

.filter-btn.secondary:hover {
  background: #ffebee;
}

/* 記錄列表 */
.logs-section {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(163, 177, 198, 0.2);
}

.logs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.total-count {
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 14px;
}

.refresh-btn {
  padding: 8px 14px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: var(--color-primary-dark, #b8762d);
}

.empty-state {
  text-align: center;
  padding: 60px;
  font-size: 16px;
  color: var(--color-text-light, #a0917c);
}

/* 表格 */
.logs-table-wrapper {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.logs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.logs-table th {
  background: #fafafa;
  padding: 12px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
  position: sticky;
  top: 0;
  white-space: nowrap;
  font-size: 12px;
}

.logs-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.1);
  color: var(--color-text, rgb(145, 106, 45));
}

.logs-table tbody tr:hover {
  background: rgba(221, 132, 72, 0.04);
}

.logs-table tbody tr.failed-row {
  background: rgba(198, 40, 40, 0.03);
}

.logs-table tbody tr.failed-row:hover {
  background: rgba(198, 40, 40, 0.06);
}

.timestamp {
  white-space: nowrap;
  font-weight: 500;
  color: var(--color-text-light, #a0917c);
  font-size: 12px;
}

.log-type-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.type-auth { background: #e3f2fd; color: #1565c0; }
.type-task { background: #f3e5f5; color: #7b1fa2; }
.type-transcription { background: #e8f5e9; color: #2e7d32; }
.type-tag { background: #fff3e0; color: #e65100; }
.type-admin { background: #fce4ec; color: #c2185b; }
.type-file { background: #e0f2f1; color: #00695c; }

.action {
  font-weight: 600;
  font-family: monospace;
  font-size: 12px;
}

.user-id {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--color-primary, #dd8448);
  font-family: monospace;
}

.null-value {
  color: var(--color-text-light, #a0917c);
  font-style: italic;
}

.status-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.status-success { background: #d4edda; color: #155724; }
.status-redirect { background: #fff3cd; color: #856404; }
.status-client-error { background: #ffe0b2; color: #e65100; }
.status-server-error { background: #ffebee; color: #c62828; }

.ip {
  font-family: monospace;
  font-size: 12px;
  color: var(--color-text-light, #a0917c);
}

.path {
  font-family: monospace;
  font-size: 11px;
  color: var(--color-text-light, #a0917c);
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.duration {
  font-family: monospace;
  font-size: 12px;
  color: var(--color-text-light, #a0917c);
  text-align: right;
}

/* 分頁控制 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
}

.page-btn {
  padding: 8px 16px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: var(--color-primary-dark, #b8762d);
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-weight: 500;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 13px;
}

@media (max-width: 1200px) {
  .logs-table { font-size: 12px; }
  .logs-table th, .logs-table td { padding: 8px; }
}

@media (max-width: 768px) {
  .filters {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-item {
    flex-direction: column;
    align-items: stretch;
  }

  .filter-select,
  .filter-input {
    width: 100%;
  }
}
</style>
