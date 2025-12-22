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
      <router-link to="/tasks" class="nav-link" active-class="active">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 11l3 3L22 4"></path>
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
        </svg>
        <span>所有任務</span>
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

    <div v-if="authStore.isAuthenticated" class="nav-user">
      <span class="user-email">{{ authStore.user?.email }}</span>
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
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// 根據當前路由決定主題
const themeClass = computed(() => {
  return route.path === '/' ? 'glass-theme' : 'dark-theme'
})

// 登出處理
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
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
  flex: 1;
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
  background: linear-gradient(145deg, #d1d9e6, #e9eef5);
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
  flex-direction: column;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid rgba(163, 177, 198, 0.2);
}

.user-email {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--neu-text-light);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

  .user-email {
    flex: 1;
    text-align: left;
  }
}
</style>
