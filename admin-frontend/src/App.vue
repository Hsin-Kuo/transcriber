<template>
  <div class="app-container">
    <ElectricBorder />
    <main class="content-wrapper admin-only">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import ElectricBorder from './components/shared/ElectricBorder.vue'
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
  padding: 20px;
  box-sizing: border-box;
  overflow: hidden;
}

.content-wrapper.admin-only {
  flex: 1;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  height: 100%;
  overflow-y: auto;
}
</style>
