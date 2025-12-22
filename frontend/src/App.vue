<template>
  <div class="app-container">
    <ElectricBorder />
    <Navigation />
    <main class="content-wrapper">
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
import Navigation from './components/shared/Navigation.vue'
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
  padding: 20px 20px 20px 8px;
}

.content-wrapper {
  flex: 1;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

@media (max-width: 768px) {
  .app-container {
    flex-direction: column;
  }
}
</style>
