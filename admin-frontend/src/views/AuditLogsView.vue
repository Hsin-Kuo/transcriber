<template>
  <div class="audit-logs-container">
    <!-- 導航 -->
    <nav class="admin-nav">
      <router-link to="/" class="nav-link" exact-active-class="active">
        📊 系統統計
      </router-link>
      <router-link to="/audit-logs" class="nav-link" exact-active-class="active">
        📝 操作記錄
      </router-link>
    </nav>

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
  // timestamp 格式: "2025-01-01 12:34:56"
  return timestamp.replace(' ', ' ')
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
  padding: 20px;
}

/* 導航 */
.admin-nav {
  display: flex;
  gap: 15px;
  margin-bottom: 30px;
  background: var(--main-bg);
  padding: 15px 20px;
  border-radius: 20px;
  justify-content: center;
}

.nav-link {
  padding: 12px 24px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--main-text);
  text-decoration: none;
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.3s;
}

.nav-link:hover {
  transform: translateY(-2px);
}

.nav-link.active {
  background: linear-gradient(145deg, var(--main-primary-light), var(--main-primary));
  color: white;
}

.page-title {
  text-align: center;
  color: var(--main-primary);
  margin-bottom: 30px;
  font-weight: 700;
  font-size: 28px;
}

/* 過濾器 */
.filters {
  display: flex;
  gap: 15px;
  align-items: center;
  background: var(--main-bg);
  padding: 20px;
  border-radius: 20px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-item label {
  font-weight: 600;
  color: var(--main-text);
  white-space: nowrap;
}

.filter-select,
.filter-input {
  padding: 8px 12px;
  border: none;
  border-radius: 12px;
  background: var(--main-bg);
  color: var(--main-text);
  box-shadow:
    inset 3px 3px 6px var(--main-shadow-dark),
    inset -3px -3px 6px var(--main-shadow-light);
  font-size: 14px;
  outline: none;
  transition: all 0.3s;
}

.filter-select {
  min-width: 150px;
}

.filter-input {
  min-width: 200px;
}

.filter-select:focus,
.filter-input:focus {
  box-shadow:
    inset 2px 2px 4px var(--main-shadow-dark),
    inset -2px -2px 4px var(--main-shadow-light);
}

.filter-btn {
  padding: 8px 16px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--main-primary);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  transition: all 0.3s;
}

.filter-btn:hover {
  transform: translateY(-2px);
}

.filter-btn.secondary {
  background: linear-gradient(145deg, #f0e9e9, #e0d3d3);
  color: #c62828;
}

/* 載入和錯誤狀態 */
.loading, .error-message {
  text-align: center;
  padding: 40px;
  font-size: 18px;
  color: var(--main-text);
}

.spinner {
  border: 4px solid transparent;
  border-top: 4px solid var(--main-primary);
  border-right: 4px solid var(--main-primary-light);
  border-radius: 50%;
  width: 40px;
  height: 40px;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* 記錄列表 */
.logs-section {
  background: var(--main-bg);
  border-radius: 20px;
  padding: 24px;
}

.logs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.total-count {
  font-weight: 600;
  color: var(--main-text);
  font-size: 16px;
}

.refresh-btn {
  padding: 8px 16px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--main-primary);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  transition: all 0.3s;
}

.refresh-btn:hover {
  transform: translateY(-2px);
}

.empty-state {
  text-align: center;
  padding: 60px;
  font-size: 20px;
  color: var(--main-text-light);
}

/* 表格 */
.logs-table-wrapper {
  overflow-x: auto;
  border-radius: 12px;
  box-shadow:
    inset 2px 2px 4px var(--main-shadow-dark),
    inset -2px -2px 4px var(--main-shadow-light);
}

.logs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.logs-table th {
  background: var(--main-bg);
  padding: 14px 12px;
  text-align: left;
  font-weight: 700;
  color: var(--main-primary);
  border-bottom: 2px solid rgba(163, 177, 198, 0.3);
  position: sticky;
  top: 0;
  white-space: nowrap;
}

.logs-table td {
  padding: 12px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.15);
  color: var(--main-text);
}

.logs-table tbody tr {
  transition: background 0.2s;
}

.logs-table tbody tr:hover {
  background: rgba(163, 177, 198, 0.08);
}

.logs-table tbody tr.failed-row {
  background: rgba(198, 40, 40, 0.05);
}

.logs-table tbody tr.failed-row:hover {
  background: rgba(198, 40, 40, 0.1);
}

/* 特殊欄位樣式 */
.timestamp {
  white-space: nowrap;
  font-weight: 600;
  color: var(--main-text-light);
  font-size: 12px;
}

.log-type-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  box-shadow:
    inset 2px 2px 4px rgba(0, 0, 0, 0.1),
    inset -2px -2px 4px rgba(255, 255, 255, 0.3);
}

.type-auth { background: #e3f2fd; color: #1976d2; }
.type-task { background: #f3e5f5; color: #7b1fa2; }
.type-transcription { background: #e8f5e9; color: #388e3c; }
.type-tag { background: #fff3e0; color: #f57c00; }
.type-admin { background: #fce4ec; color: #c2185b; }
.type-file { background: #e0f2f1; color: #00796b; }

.action {
  font-weight: 600;
  font-family: monospace;
  font-size: 12px;
}

.user-id {
  background: var(--main-bg);
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  color: var(--main-primary);
  box-shadow:
    inset 2px 2px 4px var(--main-shadow-dark),
    inset -2px -2px 4px var(--main-shadow-light);
}

.null-value {
  color: var(--main-text-light);
  font-style: italic;
}

.status-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 700;
  box-shadow:
    inset 2px 2px 4px rgba(0, 0, 0, 0.1),
    inset -2px -2px 4px rgba(255, 255, 255, 0.3);
}

.status-success {
  background: #c8e6c9;
  color: #2e7d32;
}

.status-redirect {
  background: #fff9c4;
  color: #f57f17;
}

.status-client-error {
  background: #ffccbc;
  color: #d84315;
}

.status-server-error {
  background: #ffcdd2;
  color: #c62828;
}

.ip {
  font-family: monospace;
  font-size: 12px;
  color: var(--main-text-light);
}

.path {
  font-family: monospace;
  font-size: 11px;
  color: var(--main-text-light);
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
  color: var(--main-text-light);
  text-align: right;
}

/* 分頁控制 */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  margin-top: 30px;
  padding-top: 20px;
  border-top: 2px solid rgba(163, 177, 198, 0.2);
}

.page-btn {
  padding: 10px 20px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--main-primary);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  transition: all 0.3s;
}

.page-btn:hover:not(:disabled) {
  transform: translateY(-2px);
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.page-info {
  font-weight: 600;
  color: var(--main-text);
  font-size: 14px;
}

/* 響應式設計 */
@media (max-width: 1200px) {
  .logs-table {
    font-size: 12px;
  }

  .logs-table th,
  .logs-table td {
    padding: 8px;
  }
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

  .logs-table-wrapper {
    font-size: 11px;
  }
}
</style>
