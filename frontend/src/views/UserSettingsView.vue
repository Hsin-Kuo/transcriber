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

      <!-- 介面設定 -->
      <div class="card interface-card">
        <h2>{{ $t('userSettings.interface') }}</h2>

        <!-- 語言 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.language') }}</span>
          <div class="custom-select" :class="{ open: languageDropdownOpen }">
            <div class="select-trigger" @click="toggleLanguageDropdown">
              <span>{{ currentLanguageLabel }}</span>
              <svg class="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <div class="select-dropdown">
              <div
                v-for="lang in availableLanguages"
                :key="lang.code"
                class="select-option"
                :class="{ active: currentLanguage === lang.code }"
                @click="selectLanguage(lang.code)"
              >
                {{ lang.name }}
              </div>
            </div>
          </div>
        </div>

        <!-- 時區 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.timezone') }}</span>
          <div class="custom-select" :class="{ open: timezoneDropdownOpen }">
            <div class="select-trigger" @click="toggleTimezoneDropdown">
              <span>{{ currentTimezoneLabel }}</span>
              <svg class="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <div class="select-dropdown">
              <div
                v-for="tz in availableTimezones"
                :key="tz.code"
                class="select-option"
                :class="{ active: currentTimezone === tz.code }"
                @click="selectTimezone(tz.code)"
              >
                {{ tz.name }}
              </div>
            </div>
          </div>
        </div>

        <!-- 色調 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.theme') }}</span>
          <div class="theme-toggle">
            <svg class="theme-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="5"></circle>
              <line x1="12" y1="1" x2="12" y2="3"></line>
              <line x1="12" y1="21" x2="12" y2="23"></line>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
              <line x1="1" y1="12" x2="3" y2="12"></line>
              <line x1="21" y1="12" x2="23" y2="12"></line>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
            </svg>
            <label class="toggle-switch" :class="{ active: currentTheme === 'dark' }">
              <input type="checkbox" :checked="currentTheme === 'dark'" @change="currentTheme = $event.target.checked ? 'dark' : 'light'; changeTheme()" />
              <span class="toggle-slider"></span>
            </label>
            <svg class="theme-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
          </div>
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
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'

const authStore = useAuthStore()
const { t: $t, locale } = useI18n()

// 可用語言列表
const availableLanguages = [
  { code: 'zh-TW', name: '繁體中文' },
  { code: 'en', name: 'English' }
]

// 當前語言
const currentLanguage = ref(locale.value)

// 可用時區列表
const availableTimezones = [
  { code: 'Asia/Taipei', name: 'UTC+8 台北' },
  { code: 'Asia/Tokyo', name: 'UTC+9 東京' },
  { code: 'Asia/Shanghai', name: 'UTC+8 上海' },
  { code: 'Asia/Hong_Kong', name: 'UTC+8 香港' },
  { code: 'America/New_York', name: 'UTC-5 紐約' },
  { code: 'America/Los_Angeles', name: 'UTC-8 洛杉磯' },
  { code: 'Europe/London', name: 'UTC+0 倫敦' }
]

// 當前時區
const currentTimezone = ref(localStorage.getItem('timezone') || 'Asia/Taipei')

// 當前色調
const currentTheme = ref(localStorage.getItem('theme') || 'light')

// 下拉選單狀態
const languageDropdownOpen = ref(false)
const timezoneDropdownOpen = ref(false)

// 當前選項的顯示文字
const currentLanguageLabel = computed(() => {
  const lang = availableLanguages.find(l => l.code === currentLanguage.value)
  return lang ? lang.name : ''
})

const currentTimezoneLabel = computed(() => {
  const tz = availableTimezones.find(t => t.code === currentTimezone.value)
  return tz ? tz.name : ''
})

// 切換下拉選單
function toggleLanguageDropdown() {
  languageDropdownOpen.value = !languageDropdownOpen.value
  timezoneDropdownOpen.value = false
}

function toggleTimezoneDropdown() {
  timezoneDropdownOpen.value = !timezoneDropdownOpen.value
  languageDropdownOpen.value = false
}

// 選擇選項
function selectLanguage(code) {
  currentLanguage.value = code
  changeLanguage()
  languageDropdownOpen.value = false
}

function selectTimezone(code) {
  currentTimezone.value = code
  changeTimezone()
  timezoneDropdownOpen.value = false
}

// 點擊外部關閉下拉選單
function handleClickOutside(event) {
  if (!event.target.closest('.custom-select')) {
    languageDropdownOpen.value = false
    timezoneDropdownOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

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

// 切換時區
function changeTimezone() {
  localStorage.setItem('timezone', currentTimezone.value)
}

// 切換色調
function changeTheme() {
  localStorage.setItem('theme', currentTheme.value)
  document.documentElement.setAttribute('data-theme', currentTheme.value)
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
.interface-card h2 {
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

/* 介面設定樣式 */
.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.setting-item:last-child {
  border-bottom: none;
}

.setting-label {
  font-size: 0.95rem;
  color: var(--main-text-light);
  font-weight: 500;
}

/* 自訂下拉選單 */
.custom-select {
  position: relative;
  min-width: 140px;
}

.select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  background: var(--main-bg);
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--main-text);
  transition: all 0.2s ease;
}

.select-trigger:hover {
  background: rgba(163, 177, 198, 0.15);
}

.select-arrow {
  color: var(--main-text-light);
  transition: transform 0.2s ease;
}

.custom-select.open .select-arrow {
  transform: rotate(180deg);
}

.select-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 100%;
  background: var(--card-bg, #fff);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-8px);
  transition: all 0.2s ease;
  z-index: 100;
  overflow: hidden;
}

.custom-select.open .select-dropdown {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.select-option {
  padding: 10px 14px;
  font-size: 14px;
  color: var(--main-text);
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.select-option:hover {
  background: rgba(163, 177, 198, 0.15);
}

.select-option.active {
  background: var(--nav-active-bg);
  color: white;
}

/* 色調開關 */
.theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.theme-icon {
  color: var(--main-text-light);
  opacity: 0.6;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
  cursor: pointer;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: #dedede;
  border-radius: 22px;
  transition: all 0.3s ease;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: all 0.3s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.toggle-switch.active .toggle-slider {
  background: var(--nav-active-bg);
}

.toggle-switch.active .toggle-slider::before {
  transform: translateX(18px);
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
