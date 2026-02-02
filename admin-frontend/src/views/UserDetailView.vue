<template>
  <div class="user-detail-container">
    <!-- 導航 -->
    <AdminNav />

    <!-- 返回按鈕 -->
    <div class="back-link">
      <router-link to="/users">← 返回用戶列表</router-link>
    </div>

    <!-- 載入中 -->
    <div v-if="loading" class="loading">
      <div class="spinner"></div>
      <p>載入用戶資料中...</p>
    </div>

    <!-- 錯誤訊息 -->
    <div v-else-if="error" class="error-message">
      {{ error }}
    </div>

    <!-- 用戶詳情 -->
    <div v-else-if="user" class="user-detail">
      <h1 class="page-title">{{ user.email }}</h1>

      <div class="detail-grid">
        <!-- 基本資訊 -->
        <div class="detail-card">
          <h2>基本資訊</h2>
          <div class="info-row">
            <span class="label">用戶 ID：</span>
            <code class="value">{{ user.id }}</code>
          </div>
          <div class="info-row">
            <span class="label">Email：</span>
            <span class="value">{{ user.email }}</span>
          </div>
          <div class="info-row">
            <span class="label">角色：</span>
            <span class="role-badge" :class="`role-${user.role}`">
              {{ user.role === 'admin' ? '管理員' : '一般用戶' }}
            </span>
            <button
              v-if="user.role !== 'admin'"
              @click="showRoleModal = true"
              class="edit-btn"
            >
              修改
            </button>
          </div>
          <div class="info-row">
            <span class="label">狀態：</span>
            <span class="status-badge" :class="user.is_active ? 'active' : 'inactive'">
              {{ user.is_active ? '啟用' : '停用' }}
            </span>
            <button
              @click="toggleStatus"
              class="edit-btn"
              :class="user.is_active ? 'danger' : 'success'"
            >
              {{ user.is_active ? '停用帳號' : '啟用帳號' }}
            </button>
          </div>
          <div class="info-row">
            <span class="label">Email 驗證：</span>
            <span :class="user.email_verified ? 'verified' : 'not-verified'">
              {{ user.email_verified ? '已驗證' : '未驗證' }}
            </span>
          </div>
          <div class="info-row">
            <span class="label">註冊時間：</span>
            <span class="value">{{ formatTimestamp(user.created_at) }}</span>
          </div>
          <div class="info-row">
            <span class="label">密碼：</span>
            <span class="value">••••••••</span>
            <button @click="showPasswordModal = true" class="edit-btn">
              重設密碼
            </button>
          </div>
        </div>

        <!-- 配額資訊 -->
        <div class="detail-card">
          <h2>配額設定</h2>
          <div class="info-row">
            <span class="label">等級：</span>
            <span class="tier-badge" :class="`tier-${user.quota?.tier || 'free'}`">
              {{ getTierName(user.quota?.tier) }}
            </span>
            <button @click="showQuotaModal = true" class="edit-btn">調整配額</button>
          </div>
          <div class="info-row">
            <span class="label">每月轉錄次數：</span>
            <span class="value">{{ user.quota?.max_transcriptions || 0 }} 次</span>
          </div>
          <div class="info-row">
            <span class="label">每月轉錄時長：</span>
            <span class="value">{{ user.quota?.max_duration_minutes || 0 }} 分鐘</span>
          </div>
          <div class="info-row">
            <span class="label">並發任務數：</span>
            <span class="value">{{ user.quota?.max_concurrent_tasks || 1 }}</span>
          </div>
          <div class="info-row">
            <span class="label">說話者辨識：</span>
            <span :class="user.quota?.features?.speaker_diarization ? 'enabled' : 'disabled'">
              {{ user.quota?.features?.speaker_diarization ? '已啟用' : '未啟用' }}
            </span>
          </div>
        </div>

        <!-- 使用量統計 -->
        <div class="detail-card">
          <h2>本月使用量</h2>
          <div class="usage-item">
            <div class="usage-header">
              <span class="label">轉錄次數</span>
              <span class="usage-text">
                {{ user.usage?.transcriptions || 0 }} / {{ user.quota?.max_transcriptions || 0 }}
              </span>
            </div>
            <div class="usage-bar">
              <div
                class="usage-fill"
                :style="{ width: getUsagePercent(user.usage?.transcriptions, user.quota?.max_transcriptions) + '%' }"
              ></div>
            </div>
          </div>
          <div class="usage-item">
            <div class="usage-header">
              <span class="label">轉錄時長（分鐘）</span>
              <span class="usage-text">
                {{ (user.usage?.duration_minutes || 0).toFixed(1) }} / {{ user.quota?.max_duration_minutes || 0 }}
              </span>
            </div>
            <div class="usage-bar">
              <div
                class="usage-fill"
                :style="{ width: getUsagePercent(user.usage?.duration_minutes, user.quota?.max_duration_minutes) + '%' }"
              ></div>
            </div>
          </div>
          <div class="info-row">
            <span class="label">累計轉錄次數：</span>
            <span class="value">{{ user.usage?.total_transcriptions || 0 }} 次</span>
          </div>
          <div class="info-row">
            <span class="label">累計轉錄時長：</span>
            <span class="value">{{ (user.usage?.total_duration_minutes || 0).toFixed(1) }} 分鐘</span>
          </div>
          <button @click="resetQuota" class="reset-btn">🔄 重置本月配額</button>
        </div>

        <!-- 任務統計 -->
        <div class="detail-card">
          <h2>任務統計</h2>
          <div class="stats-grid">
            <div class="stat-item">
              <span class="stat-value">{{ user.stats?.total_tasks || 0 }}</span>
              <span class="stat-label">總任務數</span>
            </div>
            <div class="stat-item success">
              <span class="stat-value">{{ user.stats?.completed_tasks || 0 }}</span>
              <span class="stat-label">已完成</span>
            </div>
            <div class="stat-item danger">
              <span class="stat-value">{{ user.stats?.failed_tasks || 0 }}</span>
              <span class="stat-label">失敗</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近任務 -->
      <div class="recent-tasks-card">
        <h2>最近任務</h2>
        <div v-if="!user.recent_tasks || user.recent_tasks.length === 0" class="empty-state">
          暫無任務記錄
        </div>
        <table v-else class="tasks-table">
          <thead>
            <tr>
              <th>Task ID</th>
              <th>檔名</th>
              <th>狀態</th>
              <th>建立時間</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in user.recent_tasks" :key="task.task_id">
              <td><code>{{ task.task_id?.substring(0, 8) }}...</code></td>
              <td>{{ task.filename || '-' }}</td>
              <td>
                <span class="task-status" :class="`status-${task.status}`">
                  {{ getStatusName(task.status) }}
                </span>
              </td>
              <td>{{ formatTimestamp(task.created_at) }}</td>
              <td>
                <router-link :to="`/tasks/${task.task_id}`" class="action-btn view">
                  查看
                </router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 配額調整 Modal -->
    <div v-if="showQuotaModal" class="modal-overlay" @click.self="showQuotaModal = false">
      <div class="modal">
        <h3>調整配額</h3>
        <div class="modal-body">
          <div class="form-group">
            <label>選擇等級：</label>
            <select v-model="quotaForm.tier" class="form-select">
              <option value="free">免費版</option>
              <option value="basic">基礎版</option>
              <option value="pro">專業版</option>
              <option value="enterprise">企業版</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button @click="showQuotaModal = false" class="btn-cancel">取消</button>
          <button @click="updateQuota" class="btn-confirm">確認</button>
        </div>
      </div>
    </div>

    <!-- 角色修改 Modal -->
    <div v-if="showRoleModal" class="modal-overlay" @click.self="showRoleModal = false">
      <div class="modal">
        <h3>修改角色</h3>
        <div class="modal-body">
          <p>確定要將此用戶設為管理員嗎？</p>
          <p class="warning">⚠️ 此操作將賦予該用戶管理後台的完整權限</p>
        </div>
        <div class="modal-footer">
          <button @click="showRoleModal = false" class="btn-cancel">取消</button>
          <button @click="updateRole" class="btn-confirm">確認</button>
        </div>
      </div>
    </div>

    <!-- 重設密碼 Modal -->
    <div v-if="showPasswordModal" class="modal-overlay" @click.self="closePasswordModal">
      <div class="modal">
        <h3>重設密碼</h3>
        <div class="modal-body">
          <p class="modal-user-email">用戶：{{ user.email }}</p>
          <div class="form-group">
            <label>新密碼：</label>
            <input
              v-model="passwordForm.newPassword"
              type="password"
              class="form-input"
              placeholder="請輸入新密碼（至少 8 個字元）"
              minlength="8"
            />
          </div>
          <div class="form-group">
            <label>確認密碼：</label>
            <input
              v-model="passwordForm.confirmPassword"
              type="password"
              class="form-input"
              placeholder="請再次輸入新密碼"
            />
          </div>
          <p v-if="passwordError" class="error-text">{{ passwordError }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closePasswordModal" class="btn-cancel">取消</button>
          <button @click="resetPassword" class="btn-confirm" :disabled="isResettingPassword">
            {{ isResettingPassword ? '重設中...' : '確認重設' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../utils/api'
import AdminNav from '../components/shared/AdminNav.vue'

const route = useRoute()

const user = ref(null)
const loading = ref(true)
const error = ref(null)
const showQuotaModal = ref(false)
const showRoleModal = ref(false)
const showPasswordModal = ref(false)
const isResettingPassword = ref(false)
const passwordError = ref('')

const quotaForm = ref({
  tier: 'free'
})

const passwordForm = ref({
  newPassword: '',
  confirmPassword: ''
})

async function fetchUser() {
  loading.value = true
  error.value = null

  try {
    const response = await api.get(`/api/admin/users/${route.params.id}`)
    user.value = response.data
    quotaForm.value.tier = user.value.quota?.tier || 'free'
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || '載入失敗'
  } finally {
    loading.value = false
  }
}

async function toggleStatus() {
  const action = user.value.is_active ? '停用' : '啟用'
  if (!confirm(`確定要${action}此用戶嗎？`)) return

  try {
    await api.put(`/api/admin/users/${user.value.id}/status`, {
      is_active: !user.value.is_active
    })
    user.value.is_active = !user.value.is_active
    alert(`用戶已${action}`)
  } catch (err) {
    alert(err.response?.data?.detail || `${action}失敗`)
  }
}

async function updateQuota() {
  try {
    const response = await api.put(`/api/admin/users/${user.value.id}/quota`, {
      tier: quotaForm.value.tier
    })
    user.value.quota = response.data.quota
    showQuotaModal.value = false
    alert('配額已更新')
  } catch (err) {
    alert(err.response?.data?.detail || '更新失敗')
  }
}

async function updateRole() {
  try {
    await api.put(`/api/admin/users/${user.value.id}/role`, {
      role: 'admin'
    })
    user.value.role = 'admin'
    showRoleModal.value = false
    alert('角色已更新')
  } catch (err) {
    alert(err.response?.data?.detail || '更新失敗')
  }
}

async function resetQuota() {
  if (!confirm('確定要重置此用戶的本月配額使用量嗎？')) return

  try {
    await api.post(`/api/admin/users/${user.value.id}/reset-quota`)
    user.value.usage.transcriptions = 0
    user.value.usage.duration_minutes = 0
    alert('配額已重置')
  } catch (err) {
    alert(err.response?.data?.detail || '重置失敗')
  }
}

function closePasswordModal() {
  showPasswordModal.value = false
  passwordForm.value = { newPassword: '', confirmPassword: '' }
  passwordError.value = ''
}

async function resetPassword() {
  passwordError.value = ''

  // 驗證密碼
  if (passwordForm.value.newPassword.length < 8) {
    passwordError.value = '密碼長度至少需要 8 個字元'
    return
  }

  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    passwordError.value = '兩次輸入的密碼不一致'
    return
  }

  isResettingPassword.value = true

  try {
    await api.post(`/api/admin/users/${user.value.id}/reset-password`, {
      new_password: passwordForm.value.newPassword
    })
    closePasswordModal()
    alert('密碼已重設成功')
  } catch (err) {
    passwordError.value = err.response?.data?.detail || '重設密碼失敗'
  } finally {
    isResettingPassword.value = false
  }
}

function getTierName(tier) {
  const names = { free: '免費版', basic: '基礎版', pro: '專業版', enterprise: '企業版' }
  return names[tier] || '免費版'
}

function getStatusName(status) {
  const names = {
    pending: '等待中', processing: '處理中', completed: '已完成',
    failed: '失敗', cancelled: '已取消'
  }
  return names[status] || status
}

function getUsagePercent(used, max) {
  if (!max) return 0
  return Math.min((used || 0) / max * 100, 100)
}

function formatTimestamp(timestamp) {
  if (!timestamp) return '-'
  if (typeof timestamp === 'number') {
    return new Date(timestamp * 1000).toLocaleString('zh-TW')
  }
  return timestamp
}

onMounted(() => {
  fetchUser()
})
</script>

<style scoped>
.user-detail-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px;
}

.admin-nav {
  display: flex;
  gap: 15px;
  margin-bottom: 20px;
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

.back-link {
  margin-bottom: 20px;
}

.back-link a {
  color: var(--color-primary, #dd8448);
  text-decoration: none;
  font-weight: 600;
}

.back-link a:hover { text-decoration: underline; }

.page-title {
  text-align: center;
  color: var(--color-primary, #dd8448);
  margin-bottom: 30px;
  font-weight: 700;
}

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

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.detail-card, .recent-tasks-card {
  background: white;
  border-radius: 20px;
  padding: 24px;
}

.detail-card h2, .recent-tasks-card h2 {
  font-size: 18px;
  color: var(--color-primary, #dd8448);
  margin-bottom: 20px;
  font-weight: 700;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.info-row:last-child { border-bottom: none; }

.label {
  color: var(--color-text-light, #a0917c);
  font-weight: 500;
  min-width: 120px;
}

.value {
  color: var(--color-text, rgb(145, 106, 45));
  font-weight: 600;
}

code {
  background: white;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.role-badge, .status-badge, .tier-badge {
  padding: 4px 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.role-badge.role-admin { background: #fce4ec; color: #c2185b; }
.role-badge.role-user { background: #e3f2fd; color: #1976d2; }
.status-badge.active { background: #c8e6c9; color: #2e7d32; }
.status-badge.inactive { background: #ffcdd2; color: #c62828; }
.tier-badge.tier-free { background: #f5f5f5; color: #757575; }
.tier-badge.tier-basic { background: #e3f2fd; color: #1976d2; }
.tier-badge.tier-pro { background: #fff3e0; color: #f57c00; }
.tier-badge.tier-enterprise { background: #fce4ec; color: #c2185b; }

.verified { color: #2e7d32; font-weight: 600; }
.not-verified { color: #c62828; font-weight: 600; }
.enabled { color: #2e7d32; font-weight: 600; }
.disabled { color: #757575; font-weight: 600; }

.edit-btn {
  padding: 4px 12px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  background: #e3f2fd;
  color: #1976d2;
  margin-left: auto;
}

.edit-btn.danger { background: #ffcdd2; color: #c62828; }
.edit-btn.success { background: #c8e6c9; color: #2e7d32; }
.edit-btn:hover { transform: translateY(-1px); }

.usage-item {
  margin-bottom: 20px;
}

.usage-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.usage-text {
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
}

.usage-bar {
  height: 10px;
  background: white;
  border-radius: 5px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.usage-fill {
  height: 100%;
  background: var(--color-primary, #dd8448);
  border-radius: 5px;
  transition: width 0.3s;
}

.reset-btn {
  width: 100%;
  padding: 12px;
  margin-top: 15px;
  background: var(--color-primary, #dd8448); color: white;
  color: var(--color-primary, #dd8448);
  border: none;
  border-radius: 12px;
  font-weight: 700;
  cursor: pointer;
}

.reset-btn:hover { transform: translateY(-2px); }

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
}

.stat-item {
  text-align: center;
  padding: 15px;
  background: white;
  border-radius: 12px;
  border: 1px solid rgba(163, 177, 198, 0.15);
}

.stat-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: var(--color-primary, #dd8448);
}

.stat-item.success .stat-value { color: #2e7d32; }
.stat-item.danger .stat-value { color: #c62828; }

.stat-label {
  font-size: 12px;
  color: var(--color-text-light, #a0917c);
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--color-text-light, #a0917c);
}

.tasks-table {
  width: 100%;
  border-collapse: collapse;
}

.tasks-table th, .tasks-table td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.tasks-table th {
  font-weight: 700;
  color: var(--color-primary, #dd8448);
}

.task-status {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.task-status.status-completed { background: #c8e6c9; color: #2e7d32; }
.task-status.status-failed { background: #ffcdd2; color: #c62828; }
.task-status.status-processing { background: #fff3e0; color: #f57c00; }
.task-status.status-pending { background: #e3f2fd; color: #1976d2; }
.task-status.status-cancelled { background: #f5f5f5; color: #757575; }

.action-btn {
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
}

.action-btn.view { background: #e3f2fd; color: #1976d2; }

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: white;
  border-radius: 20px;
  padding: 30px;
  min-width: 400px;
  max-width: 90%;
}

.modal h3 {
  color: var(--color-primary, #dd8448);
  margin-bottom: 20px;
}

.modal-body {
  margin-bottom: 20px;
}

.form-group {
  margin-bottom: 15px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
}

.form-select {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 12px;
  background: white;
  border: 1px solid rgba(163, 177, 198, 0.3);
}

.warning {
  color: #f57c00;
  font-size: 14px;
  margin-top: 10px;
}

.modal-footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.btn-cancel, .btn-confirm {
  padding: 10px 20px;
  border: none;
  border-radius: 10px;
  font-weight: 600;
  cursor: pointer;
}

.btn-cancel {
  background: #f5f5f5;
  color: #757575;
}

.btn-confirm {
  background: var(--color-primary, #dd8448);
  color: white;
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-input {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 12px;
  background: white;
  border: 1px solid rgba(163, 177, 198, 0.3);
  font-size: 14px;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary, #dd8448);
}

.modal-user-email {
  color: var(--color-text, rgb(145, 106, 45));
  font-weight: 600;
  margin-bottom: 15px;
}

.error-text {
  color: #c62828;
  font-size: 14px;
  margin-top: 10px;
}
</style>
