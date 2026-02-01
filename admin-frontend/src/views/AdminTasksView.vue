<template>
  <div class="tasks-container">
    <!-- 導航 -->
    <AdminNav />

    <h1 class="page-title">任務管理</h1>

    <!-- 篩選器 -->
    <div class="filters">
      <div class="filter-item">
        <label>搜尋：</label>
        <input
          v-model="filters.search"
          @keyup.enter="fetchTasks"
          placeholder="檔名或 Task ID"
          class="filter-input"
        />
      </div>

      <div class="filter-item">
        <label>用戶：</label>
        <input
          v-model="filters.user_email"
          @keyup.enter="fetchTasks"
          placeholder="用戶 Email"
          class="filter-input"
        />
      </div>

      <div class="filter-item">
        <label>狀態：</label>
        <select v-model="filters.status" @change="fetchTasks" class="filter-select">
          <option value="">全部</option>
          <option value="active">進行中</option>
          <option value="pending">等待中</option>
          <option value="processing">處理中</option>
          <option value="completed">已完成</option>
          <option value="failed">失敗</option>
          <option value="cancelled">已取消</option>
        </select>
      </div>

      <div class="filter-item">
        <label>日期：</label>
        <input
          type="date"
          v-model="filters.date_from"
          @change="fetchTasks"
          class="filter-input date"
        />
        <span>~</span>
        <input
          type="date"
          v-model="filters.date_to"
          @change="fetchTasks"
          class="filter-input date"
        />
      </div>

      <button @click="fetchTasks" class="filter-btn">🔍 搜尋</button>
      <button @click="clearFilters" class="filter-btn secondary">✕ 清除</button>
    </div>

    <!-- 批次操作 -->
    <div v-if="selectedTasks.length > 0" class="batch-actions">
      <span>已選擇 {{ selectedTasks.length }} 個任務</span>
      <button @click="batchDelete" class="batch-btn danger">🗑️ 批次刪除</button>
      <button @click="selectedTasks = []" class="batch-btn">取消選擇</button>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入任務列表中...</p>
    </div>

    <!-- 錯誤訊息 -->
    <div v-else-if="error" class="error-message">
      {{ error }}
    </div>

    <!-- 任務列表 -->
    <div v-else class="tasks-section">
      <div class="tasks-header">
        <span class="total-count">共 {{ total }} 個任務</span>
        <button @click="fetchTasks" class="refresh-btn">🔄 刷新</button>
      </div>

      <div v-if="tasks.length === 0" class="empty-state">
        📭 沒有符合條件的任務
      </div>

      <div v-else class="tasks-table-wrapper">
        <table class="tasks-table">
          <thead>
            <tr>
              <th class="checkbox-col">
                <input type="checkbox" @change="toggleSelectAll" :checked="isAllSelected" />
              </th>
              <th>Task ID</th>
              <th>用戶</th>
              <th>檔名</th>
              <th>狀態</th>
              <th>進度</th>
              <th>音檔時長</th>
              <th>處理時間</th>
              <th>建立時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in tasks" :key="task.task_id">
              <td class="checkbox-col">
                <input
                  type="checkbox"
                  :checked="selectedTasks.includes(task.task_id)"
                  @change="toggleSelect(task.task_id)"
                  :disabled="['pending', 'processing'].includes(task.status)"
                />
              </td>
              <td>
                <router-link :to="`/tasks/${task.task_id}`" class="task-link">
                  {{ task.task_id?.substring(0, 8) }}...
                </router-link>
              </td>
              <td class="user-col">
                <router-link v-if="task.user_id" :to="`/users/${task.user_id}`" class="user-link">
                  {{ task.user_email || task.user_id?.substring(0, 8) }}
                </router-link>
                <span v-else>-</span>
              </td>
              <td class="filename">{{ task.filename || '-' }}</td>
              <td>
                <span class="status-badge" :class="`status-${task.status}`">
                  {{ getStatusName(task.status) }}
                </span>
              </td>
              <td class="progress-col">
                <template v-if="['pending', 'processing'].includes(task.status)">
                  <div class="progress-bar">
                    <div class="progress-fill" :style="{ width: (task.progress_percentage || 0) + '%' }"></div>
                  </div>
                  <span class="progress-text">{{ (task.progress_percentage || 0).toFixed(0) }}%</span>
                </template>
                <span v-else>-</span>
              </td>
              <td>{{ formatDuration(task.audio_duration_seconds) }}</td>
              <td>{{ formatDuration(task.duration_seconds) }}</td>
              <td class="created-at">{{ formatTimestamp(task.created_at) }}</td>
              <td class="actions">
                <router-link :to="`/tasks/${task.task_id}`" class="action-btn view">
                  查看
                </router-link>
                <button
                  v-if="['pending', 'processing'].includes(task.status)"
                  @click="cancelTask(task)"
                  class="action-btn cancel"
                >
                  取消
                </button>
                <button
                  v-else
                  @click="deleteTask(task)"
                  class="action-btn delete"
                >
                  刪除
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分頁 -->
      <div class="pagination">
        <button @click="previousPage" :disabled="currentPage === 1" class="page-btn">
          ← 上一頁
        </button>
        <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 頁</span>
        <button @click="nextPage" :disabled="currentPage >= totalPages" class="page-btn">
          下一頁 →
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

const tasks = ref([])
const loading = ref(true)
const error = ref(null)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(50)
const selectedTasks = ref([])

const filters = ref({
  search: '',
  user_email: '',
  status: '',
  date_from: '',
  date_to: ''
})

const totalPages = computed(() => Math.ceil(total.value / pageSize.value))
const isAllSelected = computed(() => {
  const selectableTasks = tasks.value.filter(t => !['pending', 'processing'].includes(t.status))
  return selectableTasks.length > 0 && selectableTasks.every(t => selectedTasks.value.includes(t.task_id))
})

async function fetchTasks() {
  loading.value = true
  error.value = null

  try {
    const params = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value
    }

    if (filters.value.search) params.search = filters.value.search
    if (filters.value.user_email) params.user_email = filters.value.user_email
    if (filters.value.status) params.status = filters.value.status
    if (filters.value.date_from) params.date_from = filters.value.date_from
    if (filters.value.date_to) params.date_to = filters.value.date_to

    const response = await api.get('/api/admin/tasks', { params })
    tasks.value = response.data.tasks
    total.value = response.data.total
    selectedTasks.value = []
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

function clearFilters() {
  filters.value = { search: '', user_email: '', status: '', date_from: '', date_to: '' }
  currentPage.value = 1
  fetchTasks()
}

function previousPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    fetchTasks()
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    fetchTasks()
  }
}

function toggleSelect(taskId) {
  const index = selectedTasks.value.indexOf(taskId)
  if (index === -1) {
    selectedTasks.value.push(taskId)
  } else {
    selectedTasks.value.splice(index, 1)
  }
}

function toggleSelectAll(event) {
  if (event.target.checked) {
    selectedTasks.value = tasks.value
      .filter(t => !['pending', 'processing'].includes(t.status))
      .map(t => t.task_id)
  } else {
    selectedTasks.value = []
  }
}

async function cancelTask(task) {
  if (!confirm(`確定要取消任務 ${task.task_id.substring(0, 8)}... 嗎？`)) return

  try {
    await api.post(`/api/admin/tasks/${task.task_id}/cancel`)
    task.status = 'cancelled'
    alert('任務已取消')
  } catch (err) {
    alert(err.response?.data?.detail || '取消失敗')
  }
}

async function deleteTask(task) {
  if (!confirm(`確定要刪除任務 ${task.task_id.substring(0, 8)}... 嗎？`)) return

  try {
    await api.delete(`/api/admin/tasks/${task.task_id}`)
    tasks.value = tasks.value.filter(t => t.task_id !== task.task_id)
    total.value--
    alert('任務已刪除')
  } catch (err) {
    alert(err.response?.data?.detail || '刪除失敗')
  }
}

async function batchDelete() {
  if (!confirm(`確定要刪除選中的 ${selectedTasks.value.length} 個任務嗎？`)) return

  try {
    const response = await api.post('/api/admin/tasks/batch/delete', {
      task_ids: selectedTasks.value
    })
    alert(`已刪除 ${response.data.deleted_count} 個任務`)
    fetchTasks()
  } catch (err) {
    alert(err.response?.data?.detail || '批次刪除失敗')
  }
}

function getStatusName(status) {
  const names = {
    pending: '等待中', processing: '處理中', completed: '已完成',
    failed: '失敗', cancelled: '已取消', canceling: '取消中'
  }
  return names[status] || status
}

function formatDuration(seconds) {
  if (!seconds) return '-'
  if (seconds < 60) return `${Math.round(seconds)}秒`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}分${secs}秒`
}

function formatTimestamp(timestamp) {
  if (!timestamp) return '-'
  if (typeof timestamp === 'number') {
    return new Date(timestamp * 1000).toLocaleString('zh-TW')
  }
  return timestamp
}

onMounted(() => {
  fetchTasks()
})
</script>

<style scoped>
.tasks-container {
  max-width: 1800px;
  margin: 0 auto;
  padding: 20px;
}

.admin-nav {
  display: flex;
  gap: 15px;
  margin-bottom: 30px;
  background: white;
  padding: 15px 20px;
  border-radius: 20px;
  justify-content: center;
}

.nav-link {
  padding: 12px 24px;
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-text, rgb(145, 106, 45));
  text-decoration: none;
  border-radius: 12px;
  font-weight: 600;
  transition: all 0.3s;
}

.nav-link:hover { transform: translateY(-2px); }
.nav-link.active {
  background: var(--color-primary, #dd8448);
  color: white;
}

.page-title {
  text-align: center;
  color: var(--color-primary, #dd8448);
  margin-bottom: 30px;
  font-weight: 700;
}

.filters {
  display: flex;
  gap: 15px;
  align-items: center;
  background: white;
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
  color: var(--color-text, rgb(145, 106, 45));
  white-space: nowrap;
}

.filter-select, .filter-input {
  padding: 8px 12px;
  border: none;
  border-radius: 12px;
  background: white;
  color: var(--color-text, rgb(145, 106, 45));
  border: 1px solid rgba(163, 177, 198, 0.3);
  font-size: 14px;
  outline: none;
}

.filter-input { min-width: 150px; }
.filter-input.date { min-width: 130px; }

.filter-btn {
  padding: 8px 16px;
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-primary, #dd8448);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-weight: 700;
  transition: all 0.3s;
}

.filter-btn:hover { transform: translateY(-2px); }
.filter-btn.secondary { background: #fff5f5; color: #c62828; border: 1px solid rgba(198, 40, 40, 0.2); }

.batch-actions {
  display: flex;
  align-items: center;
  gap: 15px;
  background: #fff3e0;
  padding: 15px 20px;
  border-radius: 12px;
  margin-bottom: 20px;
}

.batch-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  background: #e3f2fd;
  color: #1976d2;
}

.batch-btn.danger { background: #ffcdd2; color: #c62828; }

.loading, .error-message {
  text-align: center;
  padding: 40px;
  font-size: 18px;
}

.spinner {
  border: 4px solid transparent;
  border-top: 4px solid var(--main-primary);
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

.tasks-section {
  background: white;
  border-radius: 20px;
  padding: 24px;
}

.tasks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.total-count { font-weight: 600; color: var(--color-text, rgb(145, 106, 45)); }

.refresh-btn {
  padding: 8px 16px;
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-primary, #dd8448);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-weight: 700;
}

.empty-state {
  text-align: center;
  padding: 60px;
  font-size: 20px;
  color: var(--color-text-light, #a0917c);
}

.tasks-table-wrapper {
  overflow-x: auto;
  border-radius: 12px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.tasks-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.tasks-table th {
  background: white;
  padding: 14px 10px;
  text-align: left;
  font-weight: 700;
  color: var(--color-primary, #dd8448);
  border-bottom: 2px solid rgba(163, 177, 198, 0.3);
  white-space: nowrap;
}

.tasks-table td {
  padding: 12px 10px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.15);
  color: var(--color-text, rgb(145, 106, 45));
}

.tasks-table tbody tr:hover { background: rgba(163, 177, 198, 0.08); }

.checkbox-col { width: 40px; text-align: center; }

.task-link, .user-link {
  color: var(--color-primary, #dd8448);
  text-decoration: none;
  font-weight: 600;
}

.task-link:hover, .user-link:hover { text-decoration: underline; }

.filename {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.status-badge.status-completed { background: #c8e6c9; color: #2e7d32; }
.status-badge.status-failed { background: #ffcdd2; color: #c62828; }
.status-badge.status-processing { background: #fff3e0; color: #f57c00; }
.status-badge.status-pending { background: #e3f2fd; color: #1976d2; }
.status-badge.status-cancelled { background: #f5f5f5; color: #757575; }
.status-badge.status-canceling { background: #fff9c4; color: #f57f17; }

.progress-col { min-width: 100px; }

.progress-bar {
  width: 80px;
  height: 8px;
  background: white;
  border-radius: 4px;
  border: 1px solid rgba(163, 177, 198, 0.15);
  display: inline-block;
  vertical-align: middle;
  margin-right: 8px;
}

.progress-fill {
  height: 100%;
  background: var(--color-primary, #dd8448);
  border-radius: 4px;
}

.progress-text { font-size: 11px; color: var(--color-text-light, #a0917c); }

.created-at { font-size: 12px; color: var(--color-text-light, #a0917c); white-space: nowrap; }

.actions { display: flex; gap: 6px; }

.action-btn {
  padding: 5px 10px;
  border: none;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
}

.action-btn.view { background: #e3f2fd; color: #1976d2; }
.action-btn.cancel { background: #fff3e0; color: #f57c00; }
.action-btn.delete { background: #ffcdd2; color: #c62828; }
.action-btn:hover { transform: translateY(-1px); }

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
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-primary, #dd8448);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  font-weight: 700;
}

.page-btn:hover:not(:disabled) { transform: translateY(-2px); }
.page-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.page-info { font-weight: 600; color: var(--color-text, rgb(145, 106, 45)); }
</style>
