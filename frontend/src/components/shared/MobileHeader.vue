<template>
  <header class="mobile-header">
    <router-link to="/settings" class="mobile-header-avatar" :aria-label="authStore.user?.email || ''" :title="authStore.user?.email">
      <div class="avatar-circle">
        {{ getFirstLetter(authStore.user?.email) }}
      </div>
    </router-link>

    <router-link to="/all" class="mobile-header-brand">
      <img class="brand-icon" src="/favicon.svg" alt="SoundLite" width="24" height="24" />
      <span>SoundLite</span>
    </router-link>

    <!-- 搜尋功能後續補上：目前僅為 placeholder，點擊無動作 -->
    <button class="mobile-header-search" :aria-label="$t('nav.search')" type="button">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
    </button>
  </header>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../../stores/auth'

const { t: $t } = useI18n()
const authStore = useAuthStore()

// 取得郵箱首字母（與 Navigation.vue 邏輯一致）
function getFirstLetter(email) {
  if (!email) return '?'
  return email.charAt(0).toUpperCase()
}
</script>

<style scoped>
/* 桌機不顯示，只在手機版（<=768px）出現 */
.mobile-header {
  display: none;
}

@media (max-width: 768px) {
  .mobile-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: calc(52px + env(safe-area-inset-top, 0px));
    padding: 0 calc(12px + env(safe-area-inset-right, 0px)) 0 calc(12px + env(safe-area-inset-left, 0px));
    padding-top: env(safe-area-inset-top, 0px);
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    z-index: 1000;
  }

  :root[data-theme="dark"] .mobile-header {
    background: rgba(40, 40, 40, 0.95);
  }

  .mobile-header-avatar {
    display: flex;
    align-items: center;
    justify-content: center;
    text-decoration: none;
    flex-shrink: 0;
  }

  .avatar-circle {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: var(--nav-bg);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    font-weight: 700;
    color: var(--nav-text);
  }

  .mobile-header-brand {
    display: flex;
    align-items: center;
    gap: 6px;
    text-decoration: none;
    color: var(--nav-text);
    font-weight: 600;
    font-size: 1rem;
    position: absolute;
    left: 50%;
    transform: translateX(-50%);
  }

  .mobile-header-brand .brand-icon {
    color: var(--nav-active-bg);
    flex-shrink: 0;
  }

  .mobile-header-search {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex-shrink: 0;
    border: none;
    background: transparent;
    color: var(--nav-text);
    cursor: pointer;
    padding: 0;
  }

  .mobile-header-search svg {
    stroke: currentColor;
  }
}
</style>
