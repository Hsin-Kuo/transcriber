<template>
  <nav class="navigation">
    <div class="nav-brand">
      <h2>🎙️ Soundtime</h2>
    </div>

    <div class="nav-links">
      <router-link to="/" class="nav-link" active-class="active">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
          <line x1="12" y1="19" x2="12" y2="23"></line>
          <line x1="8" y1="23" x2="16" y2="23"></line>
        </svg>
        <span>轉錄服務</span>
      </router-link>

      <router-link to="/editor" class="nav-link" active-class="active">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
        </svg>
        <span>音訊剪輯</span>
      </router-link>
      <router-link to="/admin" class="nav-link" active-class="active">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
          <line x1="3" y1="9" x2="21" y2="9"></line>
          <line x1="9" y1="21" x2="9" y2="9"></line>
        </svg>
        <span>系統統計</span>
      </router-link>
    </div>

    <!-- 最近任務預覽 -->
    <div v-if="authStore.isAuthenticated" class="recent-tasks">
      <div class="recent-tasks-header">
        <div class="header-left">
          <h3>近期</h3>
        </div>
        <router-link to="/tasks" class="all-tasks-btn" active-class="active">
          所有任務
        </router-link>
      </div>

      <div class="recent-tasks-list">
        <div v-if="recentTasks.length === 0" class="recent-task-empty">
          暫無已完成任務
        </div>

        <router-link
          v-for="task in recentTasks"
          :key="task.task_id"
          :to="`/transcript/${task.task_id}`"
          class="recent-task-item"
          :title="task.display_name"
        >
          <div class="task-name">{{ truncateName(task.display_name) }}</div>
        </router-link>
      </div>
    </div>

    <div v-if="authStore.isAuthenticated" class="nav-user">
      <router-link to="/settings" class="user-avatar-btn" :title="authStore.user?.email">
        <div class="avatar-circle">
          {{ getFirstLetter(authStore.user?.email) }}
        </div>
      </router-link>
      <button @click="handleLogout" class="logout-btn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
          <polyline points="16 17 21 12 16 7"></polyline>
          <line x1="21" y1="12" x2="9" y2="12"></line>
        </svg>
        <span>登出</span>
      </button>
    </div>
  </nav>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import api from '../../utils/api'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const recentTasks = ref([])

// 根據當前路由決定主題
const themeClass = computed(() => {
  return route.path === '/' ? 'glass-theme' : 'dark-theme'
})

// 載入最近任務
async function loadRecentTasks() {
  if (!authStore.isAuthenticated) return
  try {
    const response = await api.get('/transcribe/recent/preview')
    recentTasks.value = response.data.tasks || []
  } catch (error) {
    console.error('載入最近任務失敗:', error)
  }
}

// 截斷任務名稱（最多 18 字符）
function truncateName(name) {
  const maxLength = 18
  return name.length <= maxLength ? name : name.substring(0, 15) + '...'
}

// 格式化時間為相對時間
function formatTime(timestamp) {
  if (!timestamp) return ''
  try {
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return '剛剛'
    if (diffMins < 60) return `${diffMins}分鐘前`

    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}小時前`

    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 7) return `${diffDays}天前`

    return date.toLocaleDateString('zh-TW', { month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}

// 取得郵箱首字母
function getFirstLetter(email) {
  if (!email) return '?'
  return email.charAt(0).toUpperCase()
}

// 登出處理
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}

// 組件掛載時載入數據
onMounted(() => {
  if (authStore.isAuthenticated) {
    loadRecentTasks()
  }
})

// 可選：監聽路由變化，從任務頁面返回時刷新
watch(() => route.path, (newPath, oldPath) => {
  if (newPath === '/' && oldPath === '/tasks') {
    loadRecentTasks()
  }
})
</script>

<style scoped>
.navigation {
  width: 240px;
  min-width: 240px;
  height: calc(100vh - 40px);
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 28px 20px;
  background: var(--neu-bg);
  border-radius: 20px;
  box-shadow: var(--neu-shadow-raised);
  transition: all 0.3s ease;
}

.nav-brand {
  padding-bottom: 20px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.nav-brand h2 {
  font-size: 1.5rem;
  margin: 0;
  font-weight: 700;
  letter-spacing: -0.5px;
  color: var(--neu-primary);
  text-align: center;
}

.nav-links {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  text-decoration: none;
  font-weight: 600;
  color: var(--neu-text);
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  transition: all 0.3s ease;
}

.nav-link:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary);
  transform: translateX(4px);
}

.nav-link.active {
  box-shadow: var(--neu-shadow-btn-active);
  color: var(--neu-primary-dark);
  background: #dee5d2;
}

.nav-link svg {
  stroke: currentColor;
  flex-shrink: 0;
}

.nav-link span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-user {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
}

.user-avatar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  transition: transform 0.2s ease;
}

.user-avatar-btn:hover {
  transform: translateY(-2px);
}

.avatar-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--neu-primary);
  transition: all 0.3s ease;
  cursor: pointer;
}

.avatar-circle:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary-dark);
}

.avatar-circle:active {
  box-shadow: var(--neu-shadow-btn-active);
}

.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  border: none;
  background: var(--neu-bg);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--neu-text);
  box-shadow: var(--neu-shadow-btn);
  transition: all 0.3s ease;
}

.logout-btn:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary);
  transform: translateY(-2px);
}

.logout-btn:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

.logout-btn svg {
  stroke: currentColor;
  flex-shrink: 0;
}

.recent-tasks {
  padding: 6px 6px 0 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow: hidden;
}

.recent-tasks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px;
  margin-bottom: 8px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-left svg {
  stroke: var(--neu-text-light);
  flex-shrink: 0;
}

.header-left h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--neu-text-light);
  margin: 0;
}

.all-tasks-btn {
  padding: 4px 10px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--neu-text);
  text-decoration: none;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn-sm);
  border-radius: 8px;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.all-tasks-btn:hover {
  box-shadow: var(--neu-shadow-btn-hover-sm);
  color: var(--neu-primary);
  transform: translateY(-1px);
}

.all-tasks-btn.active {
  box-shadow: var(--neu-shadow-btn-active-sm);
  color: var(--neu-primary-dark);
}

.recent-tasks-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  max-height: 240px;
  padding-right: 4px;
}

.recent-tasks-list::-webkit-scrollbar {
  width: 4px;
}

.recent-tasks-list::-webkit-scrollbar-track {
  background: transparent;
}

.recent-tasks-list::-webkit-scrollbar-thumb {
  background: rgba(163, 177, 198, 0.3);
  border-radius: 2px;
}

.recent-task-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 3px 12px;
  /* border-radius: 10px; */
  background: var(--neu-bg);
  /* box-shadow: var(--neu-shadow-btn); */
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
}

.recent-task-item:hover {
  /* box-shadow: var(--neu-shadow-btn-hover); */
  transform: translateX(2px);
}

.recent-task-item:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateX(0);
}

.task-name {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--neu-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}

.task-time {
  font-size: 0.7rem;
  color: var(--neu-text-lighter);
  line-height: 1.2;
}

.recent-task-empty {
  padding: 16px 12px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--neu-text-lighter);
  font-style: italic;
}

@media (max-width: 768px) {
  .navigation {
    width: 100%;
    min-width: 100%;
    height: auto;
    position: relative;
    top: 0;
    padding: 20px;
  }

  .nav-links {
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: center;
  }

  .nav-link {
    flex: 1;
    min-width: 140px;
    justify-content: center;
  }

  .nav-link:hover {
    transform: translateY(-2px);
  }

  .nav-user {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    padding-top: 16px;
  }

  .recent-tasks {
    display: none;
  }
}
</style>
