<template>
  <nav class="admin-nav">
    <div class="nav-brand">
      <div class="brand-icon">
        <svg width="28" height="28" viewBox="0 0 28 28">
          <rect x="0" y="0" width="28" height="28" rx="4" fill="currentColor"/>
          <circle cx="14" cy="14" r="2" fill="#f4ecd5"/>
          <circle cx="14" cy="9" r="1.5" fill="#f4ecd5"/>
          <circle cx="18.3" cy="11.5" r="1.5" fill="#f4ecd5"/>
          <circle cx="18.3" cy="16.5" r="1.5" fill="#f4ecd5"/>
          <circle cx="14" cy="19" r="1.5" fill="#f4ecd5"/>
          <circle cx="9.7" cy="16.5" r="1.5" fill="#f4ecd5"/>
          <circle cx="9.7" cy="11.5" r="1.5" fill="#f4ecd5"/>
        </svg>
      </div>
      <span class="brand-text">Admin</span>
    </div>

    <div class="nav-links">
      <router-link to="/" class="nav-link" exact-active-class="active">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 3v18h18"/>
          <path d="M18 17V9"/>
          <path d="M13 17V5"/>
          <path d="M8 17v-3"/>
        </svg>
        <span>系統統計</span>
      </router-link>
      <router-link to="/users" class="nav-link" exact-active-class="active">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
          <circle cx="9" cy="7" r="4"/>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
        </svg>
        <span>用戶管理</span>
      </router-link>
      <router-link to="/tasks" class="nav-link" exact-active-class="active">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 11l3 3L22 4"/>
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
        </svg>
        <span>任務管理</span>
      </router-link>
      <router-link to="/audit-logs" class="nav-link" exact-active-class="active">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
          <polyline points="10 9 9 9 8 9"/>
        </svg>
        <span>操作記錄</span>
      </router-link>
    </div>

    <div class="nav-user">
      <div class="user-info">
        <div class="user-avatar">{{ getInitial(authStore.user?.email) }}</div>
        <span class="user-email">{{ authStore.user?.email }}</span>
      </div>
      <button @click="handleLogout" class="logout-btn" :disabled="loggingOut">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
          <polyline points="16 17 21 12 16 7"/>
          <line x1="21" y1="12" x2="9" y2="12"/>
        </svg>
        <span>{{ loggingOut ? '登出中...' : '登出' }}</span>
      </button>
    </div>
  </nav>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loggingOut = ref(false)

function getInitial(email) {
  if (!email) return '?'
  return email.charAt(0).toUpperCase()
}

async function handleLogout() {
  loggingOut.value = true
  await authStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 12px 24px;
  background: var(--color-bg-card, #ffffff);
  border-bottom: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  margin-bottom: 24px;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  color: var(--color-primary, #dd8448);
}

.brand-text {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--color-text, rgb(145, 106, 45));
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 500;
  font-size: 14px;
  color: var(--color-text-light, #a0917c);
  transition: all 0.2s ease;
}

.nav-link:hover {
  color: var(--color-primary, #dd8448);
  background: rgba(221, 132, 72, 0.08);
}

.nav-link.active {
  color: white;
  background: var(--color-primary, #dd8448);
}

.nav-link.active:hover {
  background: var(--color-primary-dark, #b8762d);
}

.nav-link svg {
  flex-shrink: 0;
}

.nav-user {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-bg, #f5f5f5);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-primary, #dd8448);
  border: 2px solid var(--color-primary, #dd8448);
}

.user-email {
  font-size: 13px;
  color: var(--color-text-light, #a0917c);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--color-danger, #ef4444);
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-danger, #ef4444);
  transition: all 0.2s ease;
}

.logout-btn:hover:not(:disabled) {
  background: var(--color-danger, #ef4444);
  color: white;
}

.logout-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 1024px) {
  .admin-nav {
    flex-wrap: wrap;
    gap: 16px;
  }

  .nav-links {
    order: 3;
    width: 100%;
    justify-content: center;
  }

  .user-email {
    display: none;
  }
}

@media (max-width: 768px) {
  .admin-nav {
    padding: 12px 16px;
  }

  .nav-links {
    gap: 4px;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .nav-link {
    padding: 8px 12px;
    font-size: 13px;
  }

  .nav-link span {
    display: none;
  }

  .logout-btn span {
    display: none;
  }

  .logout-btn {
    padding: 8px;
  }
}
</style>
