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
    <NotificationToast ref="notificationToast" />
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
import { ref, provide, computed } from 'vue'
import { useRoute } from 'vue-router'
import ElectricBorder from './components/shared/ElectricBorder.vue'
import Navigation from './components/shared/Navigation.vue'
import NotificationToast from './components/NotificationToast.vue'

const route = useRoute()
const notificationToast = ref(null)

// 判斷是否顯示導航欄（訪客頁面不顯示）
const showNavigation = computed(() => {
  return !route.meta.guest
})

// 提供全局通知方法
provide('showNotification', (options) => {
  if (notificationToast.value) {
    return notificationToast.value.addNotification(options)
  }
})
</script>

<style>
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
