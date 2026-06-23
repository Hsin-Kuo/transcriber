<template>
  <div class="app-container">
    <ElectricBorder />
    <main class="content-wrapper" :class="isGuest ? 'guest-full' : 'admin-only'">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import ElectricBorder from './components/shared/ElectricBorder.vue'

const route = useRoute()
// guest 路由（如登入頁）自行掌管整個視窗背景，不套 admin 內容頁的 12px 邊框
const isGuest = computed(() => route.meta.guest === true)
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
  height: 100vh;
  display: flex;
  box-sizing: border-box;
  overflow: hidden;
}

.content-wrapper.admin-only {
  flex: 1;
  max-width: none;
  margin: 0 auto;
  width: 100%;
  height: 100%;
  padding: 12px;
  box-sizing: border-box;
  overflow-y: auto;
}

/* guest 頁（登入）：滿版、無邊框，背景由 view 自行鋪滿整個視窗 */
.content-wrapper.guest-full {
  flex: 1;
  width: 100%;
  height: 100%;
  overflow-y: auto;
}
</style>
