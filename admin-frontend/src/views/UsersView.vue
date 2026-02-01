<template>
  <div class="users-container">
    <!-- 導航 -->
    <AdminNav />

    <h1 class="page-title">用戶管理</h1>

    <!-- 篩選器 -->
    <div class="filters">
      <div class="filter-item">
        <label>搜尋：</label>
        <input
          v-model="filters.search"
          @keyup.enter="fetchUsers"
          placeholder="Email"
          class="filter-input"
        />
      </div>

      <div class="filter-item">
        <label>角色：</label>
        <select v-model="filters.role" @change="fetchUsers" class="filter-select">
          <option value="">全部</option>
          <option value="user">一般用戶</option>
          <option value="admin">管理員</option>
        </select>
      </div>

      <div class="filter-item">
        <label>狀態：</label>
        <select v-model="filters.is_active" @change="fetchUsers" class="filter-select">
          <option value="">全部</option>
          <option value="true">啟用</option>
          <option value="false">停用</option>
        </select>
      </div>

      <div class="filter-item">
        <label>配額等級：</label>
        <select v-model="filters.tier" @change="fetchUsers" class="filter-select">
          <option value="">全部</option>
          <option value="free">免費版</option>
          <option value="basic">基礎版</option>
          <option value="pro">專業版</option>
          <option value="enterprise">企業版</option>
        </select>
      </div>

      <button @click="fetchUsers" class="filter-btn">🔍 搜尋</button>
      <button @click="clearFilters" class="filter-btn secondary">✕ 清除</button>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入用戶列表中...</p>
    </div>

    <!-- 錯誤訊息 -->
    <div v-else-if="error" class="error-message">
      {{ error }}
    </div>

    <!-- 用戶列表 -->
    <div v-else class="users-section">
      <div class="users-header">
        <span class="total-count">共 {{ total }} 位用戶</span>
        <button @click="fetchUsers" class="refresh-btn">🔄 刷新</button>
      </div>

      <div v-if="users.length === 0" class="empty-state">
        📭 沒有符合條件的用戶
      </div>

      <div v-else class="users-table-wrapper">
        <table class="users-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>角色</th>
              <th>狀態</th>
              <th>配額等級</th>
              <th>本月使用</th>
              <th>任務數</th>
              <th>註冊時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td class="email">
                <router-link :to="`/users/${user.id}`" class="user-link">
                  {{ user.email }}
                </router-link>
              </td>
              <td>
                <span class="role-badge" :class="`role-${user.role}`">
                  {{ user.role === 'admin' ? '管理員' : '用戶' }}
                </span>
              </td>
              <td>
                <span class="status-badge" :class="user.is_active ? 'active' : 'inactive'">
                  {{ user.is_active ? '啟用' : '停用' }}
                </span>
              </td>
              <td>
                <span class="tier-badge" :class="`tier-${user.quota?.tier || 'free'}`">
                  {{ getTierName(user.quota?.tier) }}
                </span>
              </td>
              <td class="usage">
                <div class="usage-info">
                  <span>{{ user.usage?.transcriptions || 0 }} / {{ user.quota?.max_transcriptions || 0 }} 次</span>
                  <div class="usage-bar">
                    <div
                      class="usage-fill"
                      :style="{ width: getUsagePercent(user.usage?.transcriptions, user.quota?.max_transcriptions) + '%' }"
                    ></div>
                  </div>
                </div>
              </td>
              <td class="task-count">
                {{ user.task_count || 0 }}
                <span v-if="user.active_task_count > 0" class="active-tasks">
                  ({{ user.active_task_count }} 進行中)
                </span>
              </td>
              <td class="created-at">{{ formatTimestamp(user.created_at) }}</td>
              <td class="actions">
                <router-link :to="`/users/${user.id}`" class="action-btn view">
                  查看
                </router-link>
                <button
                  @click="toggleUserStatus(user)"
                  class="action-btn"
                  :class="user.is_active ? 'disable' : 'enable'"
                  :disabled="user.role === 'admin'"
                >
                  {{ user.is_active ? '停用' : '啟用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 分頁 -->
      <div class="pagination">
        <button
          @click="previousPage"
          :disabled="currentPage === 1"
          class="page-btn"
        >
          ← 上一頁
        </button>

        <span class="page-info">
          第 {{ currentPage }} / {{ totalPages }} 頁
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
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

const users = ref([])
const loading = ref(true)
const error = ref(null)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

const filters = ref({
  search: '',
  role: '',
  is_active: '',
  tier: ''
})

const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

async function fetchUsers() {
  loading.value = true
  error.value = null

  try {
    const params = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value
    }

    if (filters.value.search) params.search = filters.value.search
    if (filters.value.role) params.role = filters.value.role
    if (filters.value.is_active) params.is_active = filters.value.is_active === 'true'
    if (filters.value.tier) params.tier = filters.value.tier

    const response = await api.get('/api/admin/users', { params })
    users.value = response.data.users
    total.value = response.data.total
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
    console.error('載入用戶列表失敗:', err)
  } finally {
    loading.value = false
  }
}

function clearFilters() {
  filters.value = { search: '', role: '', is_active: '', tier: '' }
  currentPage.value = 1
  fetchUsers()
}

function previousPage() {
  if (currentPage.value > 1) {
    currentPage.value--
    fetchUsers()
  }
}

function nextPage() {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
    fetchUsers()
  }
}

async function toggleUserStatus(user) {
  if (user.role === 'admin') return

  const action = user.is_active ? '停用' : '啟用'
  if (!confirm(`確定要${action}用戶 ${user.email} 嗎？`)) return

  try {
    await api.put(`/api/admin/users/${user.id}/status`, {
      is_active: !user.is_active
    })
    user.is_active = !user.is_active
  } catch (err) {
    alert(err.response?.data?.detail || `${action}失敗`)
  }
}

function getTierName(tier) {
  const names = {
    free: '免費版',
    basic: '基礎版',
    pro: '專業版',
    enterprise: '企業版'
  }
  return names[tier] || '免費版'
}

function getUsagePercent(used, max) {
  if (!max) return 0
  return Math.min((used || 0) / max * 100, 100)
}

function formatTimestamp(timestamp) {
  if (!timestamp) return '-'
  if (typeof timestamp === 'number') {
    return new Date(timestamp * 1000).toLocaleDateString('zh-TW')
  }
  return timestamp.split(' ')[0]
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped>
.users-container {
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

.filter-select, .filter-input {
  padding: 8px 12px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 8px;
  background: white;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.filter-input { min-width: 180px; }

.filter-select:focus, .filter-input:focus {
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

.filter-btn:hover { background: var(--color-primary-dark, #b8762d); }

.filter-btn.secondary {
  background: #fff5f5;
  color: #c62828;
  border: 1px solid rgba(198, 40, 40, 0.2);
}

.filter-btn.secondary:hover { background: #ffebee; }

.users-section {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(163, 177, 198, 0.2);
}

.users-header {
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
  font-weight: 600;
  font-size: 13px;
  transition: all 0.2s;
}

.refresh-btn:hover { background: var(--color-primary-dark, #b8762d); }

.empty-state {
  text-align: center;
  padding: 60px;
  font-size: 16px;
  color: var(--color-text-light, #a0917c);
}

.users-table-wrapper {
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.users-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.users-table th {
  background: #fafafa;
  padding: 12px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
  white-space: nowrap;
  font-size: 13px;
}

.users-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.1);
  color: var(--color-text, rgb(145, 106, 45));
}

.users-table tbody tr:hover {
  background: rgba(221, 132, 72, 0.04);
}

.user-link {
  color: var(--color-primary, #dd8448);
  text-decoration: none;
  font-weight: 600;
}

.user-link:hover { text-decoration: underline; }

.role-badge, .status-badge, .tier-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.role-badge.role-admin { background: #fce4ec; color: #c2185b; }
.role-badge.role-user { background: #e3f2fd; color: #1565c0; }
.status-badge.active { background: #d4edda; color: #155724; }
.status-badge.inactive { background: #ffebee; color: #c62828; }
.tier-badge.tier-free { background: #f5f5f5; color: #616161; }
.tier-badge.tier-basic { background: #e3f2fd; color: #1565c0; }
.tier-badge.tier-pro { background: #fff3e0; color: #e65100; }
.tier-badge.tier-enterprise { background: #fce4ec; color: #c2185b; }

.usage-info { font-size: 12px; }

.usage-bar {
  width: 80px;
  height: 5px;
  background: #f0f0f0;
  border-radius: 3px;
  margin-top: 4px;
}

.usage-fill {
  height: 100%;
  background: var(--color-primary, #dd8448);
  border-radius: 3px;
  transition: width 0.3s;
}

.task-count { font-weight: 600; }
.active-tasks { color: #e65100; font-size: 11px; }
.created-at { font-size: 12px; color: var(--color-text-light, #a0917c); }

.actions { display: flex; gap: 6px; }

.action-btn {
  padding: 5px 10px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.2s;
}

.action-btn.view { background: #e3f2fd; color: #1565c0; }
.action-btn.disable { background: #ffebee; color: #c62828; }
.action-btn.enable { background: #d4edda; color: #155724; }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

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
  font-weight: 600;
  font-size: 13px;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) { background: var(--color-primary-dark, #b8762d); }
.page-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.page-info { font-weight: 500; color: var(--color-text, rgb(145, 106, 45)); font-size: 13px; }
</style>
