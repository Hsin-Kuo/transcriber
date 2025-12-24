<template>
  <nav class="navigation" :class="{ collapsed: isCollapsed }">
    <!-- 收合/展開按鈕 -->
    <button class="toggle-btn" @click="toggleCollapse" :title="isCollapsed ? '展開側欄' : '收合側欄'">
      <!-- 展開時顯示《（向左，表示收合） -->
      <svg v-if="!isCollapsed" width="16" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"></polyline>
      </svg>
      <!-- 收合時顯示》（向右，表示展開） -->
      <svg v-else width="16" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"></polyline>
      </svg>
    </button>

    <div class="nav-brand">
      <h2 v-if="!isCollapsed">🎙️ Soundtime</h2>
      <h2 v-else class="brand-icon">🎙️</h2>
    </div>

    <div class="nav-links">
      <router-link to="/" class="nav-link" active-class="active" :title="isCollapsed ? '轉錄服務' : ''">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
          <line x1="12" y1="19" x2="12" y2="23"></line>
          <line x1="8" y1="23" x2="16" y2="23"></line>
        </svg>
        <span v-if="!isCollapsed">轉錄服務</span>
      </router-link>

      <router-link to="/editor" class="nav-link" active-class="active" :title="isCollapsed ? '音訊剪輯' : ''">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
        </svg>
        <span v-if="!isCollapsed">音訊剪輯</span>
      </router-link>

      <!-- 所有任務按鈕（收合時顯示） -->
      <router-link v-if="authStore.isAuthenticated && isCollapsed" to="/tasks" class="nav-link tasks-link" active-class="active" title="所有任務">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
        </svg>
      </router-link>
    </div>

    <!-- 最近任務預覽（展開時顯示） -->
    <div v-if="authStore.isAuthenticated && !isCollapsed" class="recent-tasks">
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

    <!-- Spacer 將下方內容推到底部（收合時顯示） -->
    <div v-if="isCollapsed" class="nav-spacer"></div>

    <div v-if="authStore.isAuthenticated" class="nav-user">
      <router-link to="/settings" class="user-avatar-btn" :title="authStore.user?.email">
        <div class="avatar-circle">
          {{ getFirstLetter(authStore.user?.email) }}
        </div>
      </router-link>
      <button @click="handleLogout" class="logout-btn" :title="isCollapsed ? '登出' : ''">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
          <polyline points="16 17 21 12 16 7"></polyline>
          <line x1="21" y1="12" x2="9" y2="12"></line>
        </svg>
        <span v-if="!isCollapsed">登出</span>
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

// 側欄收合狀態
const isCollapsed = ref(false)

// 切換收合狀態
function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
  localStorage.setItem('navCollapsed', JSON.stringify(isCollapsed.value))
}

// 載入最近任務
async function loadRecentTasks() {
  if (!authStore.isAuthenticated) return
  try {
    const response = await api.get('/tasks/recent', {
      params: { limit: 10 }
    })
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
  // 載入收合狀態
  const saved = localStorage.getItem('navCollapsed')
  if (saved !== null) {
    isCollapsed.value = JSON.parse(saved)
  }

  // 載入最近任務
  if (authStore.isAuthenticated) {
    loadRecentTasks()
  }
})

// 監聽認證狀態變化，確保登入後載入近期任務
watch(() => authStore.isAuthenticated, (isAuth) => {
  if (isAuth) {
    loadRecentTasks()
  } else {
    // 登出時清空近期任務
    recentTasks.value = []
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

/* 收合狀態 */
.navigation.collapsed {
  width: 80px;
  min-width: 80px;
  padding: 20px 12px;
  align-items: center;
}

/* 切換按鈕 */
.toggle-btn {
  position: absolute;
  top: 16px;
  right: 12px;
  width: 28px;
  height: 36px;
  border: none;
  background: var(--neu-bg);
  border-radius: 6px;
  box-shadow: var(--neu-shadow-btn-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  z-index: 10;
}

.toggle-btn:hover {
  box-shadow: var(--neu-shadow-btn-hover-sm);
  transform: translateX(-2px);
}

.toggle-btn:active {
  box-shadow: var(--neu-shadow-btn-active-sm);
  transform: translateX(0);
}

.toggle-btn svg {
  stroke: var(--neu-primary);
  transition: all 0.2s ease;
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
  transition: all 0.3s ease;
}

.navigation.collapsed .nav-brand {
  padding-bottom: 16px;
}

.brand-icon {
  font-size: 1.8rem;
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
  transition: opacity 0.3s ease;
}

/* 收合狀態下的連結 */
.navigation.collapsed .nav-link {
  justify-content: center;
  padding: 12px;
}

.navigation.collapsed .nav-link span {
  display: none;
}

.navigation.collapsed .nav-link:hover {
  transform: translateY(-2px);
}

/* Spacer 將下方內容推到底部 */
.nav-spacer {
  flex: 1;
  min-height: 20px;
}

.nav-user {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
  transition: all 0.3s ease;
}

/* 收合狀態下的使用者區域 - 垂直排列 */
.navigation.collapsed .nav-user {
  flex-direction: column;
  gap: 12px;
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

.logout-btn span {
  transition: opacity 0.3s ease;
}

/* 收合狀態下的登出按鈕 */
.navigation.collapsed .logout-btn {
  padding: 12px;
  width: 44px;
  min-width: 44px;
}

.navigation.collapsed .logout-btn span {
  display: none;
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
  max-height: 300px;
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
