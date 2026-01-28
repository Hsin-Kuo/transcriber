<template>
  <nav class="navigation" :class="{ collapsed: isCollapsed }">
    <!-- 收合/展開按鈕 -->
    <button class="toggle-btn" @click="toggleCollapse" :title="isCollapsed ? $t('navigation.expandSidebar') : $t('navigation.collapseSidebar')">
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
      <svg class="brand-icon" width="28" height="24" viewBox="0 0 28 24">
        <!-- 列1: 2個點 -->
        <circle cx="2" cy="18" r="1.5" fill="currentColor"/>
        <circle cx="2" cy="22" r="1.5" fill="currentColor"/>
        <!-- 列2: 1個點 -->
        <circle cx="6" cy="22" r="1.5" fill="currentColor"/>
        <!-- 列3: 4個點 -->
        <circle cx="10" cy="10" r="1.5" fill="currentColor"/>
        <circle cx="10" cy="14" r="1.5" fill="currentColor"/>
        <circle cx="10" cy="18" r="1.5" fill="currentColor"/>
        <circle cx="10" cy="22" r="1.5" fill="currentColor"/>
        <!-- 列4: 3個點 -->
        <circle cx="14" cy="14" r="1.5" fill="currentColor"/>
        <circle cx="14" cy="18" r="1.5" fill="currentColor"/>
        <circle cx="14" cy="22" r="1.5" fill="currentColor"/>
        <!-- 列5: 1個點 -->
        <circle cx="18" cy="22" r="1.5" fill="currentColor"/>
        <!-- 列6: 6個點 -->
        <circle cx="22" cy="2" r="1.5" fill="currentColor"/>
        <circle cx="22" cy="6" r="1.5" fill="currentColor"/>
        <circle cx="22" cy="10" r="1.5" fill="currentColor"/>
        <circle cx="22" cy="14" r="1.5" fill="currentColor"/>
        <circle cx="22" cy="18" r="1.5" fill="currentColor"/>
        <circle cx="22" cy="22" r="1.5" fill="currentColor"/>
        <!-- 列7: 3個點 -->
        <circle cx="26" cy="14" r="1.5" fill="currentColor"/>
        <circle cx="26" cy="18" r="1.5" fill="currentColor"/>
        <circle cx="26" cy="22" r="1.5" fill="currentColor"/>
      </svg>
      <h2 v-if="!isCollapsed">SoundThing</h2>
    </div>

    <div class="nav-links">
      <router-link to="/" class="nav-link" active-class="active" :title="isCollapsed ? $t('navigation.transcription') : ''">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
          <line x1="12" y1="19" x2="12" y2="23"></line>
          <line x1="8" y1="23" x2="16" y2="23"></line>
        </svg>
        <span v-if="!isCollapsed">{{ $t('navigation.transcription') }}</span>
      </router-link>

      <!-- <router-link to="/editor" class="nav-link" active-class="active" :title="isCollapsed ? $t('navigation.audioEditor') : ''">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
        </svg>
        <span v-if="!isCollapsed">{{ $t('navigation.audioEditor') }}</span>
      </router-link> -->

      <!-- 所有任務按鈕 -->
      <router-link v-if="authStore.isAuthenticated" to="/tasks" class="nav-link" active-class="active" :title="isCollapsed ? $t('navigation.allTasks') : ''" @click="clearTaskFilters">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <!-- 9條-45度斜線構成的正方形 -->
          <!-- 線 2 -->
          <line x1="0.8" y1="5.4" x2="5.4" y2="0.8"/>
          <!-- 線 3 -->
          <line x1="0.8" y1="10" x2="10" y2="0.8"/>
          <!-- 線 4 -->
          <line x1="0.8" y1="14.6" x2="14.6" y2="0.8"/>
          <!-- 線 5：反對角線 -->
          <line x1="0.8" y1="19.2" x2="19.2" y2="0.8"/>
          <!-- 線 6 -->
          <line x1="5.4" y1="19.2" x2="19.2" y2="5.4"/>
          <!-- 線 7 -->
          <line x1="10" y1="19.2" x2="19.2" y2="10"/>
          <!-- 線 8 -->
          <line x1="14.6" y1="19.2" x2="19.2" y2="14.6"/>
        </svg>
        <span v-if="!isCollapsed">{{ $t('navigation.allTasks') }}</span>
      </router-link>
    </div>

    <!-- 最近任務預覽（展開時顯示） -->
    <div v-if="authStore.isAuthenticated && !isCollapsed" class="recent-tasks">
      <div class="recent-tasks-header">
        <h3>{{ $t('navigation.recent') }}</h3>
      </div>

      <div class="recent-tasks-list">
        <div v-if="recentTasks.length === 0" class="recent-task-empty">
          {{ $t('navigation.noCompletedTasks') }}
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
      <button @click="handleLogout" class="logout-btn" :title="isCollapsed ? $t('navigation.logout') : ''">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
          <polyline points="16 17 21 12 16 7"></polyline>
          <line x1="21" y1="12" x2="9" y2="12"></line>
        </svg>
        <span v-if="!isCollapsed">{{ $t('navigation.logout') }}</span>
      </button>
    </div>
  </nav>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'

const { t: $t } = useI18n()

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
    console.error('Failed to load recent tasks:', error)
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

// 清除任務列表篩選狀態
function clearTaskFilters() {
  try {
    sessionStorage.removeItem('taskList_filterTags')
    sessionStorage.removeItem('taskList_taskType')
  } catch (error) {
    console.error('Failed to clear task filters:', error)
  }
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
/* CSS 變數 */
.navigation {
  /* --texture-pattern:
    repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(255, 255, 255, 0.018) 3px, rgba(255, 255, 255, 0.018) 4px),
    repeating-linear-gradient(0deg, transparent, transparent 9px, rgba(255, 255, 255, 0.028) 9px, rgba(255, 255, 255, 0.028) 11px),
    repeating-linear-gradient(0deg, transparent, transparent 19px, rgba(255, 255, 255, 0.038) 19px, rgba(255, 255, 255, 0.038) 21px),
    repeating-linear-gradient(90deg, transparent, transparent 5px, rgba(0, 0, 0, 0.018) 5px, rgba(0, 0, 0, 0.018) 6px),
    repeating-linear-gradient(90deg, transparent, transparent 13px, rgba(0, 0, 0, 0.028) 13px, rgba(0, 0, 0, 0.028) 15px),
    repeating-linear-gradient(90deg, transparent, transparent 31px, rgba(0, 0, 0, 0.038) 31px, rgba(0, 0, 0, 0.038) 33px); */
  --color-divider-rgb: 163, 177, 198;
}

.navigation {
  width: 240px;
  min-width: 240px;
  height: 100vh;
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 28px 20px;
  background: var(--nav-bg);
  border-radius: 0;
  transition: all 0.3s ease;
}

.navigation::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-image: var(--texture-pattern);
  pointer-events: none;
  opacity: 0.4;
  z-index: 0;
}

/* 收合狀態 */
.navigation.collapsed {
  width: 80px;
  min-width: 80px;
  padding: 28px 12px;
  align-items: center;
}

/* 切換按鈕 */
.toggle-btn {
  position: absolute;
  top: 4px;
  right: 2px;
  width: 28px;
  height: 36px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
  z-index: 10;
}

.toggle-btn:hover {
  transform: translateX(-2px);
}

.toggle-btn:active {
  transform: translateX(0);
}

.toggle-btn svg {
  stroke: var(--main-primary);
  transition: all 0.2s ease;
}

.nav-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding-bottom: 20px;
  position: relative;
}

.nav-brand::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 80px;
  right: -50px;
  height: 1px;
  background-color: var(--color-black);
}

.nav-brand h2 {
  font-size: 1.5rem;
  margin: 0;
  font-weight: 500;
  letter-spacing: -0.5px;
  color: var(--nav-text);
  text-align: center;
  transition: all 0.3s ease;
}

.navigation.collapsed .nav-brand {
  padding-bottom: 16px;
}

.brand-icon {
  color: var(--nav-text);
  flex-shrink: 0;
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
  color: var(--nav-text);
  /* background: var(--nav-bg); */
  transition: all 0.3s ease;
}

.nav-link:hover {
  color: var(--main-primary);
  transform: translateX(4px);
}

.nav-link.active {
  color: var(--nav-recent-text);
  background: var(--nav-active-bg);
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
  background: var(--nav-recent-bg);
  margin: 0 -20px -24px -20px;
  padding-bottom: 24px;
  position: relative;
}

.nav-spacer::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-image: var(--texture-pattern);
  pointer-events: none;
  opacity: 0.3;
}

.navigation.collapsed .nav-spacer {
  margin: 0 -12px -24px -12px;
}

.nav-user {
  display: flex;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 20px 20px 28px 20px;
  margin: 0 -20px -28px -20px;
  /* background: var(--nav-recent-bg); */
  border-top: 1px solid rgba(var(--color-divider-rgb), 0.2);
  transition: all 0.3s ease;
  position: relative;
}

.nav-user::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-image: var(--texture-pattern);
  pointer-events: none;
  opacity: 0.1;
  z-index: 0;
}

/* 收合狀態下的使用者區域 - 垂直排列 */
.navigation.collapsed .nav-user {
  flex-direction: column;
  gap: 12px;
  padding: 20px 12px 20px 12px;
  margin: 0 -12px -20px -12px;
  background: transparent;
  border-top: none;
}

.navigation.collapsed .nav-user::before {
  display: none;
}

.user-avatar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  transition: transform 0.2s ease;
  position: relative;
  z-index: 1;
}

.user-avatar-btn:hover {
  transform: translateY(-2px);
}

.avatar-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--nav-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--nav-text);
  transition: all 0.3s ease;
  cursor: pointer;
}

.avatar-circle:hover {
  color: var(--main-primary-dark);
}


.logout-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  border: none;
  background: var(--nav-bg);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--nav-text);
  transition: all 0.3s ease;
  position: relative;
  z-index: 1;
}

.logout-btn:hover {
  color: var(--main-primary);
  transform: translateY(-2px);
}

.logout-btn:active {
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
  padding: 16px 20px 24px 20px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow: hidden;
  /* background: var(--nav-bg); */
  margin: 0 -20px -24px -20px;
  border-radius: 0;
  position: relative;
}

.recent-tasks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px;
  margin-bottom: 8px;
  position: relative;
  z-index: 1;
}

.recent-tasks-header h3 {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--nav-text);
  margin: 0;
}

.recent-tasks-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  max-height: 300px;
  padding-right: 4px;
  position: relative;
  z-index: 1;
}

.recent-tasks-list::-webkit-scrollbar {
  width: 4px;
}

.recent-tasks-list::-webkit-scrollbar-track {
  background: transparent;
}

.recent-tasks-list::-webkit-scrollbar-thumb {
  background: rgba(var(--color-divider-rgb), 0.3);
  border-radius: 2px;
}

.recent-task-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 3px 12px;
  border-radius: 8px;
  background: transparent;
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
}

.recent-task-item:hover {
  transform: translateX(2px);
}

.recent-task-item:active {
  transform: translateX(0);
}

.task-name {
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--nav-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
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
