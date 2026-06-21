<template>
  <div class="app-container" :class="{ 'no-nav': !showNavigation }">
    <ElectricBorder />
    <Navigation v-if="showNavigation" />
    <main class="content-wrapper">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
    <!-- 右下角通知堆疊：上傳進度浮層 + toast 共用同一欄，避免互相覆蓋、視覺一致 -->
    <Teleport to="body">
      <div class="notify-stack">
        <!-- 上傳浮層在上、toast 在下（靠近右下角最易點） -->
        <GlobalUploadProgress />
        <NotificationToast ref="notificationToast" />
      </div>
    </Teleport>
    <!-- 全域方案面板 / 額度不足對話框（任何頁面可觸發）-->
    <PlanPanel v-model="uiStore.planPanelOpen" :current-tier="currentTier" @plan-changed="handlePlanChanged" />
    <QuotaExceededModal />
    <!-- 右下角三角形裝飾線 -->
    <!-- <svg class="corner-decoration" viewBox="0 0 130 100" preserveAspectRatio="xMaxYMax meet"> -->
      <!-- 正三角形的兩條上邊（從右下角→頂點→左下角） -->
      <!-- <polyline
        points="180,100 100,0 20,100"
        fill="none"
        stroke="#000"
        stroke-width="0.8"
        vector-effect="non-scaling-stroke"
      />
    </svg> -->
  </div>
</template>

<script setup>
import { ref, provide, computed, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import ElectricBorder from './components/shared/ElectricBorder.vue'
import Navigation from './components/shared/Navigation.vue'
import NotificationToast from './components/NotificationToast.vue'
import GlobalUploadProgress from './components/GlobalUploadProgress.vue'
// 方案面板與額度對話框只在使用者主動觸發時才需要 → 延後載入，不進主 bundle
const PlanPanel = defineAsyncComponent(() => import('./components/PlanPanel.vue'))
const QuotaExceededModal = defineAsyncComponent(() => import('./components/QuotaExceededModal.vue'))
import { useAuthStore } from './stores/auth'
import { useUiStore } from './stores/ui'

const { t: $t } = useI18n()
const route = useRoute()
const notificationToast = ref(null)
const authStore = useAuthStore()
const uiStore = useUiStore()
const currentTier = computed(() => authStore.quota?.tier || 'free')

function handlePlanChanged(event) {
  if (event.action === 'upgraded') {
    notificationToast.value?.addNotification({ title: $t('userSettings.subscription.upgradedSuccess'), type: 'success' })
  } else if (event.action === 'downgraded') {
    notificationToast.value?.addNotification({ title: $t('userSettings.subscription.downgradedSuccess'), type: 'success' })
  }
}

// 判斷是否顯示導航欄（訪客頁面不顯示）
const showNavigation = computed(() => {
  return !route.meta.guest && !route.meta.hideNav
})

// 提供全局通知方法
provide('showNotification', (options) => {
  if (notificationToast.value) {
    return notificationToast.value.addNotification(options)
  }
})

function handleRateLimit() {
  if (notificationToast.value) {
    notificationToast.value.addNotification({
      title: $t('apiError.rateLimitedTitle'),
      message: $t('apiError.rateLimitedMessage'),
      type: 'warning',
    })
  }
}

function handleServerError() {
  if (notificationToast.value) {
    notificationToast.value.addNotification({
      title: $t('apiError.serverErrorTitle'),
      message: $t('apiError.serverErrorMessage'),
      type: 'error',
    })
  }
}

function handleNetworkError() {
  if (notificationToast.value) {
    notificationToast.value.addNotification({
      title: $t('apiError.networkErrorTitle'),
      message: $t('apiError.networkErrorMessage'),
      type: 'error',
    })
  }
}

// navigator.onLine / offline 事件在 macOS Wi-Fi 省電休眠、背景 tab throttling 時會誤觸發，
// 改靠 api:network-error（實際 request 失敗才 fire）作為唯一離線信號。
onMounted(() => {
  window.addEventListener('api:rate-limited', handleRateLimit)
  window.addEventListener('api:server-error', handleServerError)
  window.addEventListener('api:network-error', handleNetworkError)
})

onUnmounted(() => {
  window.removeEventListener('api:rate-limited', handleRateLimit)
  window.removeEventListener('api:server-error', handleServerError)
  window.removeEventListener('api:network-error', handleNetworkError)
})
</script>

<style>
/* 右下角通知堆疊容器：上傳浮層 + toast 共用同一欄，垂直堆疊不重疊。
   teleport 到 body，避免任何祖層 overflow/transform 影響 fixed 定位。 */
.notify-stack {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
  pointer-events: none; /* 子卡片各自 re-enable */
  max-width: calc(100vw - 40px);
}

@media (max-width: 768px) {
  .notify-stack {
    left: 12px;
    right: 12px;
    bottom: calc(60px + env(safe-area-inset-bottom, 0px) + 8px);
    align-items: stretch;
  }
}

/* 路由過渡動畫 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.app-container {
  min-height: 100vh;
  display: flex;
  gap: 20px;
  padding: 0 20px 20px 0;
  padding-left: 240px;
  box-sizing: border-box;
  transition: padding-left 0.3s ease;
}

body.nav-collapsed .app-container {
  padding-left: 80px;
}

/* 沒有導航欄時的樣式調整 */
.app-container.no-nav,
body.nav-collapsed .app-container.no-nav {
  padding: 0;
  padding-left: 0;
  gap: 0;
}

.app-container.no-nav .content-wrapper {
  max-width: none;
  margin: 0;
}

.content-wrapper {
  flex: 1;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

/* 編輯狀態下限制視窗高度 */
body.editing-transcript .app-container {
  height: 100vh;
  overflow: hidden;
}

body.editing-transcript .content-wrapper {
  height: 100%;
  overflow-y: auto;
}

/* 上傳頁面限制視窗高度 */
body.upload-page .app-container {
  height: 100vh;
  overflow: hidden;
}

body.upload-page .content-wrapper {
  height: 100%;
  overflow-y: auto;
}

/* 逐字稿詳情頁面限制視窗高度 */
body.transcript-detail-page .app-container {
  height: 100vh;
  overflow: hidden;
}

body.transcript-detail-page .content-wrapper {
  height: 100%;
  overflow: hidden;
  max-width: none;
}

/* 手機版任務詳情頁面隱藏導航列 */
@media (max-width: 768px) {
  body.transcript-detail-page .navigation {
    display: none;
  }

  body.transcript-detail-page .app-container {
    padding-bottom: 0;
  }
}

@media (max-width: 768px) {
  .app-container,
  body.nav-collapsed .app-container {
    flex-direction: column;
    padding: 0 12px;
    padding-left: 12px;
    gap: 0;
    /* 為底部固定導航留出空間 */
    padding-bottom: calc(60px + env(safe-area-inset-bottom, 0px));
  }

  .content-wrapper {
    padding-top: 12px;
  }
}

@media (max-width: 480px) {
  .app-container,
  body.nav-collapsed .app-container {
    padding: 0 8px;
    padding-left: 8px;
    padding-bottom: calc(52px + env(safe-area-inset-bottom, 0px));
  }

  .content-wrapper {
    padding-top: 8px;
  }
}

/* 右下角三角形裝飾線（SVG 響應式） */
.corner-decoration {
  position: fixed;
  bottom: 0;
  right: 0;
  width: 200vw;  /* 視窗寬度的 8% */
  height: 200vh; /* 視窗高度的 8% */
  min-width: 60px;  /* 最小寬度，避免太小 */
  min-height: 60px; /* 最小高度，避免太小 */
  max-width: 500px; /* 最大寬度，避免太大 */
  max-height: 500px; /* 最大高度，避免太大 */
  pointer-events: none;
  z-index: 000;
}

/* 響應式：小螢幕縮小 */
@media (max-width: 768px) {
  .corner-decoration {
    width: 16vw;
    height: 16vh;
    min-width: 40px;
    min-height: 40px;
    max-width: 80px;
    max-height: 80px;
  }
}
</style>
