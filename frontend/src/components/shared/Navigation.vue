<template>
  <nav class="navigation electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main nav-content" :class="themeClass">
          <div class="nav-brand">
            <h2>🎙️ Whisper 音訊工具箱</h2>
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
            <router-link to="/editor" class="nav-link" active-class="active">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
              </svg>
              <span>音訊剪輯</span>
            </router-link>
          </div>
        </div>
      </div>
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>
  </nav>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

// 根據當前路由決定主題
const themeClass = computed(() => {
  return route.path === '/' ? 'glass-theme' : 'dark-theme'
})
</script>

<style scoped>
.navigation {
  margin-bottom: 24px;
  position: sticky;
  top: 20px;
  z-index: 100;
  transition: all 0.3s ease;
}

.nav-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  transition: all 0.3s ease;
}

/* 玻璃主題 - 用於轉錄頁面 */
.nav-content.glass-theme {
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(15px) saturate(180%);
  -webkit-backdrop-filter: blur(15px) saturate(180%);
}

.nav-content.glass-theme .nav-brand h2 {
  color: #8b4513;
}

.nav-content.glass-theme .nav-link {
  color: #666;
}

.nav-content.glass-theme .nav-link:hover {
  background: rgba(139, 69, 19, 0.1);
  color: #8b4513;
  border-color: rgba(139, 69, 19, 0.3);
}

.nav-content.glass-theme .nav-link.active {
  background: rgba(139, 69, 19, 0.15);
  color: #8b4513;
  border-color: rgba(139, 69, 19, 0.4);
}

/* 深色主題 - 用於剪輯頁面 */
.nav-content.dark-theme {
  background: linear-gradient(135deg, rgba(28, 28, 28, 0.95) 0%, rgba(20, 20, 20, 0.95) 100%);
}

.nav-content.dark-theme .nav-brand h2 {
  color: #DD8448;
}

.nav-content.dark-theme .nav-link {
  color: #aaa;
}

.nav-content.dark-theme .nav-link:hover {
  background: rgba(255, 107, 53, 0.1);
  color: #FF6B35;
  border-color: rgba(255, 107, 53, 0.3);
}

.nav-content.dark-theme .nav-link.active {
  background: rgba(221, 132, 72, 0.2);
  color: #DD8448;
  border-color: rgba(221, 132, 72, 0.5);
}

/* 共用樣式 */
.nav-brand h2 {
  font-size: 1.5rem;
  margin: 0;
  font-weight: 600;
  letter-spacing: -0.5px;
  transition: color 0.3s ease;
}

.nav-links {
  display: flex;
  gap: 12px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 500;
  transition: all 0.3s ease;
  border: 1px solid transparent;
}

.nav-link svg {
  stroke: currentColor;
}

@media (max-width: 640px) {
  .nav-content {
    flex-direction: column;
    gap: 16px;
  }

  .nav-links {
    width: 100%;
    justify-content: center;
  }

  .nav-link span {
    display: none;
  }
}
</style>
