<template>
  <div class="audit-logs-container">
    <!-- 導航 -->
    <AdminNav />

    <h1 class="page-title">操作記錄 Audit Logs</h1>

    <!-- 過濾器（forensics 多維篩選；時間範圍必帶、上限 90 天） -->
    <div class="filters">
      <div class="filter-item">
        <label>時間範圍：</label>
        <select v-model="preset" @change="onPresetChange" class="filter-select">
          <option value="24h">近 24 小時</option>
          <option value="7d">近 7 天</option>
          <option value="30d">近 30 天</option>
          <option value="custom">自訂區間</option>
        </select>
      </div>
      <template v-if="preset === 'custom'">
        <div class="filter-item">
          <label>起：</label>
          <input type="datetime-local" v-model="fromLocal" class="filter-input" />
        </div>
        <div class="filter-item">
          <label>迄：</label>
          <input type="datetime-local" v-model="toLocal" class="filter-input" />
        </div>
      </template>

      <div class="filter-item">
        <label>操作者：</label>
        <input
          v-model="actor"
          @keyup.enter="applyFilters"
          placeholder="email 或 user ID"
          class="filter-input"
        />
      </div>

      <div class="filter-item">
        <MultiSelect label="類型" :options="facets.log_types" v-model="logTypes" />
      </div>

      <div class="filter-item">
        <MultiSelect label="操作" :options="facets.actions" v-model="actions" />
      </div>

      <div class="filter-item">
        <MultiSelect label="成敗" :options="statusOptions" v-model="statuses" />
      </div>

      <div class="filter-item">
        <label>狀態碼：</label>
        <input
          v-model="statusCode"
          @keyup.enter="applyFilters"
          placeholder="如 403"
          inputmode="numeric"
          class="filter-input narrow"
        />
      </div>

      <div class="filter-item">
        <label>IP：</label>
        <input
          v-model="ip"
          @keyup.enter="applyFilters"
          placeholder="精確 IP"
          class="filter-input"
        />
      </div>

      <div class="filter-item">
        <label>排序：</label>
        <select v-model="sort" class="filter-select">
          <option value="desc">最新在上</option>
          <option value="asc">最舊在上</option>
        </select>
      </div>

      <button @click="applyFilters" class="filter-btn">🔍 套用篩選</button>
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
        <span class="total-count">共 {{ total }} 筆（第 {{ currentPage }} / {{ totalPages }} 頁）</span>
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
          第 {{ currentPage }} / {{ totalPages }} 頁（每頁 {{ pageSize }} 筆）
        </span>

        <button
          @click="nextPage"
          :disabled="currentPage >= totalPages"
          class="page-btn"
        >
          下一頁 →
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'
import MultiSelect from '../components/shared/MultiSelect.vue'

const route = useRoute()
const router = useRouter()

// 狀態
const logs = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref(null)
const currentPage = ref(1)
const pageSize = ref(50)
const facets = ref({ actions: [], log_types: [] })

// 篩選控制項
const preset = ref('7d')          // 24h / 7d / 30d / custom
const fromLocal = ref('')         // datetime-local（自訂區間用）
const toLocal = ref('')
const actor = ref('')             // email 或 user_id
// 多選（預設全選；類型預設排除 admin）。空陣列/全選皆視為「無約束」= 全部
const logTypes = ref([])
const actions = ref([])
const statuses = ref(['success', 'failed'])
const statusOptions = [
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失敗' },
]
const statusCode = ref('')        // 選填精確碼
const ip = ref('')
const sort = ref('desc')

// 記錄多選是否已由 URL 指定（是則不套 facets 預設）
let hydratedLogTypes = false
let hydratedActions = false

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

// datetime-local ↔ epoch(秒)，皆本地時區
function localToEpoch(s) {
  if (!s) return undefined
  const t = new Date(s).getTime()
  return Number.isNaN(t) ? undefined : Math.floor(t / 1000)
}

// preset → 實際時間窗（epoch 秒）
function computeRange() {
  const now = Math.floor(Date.now() / 1000)
  if (preset.value === 'custom') {
    return { from: localToEpoch(fromLocal.value), to: localToEpoch(toLocal.value) }
  }
  const span = { '24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400 }[preset.value] || 7 * 86400
  return { from: now - span, to: now }
}

// 成敗多選 → 後端 status 字串：只選一個才是約束；0 或 2 個 = 全部
function deriveStatus() {
  return statuses.value.length === 1 ? statuses.value[0] : 'all'
}

// 多選子集才算約束：非空且未涵蓋全部選項才送（全選/清空 = 無約束 = 全部）
function isSubset(selected, options) {
  return selected.length > 0 && selected.length < options.length
}

function buildParams() {
  const { from, to } = computeRange()
  const p = {
    limit: pageSize.value,
    skip: (currentPage.value - 1) * pageSize.value,
    sort: sort.value,
    status: deriveStatus(),
  }
  if (from) p.from = from
  if (to) p.to = to
  if (actor.value.trim()) p.actor = actor.value.trim()
  if (isSubset(logTypes.value, facets.value.log_types)) p.log_type = logTypes.value
  if (isSubset(actions.value, facets.value.actions)) p.action = actions.value
  if (statusCode.value) p.status_code = Number(statusCode.value)
  if (ip.value.trim()) p.ip = ip.value.trim()
  return p
}

// 把可見篩選條件同步進 URL（可分享、重整不丟）
function syncToUrl() {
  const q = { preset: preset.value }
  if (preset.value === 'custom') {
    if (fromLocal.value) q.from = fromLocal.value
    if (toLocal.value) q.to = toLocal.value
  }
  if (actor.value.trim()) q.actor = actor.value.trim()
  if (isSubset(logTypes.value, facets.value.log_types)) q.log_type = logTypes.value.join(',')
  if (isSubset(actions.value, facets.value.actions)) q.action = actions.value.join(',')
  const st = deriveStatus()
  if (st !== 'all') q.status = st
  if (statusCode.value) q.status_code = statusCode.value
  if (ip.value.trim()) q.ip = ip.value.trim()
  if (sort.value !== 'desc') q.sort = sort.value
  if (currentPage.value > 1) q.page = String(currentPage.value)
  router.replace({ query: q }).catch(() => {})
}

function hydrateFromUrl() {
  const q = route.query
  if (q.preset) preset.value = q.preset
  if (q.from) fromLocal.value = q.from
  if (q.to) toLocal.value = q.to
  if (q.actor) actor.value = q.actor
  if (q.log_type) {
    logTypes.value = String(q.log_type).split(',').filter(Boolean)
    hydratedLogTypes = true
  }
  if (q.action) {
    actions.value = String(q.action).split(',').filter(Boolean)
    hydratedActions = true
  }
  if (q.status) {
    statuses.value = q.status === 'success' ? ['success']
      : q.status === 'failed' ? ['failed'] : ['success', 'failed']
  }
  if (q.status_code) statusCode.value = q.status_code
  if (q.ip) ip.value = q.ip
  if (q.sort) sort.value = q.sort
  if (q.page) currentPage.value = Math.max(1, parseInt(q.page, 10) || 1)
}

async function fetchLogs() {
  loading.value = true
  error.value = null
  try {
    const response = await api.get('/api/admin/audit-logs', {
      params: buildParams(),
      paramsSerializer: { indexes: null },  // 陣列 → log_type=a&log_type=b（對上 FastAPI）
    })
    logs.value = response.data.logs || []
    total.value = response.data.total || 0
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
    console.error('載入 audit logs 失敗:', err)
  } finally {
    loading.value = false
  }
}

async function fetchFacets() {
  try {
    const response = await api.get('/api/admin/audit-logs/facets')
    facets.value = {
      actions: response.data.actions || [],
      log_types: response.data.log_types || [],
    }
  } catch (err) {
    console.error('載入 facets 失敗:', err)
  }
}

// 套用篩選（explicit apply）：回第一頁 + 同步 URL + 重抓
function applyFilters() {
  currentPage.value = 1
  syncToUrl()
  fetchLogs()
}

function onPresetChange() {
  if (preset.value !== 'custom') {
    fromLocal.value = ''
    toLocal.value = ''
  }
  applyFilters()
}

// 依 facets 套多選預設：類型排除 admin、操作全選、成敗全選
function applyMultiDefaults() {
  logTypes.value = facets.value.log_types.filter((t) => t !== 'admin')
  actions.value = [...facets.value.actions]
  statuses.value = ['success', 'failed']
}

function clearFilters() {
  preset.value = '7d'
  fromLocal.value = ''
  toLocal.value = ''
  actor.value = ''
  applyMultiDefaults()
  statusCode.value = ''
  ip.value = ''
  sort.value = 'desc'
  applyFilters()
}

function previousPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    syncToUrl()
    fetchLogs()
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    syncToUrl()
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

onMounted(async () => {
  hydrateFromUrl()          // 先從 URL 還原（可能設好多選 + 標記 hydrated）
  await fetchFacets()       // 確保 facets 到位，buildParams 的「子集判定」才準
  // 未由 URL 指定的多選 → 套 facets 預設（類型去 admin、其餘全選）
  if (!hydratedLogTypes) logTypes.value = facets.value.log_types.filter((t) => t !== 'admin')
  if (!hydratedActions) actions.value = [...facets.value.actions]
  fetchLogs()
})
</script>

<style scoped>
.audit-logs-container {
  max-width: none;
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
.filter-input.narrow { min-width: 90px; }

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
