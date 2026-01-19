<template>
  <div class="settings-container">
    <div class="settings-header">
      <h1>{{ $t('userSettings.title') }}</h1>
      <p>{{ $t('userSettings.description') }}</p>
    </div>

    <div class="settings-grid">
      <!-- 使用者資訊 -->
      <div class="card user-info-card">
        <h2>{{ $t('userSettings.accountInfo') }}</h2>
        <div class="info-item">
          <span class="info-label">{{ $t('userSettings.email') }}</span>
          <span class="info-value">{{ authStore.user?.email }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">{{ $t('userSettings.accountType') }}</span>
          <span class="info-value">{{ quotaTierName }}</span>
        </div>
      </div>

      <!-- 語言設定 -->
      <div class="card language-card">
        <h2>{{ $t('userSettings.language') }}</h2>
        <p class="language-description">{{ $t('userSettings.languageDescription') }}</p>
        <div class="language-select-wrapper">
          <select
            v-model="currentLanguage"
            @change="changeLanguage"
            class="language-select"
          >
            <option
              v-for="lang in availableLanguages"
              :key="lang.code"
              :value="lang.code"
            >
              {{ lang.name }}
            </option>
          </select>
        </div>
      </div>

      <!-- 配額顯示 -->
      <div class="quota-card electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main quota-content">
              <div class="quota-header">
                <h3>{{ $t('userSettings.quotaUsage') }}</h3>
                <span class="quota-tier">{{ quotaTierName }}</span>
              </div>

              <div class="quota-items">
                <div class="quota-item">
                  <div class="quota-label">
                    <span>{{ $t('userSettings.transcriptions') }}</span>
                    <span class="quota-value">{{ authStore.usage?.transcriptions || 0 }} / {{ authStore.quota?.max_transcriptions || 0 }}</span>
                  </div>
                  <div class="quota-bar">
                    <div
                      class="quota-progress"
                      :class="{ 'quota-warning': authStore.quotaPercentage?.transcriptions > 80 }"
                      :style="{ width: `${authStore.quotaPercentage?.transcriptions || 0}%` }"
                    ></div>
                  </div>
                  <div class="quota-remaining">
                    {{ $t('userSettings.remaining') }} {{ authStore.remainingQuota?.transcriptions || 0 }}
                  </div>
                </div>

                <div class="quota-item">
                  <div class="quota-label">
                    <span>{{ $t('userSettings.duration') }}</span>
                    <span class="quota-value">{{ Math.round(authStore.usage?.duration_minutes || 0) }} / {{ authStore.quota?.max_duration_minutes || 0 }} {{ $t('userSettings.minutes') }}</span>
                  </div>
                  <div class="quota-bar">
                    <div
                      class="quota-progress"
                      :class="{ 'quota-warning': authStore.quotaPercentage?.duration > 80 }"
                      :style="{ width: `${authStore.quotaPercentage?.duration || 0}%` }"
                    ></div>
                  </div>
                  <div class="quota-remaining">
                    {{ $t('userSettings.remaining') }} {{ Math.round(authStore.remainingQuota?.duration || 0) }} {{ $t('userSettings.minutes') }}
                  </div>
                </div>

                <div class="quota-item">
                  <div class="quota-label">
                    <span>{{ $t('userSettings.storage') }}</span>
                    <span class="quota-value">{{ formatBytes(authStore.usage?.storage_bytes || 0) }} / {{ formatBytes(authStore.quota?.max_storage_bytes || 0) }}</span>
                  </div>
                  <div class="quota-bar">
                    <div
                      class="quota-progress"
                      :class="{ 'quota-warning': authStore.quotaPercentage?.storage > 80 }"
                      :style="{ width: `${authStore.quotaPercentage?.storage || 0}%` }"
                    ></div>
                  </div>
                  <div class="quota-remaining">
                    {{ $t('userSettings.remaining') }} {{ formatBytes(authStore.remainingQuota?.storage || 0) }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'

const authStore = useAuthStore()
const { t: $t, locale } = useI18n()

// 可用語言列表
const availableLanguages = [
  { code: 'zh-TW', name: '繁體中文' },
  { code: 'en', name: 'English' }
  // 未來可以在這裡新增更多語言
  // { code: 'ja', name: '日本語' },
  // { code: 'ko', name: '한국어' },
]

// 當前語言
const currentLanguage = ref(locale.value)

// 配額層級名稱
const quotaTierName = computed(() => {
  const tier = authStore.quota?.tier || 'free'
  const tierNames = {
    free: '免費版',
    basic: '基礎版',
    pro: '專業版',
    enterprise: '企業版'
  }
  return tierNames[tier] || '未知'
})

// 格式化位元組大小
function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
}

// 切換語言
function changeLanguage() {
  locale.value = currentLanguage.value
  localStorage.setItem('locale', currentLanguage.value)
}
</script>

<style scoped>
.settings-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

.settings-header {
  margin-top: 30px;
  margin-bottom: 32px;
  text-align: center;
}

.settings-header h1 {
  font-size: 2rem;
  color: var(--main-primary);
  margin: 0 0 8px 0;
  font-weight: 700;
}

.settings-header p {
  color: var(--main-text-light);
  margin: 0;
  font-size: 1rem;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.quota-card {
  grid-column: 1 / -1;
}

.user-info-card h2,
.language-card h2 {
  font-size: 1.25rem;
  color: var(--main-primary);
  margin: 0 0 20px 0;
  font-weight: 600;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.info-item:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 0.95rem;
  color: var(--main-text-light);
  font-weight: 500;
}

.info-value {
  font-size: 0.95rem;
  color: var(--main-text);
  font-weight: 600;
}

/* 語言設定樣式 */
.language-description {
  font-size: 0.9rem;
  color: var(--main-text-light);
  margin: 0 0 16px 0;
}

.language-select-wrapper {
  position: relative;
}

.language-select {
  width: 100%;
  padding: 12px 16px;
  border: none;
  border-radius: 8px;
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  appearance: none;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236c8ba3' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 12px center;
  background-size: 20px;
  padding-right: 40px;
}



.language-select:focus {
  outline: none;
  box-shadow: 0 0 0 3px rgba(108, 139, 163, 0.2);
}

.language-select option {
  background: var(--main-bg);
  color: var(--main-text);
  padding: 10px;
}

/* 配額卡片樣式 */

.quota-content {
  padding: 24px;
  background: var(--main-bg);
}

.quota-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid rgba(163, 177, 198, 0.2);
}

.quota-header h3 {
  margin: 0;
  font-size: 1.25rem;
  color: var(--main-primary);
  font-weight: 600;
}

.quota-tier {
  padding: 6px 16px;
  background: var(--main-bg);
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--main-primary);
}

.quota-items {
  display: grid;
  gap: 24px;
}

.quota-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.quota-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.95rem;
  color: var(--main-text);
  font-weight: 500;
}

.quota-value {
  font-weight: 600;
  color: var(--main-primary);
}

.quota-bar {
  height: 10px;
  background: var(--main-bg);
  border-radius: 8px;
  overflow: hidden;
}

.quota-progress {
  height: 100%;
  background: linear-gradient(90deg, var(--main-primary), var(--main-primary-light));
  border-radius: 8px;
  transition: width 0.3s ease, background 0.3s ease;
  box-shadow: 0 0 8px rgba(108, 139, 163, 0.3);
}

.quota-progress.quota-warning {
  background: linear-gradient(90deg, #ff6b35, #ff8c42);
  box-shadow: 0 0 8px rgba(255, 107, 53, 0.4);
}

.quota-remaining {
  font-size: 0.85rem;
  color: var(--main-text-light);
  text-align: right;
}

@media (max-width: 768px) {
  .settings-container {
    padding: 0 16px;
  }

  .settings-header h1 {
    font-size: 1.75rem;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }

  .quota-card {
    grid-column: 1;
  }

  .quota-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .quota-tier {
    align-self: flex-end;
  }
}
</style>
