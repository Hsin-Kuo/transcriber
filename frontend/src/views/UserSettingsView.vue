<template>
  <div class="settings-container">
    <div class="settings-header">
      <h1>{{ $t('userSettings.title') }}</h1>
      <p>{{ $t('userSettings.description') }}</p>
    </div>

    <!-- 使用者資訊顯示面板 -->
    <div class="user-display-wrapper">
      <!-- 左側標籤 -->
      <div class="display-labels">
        <span class="label-item">{{ $t('userSettings.account') }}</span>
        <span class="label-item">{{ $t('userSettings.plan') }}</span>
        <span class="label-item">{{ $t('userSettings.language') }}</span>
        <span class="label-item">{{ $t('userSettings.timezone') }}</span>
        <span class="label-item">{{ $t('userSettings.theme') }}</span>
        <span class="label-item">AI Summary</span>
        <span class="label-item">{{ $t('userSettings.tasks') }}</span>
        <span class="label-bar"></span>
        <span class="label-item">{{ $t('userSettings.duration') }}</span>
        <span class="label-bar"></span>
      </div>

      <!-- 右側顯示面板 -->
      <div class="user-display-panel">
        <div class="display-row">
          <span class="display-value">{{ authStore.user?.email || '---' }}</span>
        </div>
        <div class="display-row">
          <span class="display-value plan-tiers">
            <span :class="{ active: currentTier === 'free' }">FREE</span>
            <span :class="{ active: currentTier === 'basic' }">BASIC</span>
            <span :class="{ active: currentTier === 'pro' }">PRO</span>
            <span :class="{ active: currentTier === 'enterprise' }">ENT</span>
          </span>
        </div>
        <div class="display-row">
          <span class="display-value">{{ currentLanguageLabel }}</span>
        </div>
        <div class="display-row">
          <span class="display-value">{{ getTimezoneShort(currentTimezone) }}</span>
        </div>
        <div class="display-row">
          <span class="display-value theme-icons">
            <!-- 太陽 -->
            <svg :class="{ active: currentTheme === 'light' }" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
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
            <!-- 月亮 -->
            <svg :class="{ active: currentTheme === 'dark' }" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
          </span>
        </div>

        <!-- AI Summary 展開模式 -->
        <div class="display-row">
          <span class="display-value">{{ currentSummaryExpandLabel }}</span>
        </div>

        <!-- 轉錄次數 -->
        <div class="display-row usage-row">
          <span class="display-value usage-value">{{ authStore.usage?.transcriptions || 0 }}/{{ authStore.quota?.max_transcriptions || 0 }}</span>
        </div>
        <div class="display-bar">
          <span class="bar-fill" :style="{ width: (authStore.quotaPercentage?.transcriptions || 0) + '%' }"></span>
        </div>

        <!-- 時長 -->
        <div class="display-row usage-row">
          <span class="display-value usage-value">{{ Math.round(authStore.usage?.duration_minutes || 0) }}/{{ authStore.quota?.max_duration_minutes || 0 }}m</span>
        </div>
        <div class="display-bar">
          <span class="bar-fill" :style="{ width: (authStore.quotaPercentage?.duration || 0) + '%' }"></span>
        </div>
      </div>
    </div>

    <div class="settings-grid">
      <!-- 帳戶安全 -->
      <div class="card security-card">
        <h2>{{ $t('userSettings.security') }}</h2>

        <!-- 密碼設定 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.password') }}</span>
          <div v-if="authStore.hasPassword">
            <button class="change-password-btn" @click="showPasswordModal = true">
              {{ $t('userSettings.changePassword') }}
            </button>
          </div>
          <div v-else>
            <button class="change-password-btn" @click="showSetPasswordModal = true">
              {{ $t('userSettings.setPassword') }}
            </button>
          </div>
        </div>

        <!-- Google 綁定 -->
        <div v-if="googleClientId" class="setting-item google-setting">
          <div class="setting-left">
            <span class="setting-label">{{ $t('userSettings.googleAccount') }}</span>
            <span v-if="authStore.hasGoogle" class="connected-status">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
              {{ $t('userSettings.connected') }}
            </span>
          </div>
          <div class="setting-right">
            <!-- 未綁定：顯示綁定按鈕 -->
            <div v-if="!authStore.hasGoogle" class="google-bind-wrapper">
              <GoogleSignInButton
                :key="'google-bind-' + locale"
                :client-id="googleClientId"
                button-text="signin_with"
                size="medium"
                :width="200"
                @success="handleGoogleBindSuccess"
                @error="handleGoogleBindError"
              />
            </div>
            <!-- 已綁定：顯示解除綁定按鈕 -->
            <div v-else>
              <button
                class="unbind-btn"
                @click="confirmUnbindGoogle"
                :disabled="googleLoading"
              >
                {{ googleLoading ? $t('userSettings.processing') : $t('userSettings.unbind') }}
              </button>
            </div>
          </div>
        </div>

        <!-- Google 操作訊息 -->
        <div v-if="googleError" class="google-message error">{{ googleError }}</div>
        <div v-if="googleSuccess" class="google-message success">{{ googleSuccess }}</div>
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

        <!-- AI 摘要展開 -->
        <div class="setting-item">
          <span class="setting-label">{{ $t('userSettings.summaryExpand') }}</span>
          <div class="custom-select" :class="{ open: summaryExpandDropdownOpen }">
            <div class="select-trigger" @click="toggleSummaryExpandDropdown">
              <span>{{ currentSummaryExpandLabel }}</span>
              <svg class="select-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <div class="select-dropdown">
              <div
                class="select-option"
                :class="{ active: summaryExpandMode === 'always-open' }"
                @click="selectSummaryExpandMode('always-open')"
              >
                {{ $t('userSettings.summaryAlwaysOpen') }}
              </div>
              <div
                class="select-option"
                :class="{ active: summaryExpandMode === 'always-collapsed' }"
                @click="selectSummaryExpandMode('always-collapsed')"
              >
                {{ $t('userSettings.summaryAlwaysCollapsed') }}
              </div>
              <div
                class="select-option"
                :class="{ active: summaryExpandMode === 'follow-last' }"
                @click="selectSummaryExpandMode('follow-last')"
              >
                {{ $t('userSettings.summaryFollowLast') }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 更改密碼 Modal -->
    <div v-if="showPasswordModal" class="modal-overlay" @click.self="closePasswordModal">
      <div class="modal">
        <h3>{{ $t('userSettings.changePassword') }}</h3>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ $t('userSettings.currentPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="passwordForm.currentPassword"
                :type="showCurrentPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.currentPasswordPlaceholder')"
              />
              <button type="button" class="password-toggle" @click="showCurrentPassword = !showCurrentPassword" tabindex="-1">
                <svg v-if="showCurrentPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.newPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="passwordForm.newPassword"
                :type="showNewPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.newPasswordPlaceholder')"
                @input="validateNewPassword"
              />
              <button type="button" class="password-toggle" @click="showNewPassword = !showNewPassword" tabindex="-1">
                <svg v-if="showNewPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
            <div v-if="passwordForm.newPassword" class="password-requirements">
              <div class="requirement" :class="{ met: newPasswordChecks.length }">
                {{ newPasswordChecks.length ? '✓' : '○' }} {{ $t('userSettings.reqLength') }}
              </div>
              <div class="requirement" :class="{ met: newPasswordChecks.hasUpper }">
                {{ newPasswordChecks.hasUpper ? '✓' : '○' }} {{ $t('userSettings.reqUppercase') }}
              </div>
              <div class="requirement" :class="{ met: newPasswordChecks.hasLower }">
                {{ newPasswordChecks.hasLower ? '✓' : '○' }} {{ $t('userSettings.reqLowercase') }}
              </div>
              <div class="requirement" :class="{ met: newPasswordChecks.hasNumber }">
                {{ newPasswordChecks.hasNumber ? '✓' : '○' }} {{ $t('userSettings.reqNumber') }}
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.confirmPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="passwordForm.confirmPassword"
                :type="showConfirmPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.confirmPasswordPlaceholder')"
              />
              <button type="button" class="password-toggle" @click="showConfirmPassword = !showConfirmPassword" tabindex="-1">
                <svg v-if="showConfirmPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>
          <p v-if="passwordError" class="error-text">{{ passwordError }}</p>
          <p v-if="passwordSuccess" class="success-text">{{ passwordSuccess }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closePasswordModal" class="btn-cancel">{{ $t('userSettings.cancel') }}</button>
          <button @click="changePassword" class="btn-confirm" :disabled="isChangingPassword">
            {{ isChangingPassword ? $t('userSettings.changing') : $t('userSettings.confirm') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 設定密碼 Modal (OAuth 用戶) -->
    <div v-if="showSetPasswordModal" class="modal-overlay" @click.self="closeSetPasswordModal">
      <div class="modal">
        <h3>{{ $t('userSettings.setPassword') }}</h3>
        <p class="modal-description">{{ $t('userSettings.setPasswordDescription') }}</p>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ $t('userSettings.newPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="setPasswordForm.newPassword"
                :type="showSetNewPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.newPasswordPlaceholder')"
                @input="validateSetPassword"
              />
              <button type="button" class="password-toggle" @click="showSetNewPassword = !showSetNewPassword" tabindex="-1">
                <svg v-if="showSetNewPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
            <div v-if="setPasswordForm.newPassword" class="password-requirements">
              <div class="requirement" :class="{ met: setPasswordChecks.length }">
                {{ setPasswordChecks.length ? '✓' : '○' }} {{ $t('userSettings.reqLength') }}
              </div>
              <div class="requirement" :class="{ met: setPasswordChecks.hasUpper }">
                {{ setPasswordChecks.hasUpper ? '✓' : '○' }} {{ $t('userSettings.reqUppercase') }}
              </div>
              <div class="requirement" :class="{ met: setPasswordChecks.hasLower }">
                {{ setPasswordChecks.hasLower ? '✓' : '○' }} {{ $t('userSettings.reqLowercase') }}
              </div>
              <div class="requirement" :class="{ met: setPasswordChecks.hasNumber }">
                {{ setPasswordChecks.hasNumber ? '✓' : '○' }} {{ $t('userSettings.reqNumber') }}
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.confirmPassword') }}</label>
            <div class="password-input-wrapper">
              <input
                v-model="setPasswordForm.confirmPassword"
                :type="showSetConfirmPassword ? 'text' : 'password'"
                class="form-input"
                :placeholder="$t('userSettings.confirmPasswordPlaceholder')"
              />
              <button type="button" class="password-toggle" @click="showSetConfirmPassword = !showSetConfirmPassword" tabindex="-1">
                <svg v-if="showSetConfirmPassword" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                  <circle cx="12" cy="12" r="3"></circle>
                </svg>
                <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                  <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
              </button>
            </div>
          </div>
          <p v-if="setPasswordError" class="error-text">{{ setPasswordError }}</p>
          <p v-if="setPasswordSuccess" class="success-text">{{ setPasswordSuccess }}</p>
        </div>
        <div class="modal-footer">
          <button @click="closeSetPasswordModal" class="btn-cancel">{{ $t('userSettings.cancel') }}</button>
          <button @click="setPassword" class="btn-confirm" :disabled="isSettingPassword">
            {{ isSettingPassword ? $t('userSettings.setting') : $t('userSettings.confirm') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import api from '../utils/api'
import { detectTimezone, detectTheme } from '../utils/defaults'
import GoogleSignInButton from '../components/GoogleSignInButton.vue'

const authStore = useAuthStore()
const { t: $t, locale } = useI18n()

// Google OAuth Client ID
const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

// 更改密碼相關狀態
const showPasswordModal = ref(false)
const isChangingPassword = ref(false)
const passwordError = ref('')
const passwordSuccess = ref('')
const showCurrentPassword = ref(false)
const showNewPassword = ref(false)
const showConfirmPassword = ref(false)
const passwordForm = ref({
  currentPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const newPasswordChecks = ref({
  length: false,
  hasUpper: false,
  hasLower: false,
  hasNumber: false
})

// Google 綁定相關狀態
const googleLoading = ref(false)
const googleError = ref('')
const googleSuccess = ref('')

// 設定密碼 Modal（給 OAuth 用戶使用）
const showSetPasswordModal = ref(false)
const setPasswordForm = ref({
  newPassword: '',
  confirmPassword: ''
})
const setPasswordError = ref('')
const setPasswordSuccess = ref('')
const isSettingPassword = ref(false)
const showSetNewPassword = ref(false)
const showSetConfirmPassword = ref(false)
const setPasswordChecks = ref({
  length: false,
  hasUpper: false,
  hasLower: false,
  hasNumber: false
})

function validateNewPassword() {
  const pwd = passwordForm.value.newPassword
  newPasswordChecks.value = {
    length: pwd.length >= 8,
    hasUpper: /[A-Z]/.test(pwd),
    hasLower: /[a-z]/.test(pwd),
    hasNumber: /[0-9]/.test(pwd)
  }
}

const isNewPasswordValid = computed(() => {
  return newPasswordChecks.value.length &&
         newPasswordChecks.value.hasUpper &&
         newPasswordChecks.value.hasLower &&
         newPasswordChecks.value.hasNumber
})

// 可用語言列表
const availableLanguages = [
  { code: 'zh-TW', name: '繁體中文' },
  { code: 'en', name: 'English' }
]

// 當前語言（優先 authStore → fallback localStorage/i18n → 預設值）
const currentLanguage = ref(authStore.preferences.language || locale.value)

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

// 當前時區（優先 authStore → fallback localStorage → 偵測系統時區）
const currentTimezone = ref(authStore.preferences.timezone || localStorage.getItem('timezone') || detectTimezone())

// 當前色調（優先 authStore → fallback localStorage → 偵測 OS 深色模式）
const currentTheme = ref(authStore.preferences.theme || localStorage.getItem('theme') || detectTheme())

// AI 摘要展開模式（優先 authStore → fallback localStorage → 預設值）
const summaryExpandMode = ref(
  authStore.preferences.summaryExpandMode || localStorage.getItem('summaryExpandMode') || 'follow-last'
)
const summaryExpandDropdownOpen = ref(false)

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

const currentSummaryExpandLabel = computed(() => {
  const labels = {
    'always-open': $t('userSettings.summaryAlwaysOpen'),
    'always-collapsed': $t('userSettings.summaryAlwaysCollapsed'),
    'follow-last': $t('userSettings.summaryFollowLast')
  }
  return labels[summaryExpandMode.value] || labels['follow-last']
})

// 切換下拉選單
function toggleLanguageDropdown() {
  languageDropdownOpen.value = !languageDropdownOpen.value
  timezoneDropdownOpen.value = false
  summaryExpandDropdownOpen.value = false
}

function toggleTimezoneDropdown() {
  timezoneDropdownOpen.value = !timezoneDropdownOpen.value
  languageDropdownOpen.value = false
  summaryExpandDropdownOpen.value = false
}

function toggleSummaryExpandDropdown() {
  summaryExpandDropdownOpen.value = !summaryExpandDropdownOpen.value
  languageDropdownOpen.value = false
  timezoneDropdownOpen.value = false
}

async function selectSummaryExpandMode(mode) {
  summaryExpandMode.value = mode
  localStorage.setItem('summaryExpandMode', mode)
  summaryExpandDropdownOpen.value = false
  await authStore.updatePreferences({ summaryExpandMode: mode })
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
    summaryExpandDropdownOpen.value = false
  }
}

// 當 authStore preferences 更新時，同步本地 ref 和 localStorage
watch(
  () => authStore.preferences,
  (prefs) => {
    if (prefs.summaryExpandMode && prefs.summaryExpandMode !== summaryExpandMode.value) {
      summaryExpandMode.value = prefs.summaryExpandMode
      localStorage.setItem('summaryExpandMode', prefs.summaryExpandMode)
    }
    if (prefs.language && prefs.language !== currentLanguage.value) {
      currentLanguage.value = prefs.language
      locale.value = prefs.language
      localStorage.setItem('locale', prefs.language)
    }
    if (prefs.timezone && prefs.timezone !== currentTimezone.value) {
      currentTimezone.value = prefs.timezone
      localStorage.setItem('timezone', prefs.timezone)
    }
    if (prefs.theme && prefs.theme !== currentTheme.value) {
      currentTheme.value = prefs.theme
      localStorage.setItem('theme', prefs.theme)
      document.documentElement.setAttribute('data-theme', prefs.theme)
    }
  },
  { deep: true }
)

onMounted(() => {
  document.addEventListener('click', handleClickOutside)

  // 如果 localStorage 已有值但後端沒有，首次同步寫入後端
  const prefs = authStore.preferences
  const localSync = {}
  const localMode = localStorage.getItem('summaryExpandMode')
  if (localMode && !prefs.summaryExpandMode) localSync.summaryExpandMode = localMode
  const localLang = localStorage.getItem('locale')
  if (localLang && !prefs.language) localSync.language = localLang
  const localTz = localStorage.getItem('timezone')
  if (localTz && !prefs.timezone) localSync.timezone = localTz
  const localTheme = localStorage.getItem('theme')
  if (localTheme && !prefs.theme) localSync.theme = localTheme

  if (Object.keys(localSync).length > 0) {
    authStore.updatePreferences(localSync)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

// 當前方案層級
const currentTier = computed(() => authStore.quota?.tier || 'free')

// 切換語言
function changeLanguage() {
  locale.value = currentLanguage.value
  localStorage.setItem('locale', currentLanguage.value)
  authStore.updatePreferences({ language: currentLanguage.value })
}

// 切換時區
function changeTimezone() {
  localStorage.setItem('timezone', currentTimezone.value)
  authStore.updatePreferences({ timezone: currentTimezone.value })
}

// 切換色調
function changeTheme() {
  localStorage.setItem('theme', currentTheme.value)
  document.documentElement.setAttribute('data-theme', currentTheme.value)
  authStore.updatePreferences({ theme: currentTheme.value })
}

// 取得時區簡短顯示
function getTimezoneShort(tzCode) {
  const tz = availableTimezones.find(t => t.code === tzCode)
  if (!tz) return tzCode
  // 從 "UTC+8 台北" 取出 "UTC+8"
  const match = tz.name.match(/UTC[+-]?\d+/)
  return match ? match[0] : tzCode
}

// 關閉密碼對話框
function closePasswordModal() {
  showPasswordModal.value = false
  passwordForm.value = { currentPassword: '', newPassword: '', confirmPassword: '' }
  passwordError.value = ''
  passwordSuccess.value = ''
  showCurrentPassword.value = false
  showNewPassword.value = false
  showConfirmPassword.value = false
  newPasswordChecks.value = { length: false, hasUpper: false, hasLower: false, hasNumber: false }
}

// 更改密碼
async function changePassword() {
  passwordError.value = ''
  passwordSuccess.value = ''

  // 驗證
  if (!passwordForm.value.currentPassword) {
    passwordError.value = $t('userSettings.errorCurrentPasswordRequired')
    return
  }

  if (!isNewPasswordValid.value) {
    passwordError.value = $t('userSettings.errorPasswordRequirements')
    return
  }

  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    passwordError.value = $t('userSettings.errorPasswordMismatch')
    return
  }

  isChangingPassword.value = true

  try {
    await api.post('/auth/change-password', {
      current_password: passwordForm.value.currentPassword,
      new_password: passwordForm.value.newPassword
    })
    passwordSuccess.value = $t('userSettings.passwordChanged')
    // 2 秒後自動關閉對話框
    setTimeout(() => {
      closePasswordModal()
    }, 2000)
  } catch (err) {
    passwordError.value = err.response?.data?.detail || $t('userSettings.errorChangeFailed')
  } finally {
    isChangingPassword.value = false
  }
}

// Google 綁定成功
async function handleGoogleBindSuccess(credential) {
  googleLoading.value = true
  googleError.value = ''
  googleSuccess.value = ''

  const result = await authStore.bindGoogle(credential)

  if (result.success) {
    googleSuccess.value = $t('userSettings.googleBindSuccess')
    setTimeout(() => {
      googleSuccess.value = ''
    }, 3000)
  } else {
    googleError.value = result.error
  }

  googleLoading.value = false
}

// Google 綁定失敗
function handleGoogleBindError(err) {
  googleError.value = $t('userSettings.googleBindFailed') + ': ' + err
}

// 確認解除 Google 綁定
function confirmUnbindGoogle() {
  // 如果用戶沒有密碼，警告他們
  if (!authStore.hasPassword) {
    if (!confirm($t('userSettings.unbindWarningNoPassword'))) {
      return
    }
  } else {
    if (!confirm($t('userSettings.unbindConfirm'))) {
      return
    }
  }
  unbindGoogle()
}

// 解除 Google 綁定
async function unbindGoogle() {
  googleLoading.value = true
  googleError.value = ''
  googleSuccess.value = ''

  const result = await authStore.unbindGoogle()

  if (result.success) {
    googleSuccess.value = $t('userSettings.googleUnbindSuccess')
    setTimeout(() => {
      googleSuccess.value = ''
    }, 3000)
  } else {
    googleError.value = result.error
  }

  googleLoading.value = false
}

// 驗證設定密碼表單
function validateSetPassword() {
  const pwd = setPasswordForm.value.newPassword
  setPasswordChecks.value = {
    length: pwd.length >= 8,
    hasUpper: /[A-Z]/.test(pwd),
    hasLower: /[a-z]/.test(pwd),
    hasNumber: /[0-9]/.test(pwd)
  }
}

const isSetPasswordValid = computed(() => {
  return setPasswordChecks.value.length &&
         setPasswordChecks.value.hasUpper &&
         setPasswordChecks.value.hasLower &&
         setPasswordChecks.value.hasNumber
})

// 關閉設定密碼對話框
function closeSetPasswordModal() {
  showSetPasswordModal.value = false
  setPasswordForm.value = { newPassword: '', confirmPassword: '' }
  setPasswordError.value = ''
  setPasswordSuccess.value = ''
  showSetNewPassword.value = false
  showSetConfirmPassword.value = false
  setPasswordChecks.value = { length: false, hasUpper: false, hasLower: false, hasNumber: false }
}

// 設定密碼
async function setPassword() {
  setPasswordError.value = ''
  setPasswordSuccess.value = ''

  if (!isSetPasswordValid.value) {
    setPasswordError.value = $t('userSettings.errorPasswordRequirements')
    return
  }

  if (setPasswordForm.value.newPassword !== setPasswordForm.value.confirmPassword) {
    setPasswordError.value = $t('userSettings.errorPasswordMismatch')
    return
  }

  isSettingPassword.value = true

  const result = await authStore.setPassword(setPasswordForm.value.newPassword)

  if (result.success) {
    setPasswordSuccess.value = $t('userSettings.passwordSetSuccess')
    setTimeout(() => {
      closeSetPasswordModal()
    }, 2000)
  } else {
    setPasswordError.value = result.error
  }

  isSettingPassword.value = false
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

.settings-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

/* 使用者資訊顯示面板 - 像素風格 */
.user-display-wrapper {
  display: flex;
  justify-content: flex-start;
  align-items: flex-start;
  gap: 12px;
  margin: 0 0 32px 22px;
}

/* 左側標籤 */
.display-labels {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px 0;
  text-align: right;
}

.display-labels .label-item {
  font-family: 'VT323', monospace;
  font-size: 12px;
  color: var(--main-text-light);
  letter-spacing: 1px;
  padding: 6px 0;
  line-height: 18px;
}


.display-labels .label-bar {
  height: 10px;
  margin-bottom: 12px;
}

/* 右側顯示面板 */
.user-display-panel {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: 'VT323', monospace;
  font-size: 18px;
  color: #ffffff;
  background: #101010;
  padding: 16px 20px;
  border-radius: 6px;
  min-width: 280px;
  box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.7);
  border: 1px solid #333;
  letter-spacing: 2.5px;
}

.user-display-panel .display-row {
  display: flex;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.user-display-panel .display-row:last-child {
  border-bottom: none;
}

.user-display-panel .display-value {
  color: #e4e4e4;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 分隔線 */
.user-display-panel .display-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, #ff8c00, transparent);
  margin: 8px 0;
  opacity: 0.5;
}

/* 使用量行 */
.user-display-panel .usage-row {
  border-bottom: none;
  padding-bottom: 2px;
}

.user-display-panel .usage-value {
  font-size: 14px;
  color: #ff8c00;
}

/* 進度條 */
.user-display-panel .display-bar {
  position: relative;
  height: 10px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 2px;
  margin-bottom: 12px;
  overflow: hidden;
}

.user-display-panel .display-bar:last-child {
  margin-bottom: 0;
}

.user-display-panel .bar-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background:
    repeating-linear-gradient(
      90deg,
      #ff8c00 0px,
      #ff8c00 4px,
      #1a1a1a 4px,
      #1a1a1a 6px
    );
  transition: width 0.3s ease;
  box-shadow: 0 0 6px rgba(255, 140, 0, 0.4);
}

.user-display-panel .bar-text {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 10px;
  color: #ff8c00;
  text-shadow: 0 0 4px rgba(0, 0, 0, 0.9);
  z-index: 1;
}

/* 主題色 icons */
.user-display-panel .theme-icons {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-display-panel .theme-icons svg {
  color: #444;
  transition: color 0.2s ease;
}

.user-display-panel .theme-icons svg.active {
  color: #fff;
}

/* 方案層級 */
.user-display-panel .plan-tiers {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
}

.user-display-panel .plan-tiers span {
  color: #444;
  transition: color 0.2s ease;
}

.user-display-panel .plan-tiers span.active {
  color: #fff;
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
.interface-card h2,
.security-card h2 {
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

/* 更改密碼按鈕 */
.change-password-btn {
  padding: 8px 16px;
  background: var(--main-primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.change-password-btn:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Modal 樣式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--color-overlay, rgba(0, 0, 0, 0.5));
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--upload-bg);
  border-radius: 16px;
  padding: 24px;
  min-width: 360px;
  max-width: 90%;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
}

.modal h3 {
  color: var(--main-primary);
  margin: 0 0 20px 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.modal-body {
  margin-bottom: 20px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 500;
  color: var(--main-text);
  font-size: 14px;
}

.form-input {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 8px;
  background: var(--color-bg);
  font-size: 14px;
  color: var(--main-text);
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: var(--main-primary);
  box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb), 0.15);
}

.form-input::placeholder {
  color: var(--main-text-light);
  opacity: 0.7;
}

.password-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.password-input-wrapper .form-input {
  padding-right: 40px;
}

.password-toggle {
  position: absolute;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--main-text-light);
  cursor: pointer;
  transition: all 0.2s ease;
}

.password-toggle:hover {
  color: var(--main-primary);
  background: rgba(var(--color-primary-rgb), 0.1);
}

.password-requirements {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--color-bg);
  border-radius: 8px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
}

.requirement {
  font-size: 0.8rem;
  color: var(--main-text-light);
  transition: color 0.2s ease;
}

.requirement.met {
  color: var(--color-success, #28a745);
  font-weight: 600;
}

.error-text {
  color: var(--color-danger, #dc3545);
  font-size: 14px;
  margin: 0;
}

.success-text {
  color: var(--color-success, #28a745);
  font-size: 14px;
  margin: 0;
}

.modal-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn-cancel,
.btn-confirm {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.btn-cancel {
  background: var(--color-bg);
  color: var(--main-text);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
}

.btn-cancel:hover {
  background: var(--color-bg-light, rgba(163, 177, 198, 0.15));
}

.btn-confirm {
  background: var(--color-primary, var(--main-primary));
  color: white;
}

.btn-confirm:hover {
  opacity: 0.9;
}

.btn-confirm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* Google 綁定樣式 */
.google-setting {
  flex-wrap: wrap;
  gap: 12px;
}

.setting-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.setting-right {
  display: flex;
  align-items: center;
}

.connected-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.8rem;
  color: var(--color-success, #28a745);
  font-weight: 500;
}

.connected-status svg {
  flex-shrink: 0;
}

.google-bind-wrapper {
  min-height: 40px;
  display: flex;
  align-items: center;
}

.unbind-btn {
  padding: 8px 16px;
  background: transparent;
  color: var(--color-danger, #dc3545);
  border: 1px solid var(--color-danger, #dc3545);
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.unbind-btn:hover:not(:disabled) {
  background: var(--color-danger, #dc3545);
  color: white;
}

.unbind-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.google-message {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 0.85rem;
  margin-top: 12px;
}

.google-message.error {
  background: rgba(220, 53, 69, 0.1);
  color: var(--color-danger, #dc3545);
  border: 1px solid rgba(220, 53, 69, 0.2);
}

.google-message.success {
  background: rgba(40, 167, 69, 0.1);
  color: var(--color-success, #28a745);
  border: 1px solid rgba(40, 167, 69, 0.2);
}

.modal-description {
  color: var(--main-text-light);
  font-size: 0.9rem;
  margin: -10px 0 20px 0;
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

  .user-display-wrapper {
    max-width: 100%;
    margin-bottom: 24px;
  }

  .user-display-panel {
    min-width: auto;
    flex: 1;
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

/* 小手機 */
@media (max-width: 480px) {
  .settings-container {
    padding: 0 12px;
  }

  .settings-header {
    margin-top: 20px;
    margin-bottom: 20px;
  }

  .settings-header h1 {
    font-size: 1.5rem;
  }

  .settings-header p {
    font-size: 0.9rem;
  }

  .user-display-wrapper {
    gap: 8px;
    margin-bottom: 20px;
  }

  .display-labels .label-item {
    font-size: 10px;
  }

  .user-display-panel {
    font-size: 16px;
    padding: 12px 14px;
  }

  .user-display-panel .display-value {
    max-width: 160px;
    font-size: 15px;
  }

  .settings-grid {
    gap: 16px;
  }

  /* 卡片內間距調整 */
  .user-info-card,
  .interface-card {
    padding: 16px;
  }

  .user-info-card h2,
  .interface-card h2 {
    font-size: 1.1rem;
    margin-bottom: 16px;
  }

  .info-item,
  .setting-item {
    padding: 10px 0;
    flex-wrap: wrap;
    gap: 8px;
  }

  .info-label,
  .setting-label,
  .info-value {
    font-size: 0.9rem;
  }

  /* 下拉選單在小屏優化 */
  .custom-select {
    min-width: 120px;
  }

  .select-trigger {
    padding: 10px 12px;
    font-size: 14px;
    min-height: 44px;
  }

  .select-dropdown {
    max-height: 200px;
    overflow-y: auto;
  }

  .select-option {
    padding: 12px 14px;
    min-height: 44px;
  }

  /* 配額卡片調整 */
  .quota-content {
    padding: 16px;
  }

  .quota-header h3 {
    font-size: 1.1rem;
  }

  .quota-tier {
    padding: 4px 12px;
    font-size: 0.8rem;
  }

  .quota-items {
    gap: 16px;
  }

  .quota-label {
    font-size: 0.85rem;
    flex-wrap: wrap;
  }

  .quota-value {
    font-size: 0.85rem;
  }

  .quota-remaining {
    font-size: 0.8rem;
  }

  /* toggle 開關觸控優化 */
  .toggle-switch {
    width: 44px;
    height: 24px;
  }
}
</style>
