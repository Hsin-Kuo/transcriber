<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-content">
          <h1 class="auth-title">{{ $t('auth.resetPasswordTitle') }}</h1>
          <p class="auth-subtitle">{{ $t('auth.forgotPasswordSubtitle') }}</p>

          <!-- 檢查連結有效性中（避免過期連結先閃出表單）-->
          <div v-if="checking" class="checking-state">
            <p class="form-description">{{ $t('auth.checkingLink') }}</p>
          </div>

          <!-- 無效 token 狀態 -->
          <div v-else-if="invalidToken" class="error-state">
            <div class="error-icon">⚠️</div>
            <p class="error-title">{{ $t('auth.invalidToken') }}</p>
            <p class="error-subtitle">
              {{ $t('auth.invalidTokenDescription') }}
            </p>
            <button
              type="button"
              class="btn-primary"
              @click="router.push('/forgot-password')"
            >
              {{ $t('auth.requestNewReset') }}
            </button>
          </div>

          <!-- 重設表單 -->
          <form v-else-if="!success" @submit.prevent="handleSubmit" class="auth-form">
            <p class="form-description">
              {{ $t('auth.resetPasswordEnterNew') }}
            </p>

            <div class="form-group">
              <label for="password">{{ $t('auth.newPassword') }}</label>
              <div class="password-input-wrapper">
                <input
                  :type="showPassword ? 'text' : 'password'"
                  id="password"
                  v-model="password"
                  required
                  :placeholder="$t('auth.passwordPlaceholder')"
                  minlength="8"
                  :disabled="loading"
                  @input="validatePassword"
                />
                <button
                  type="button"
                  class="password-toggle"
                  @click="showPassword = !showPassword"
                  :disabled="loading"
                  tabindex="-1"
                >
                  <svg v-if="showPassword" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>
                  <svg v-else xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                    <line x1="1" y1="1" x2="23" y2="23"></line>
                  </svg>
                </button>
              </div>
              <div v-if="password" class="password-requirements">
                <div class="requirement" :class="{ met: passwordChecks.length }">
                  {{ passwordChecks.length ? '✓' : '○' }} {{ $t('auth.reqLength') }}
                </div>
                <div class="requirement" :class="{ met: passwordChecks.hasUpper }">
                  {{ passwordChecks.hasUpper ? '✓' : '○' }} {{ $t('auth.reqUppercase') }}
                </div>
                <div class="requirement" :class="{ met: passwordChecks.hasLower }">
                  {{ passwordChecks.hasLower ? '✓' : '○' }} {{ $t('auth.reqLowercase') }}
                </div>
                <div class="requirement" :class="{ met: passwordChecks.hasNumber }">
                  {{ passwordChecks.hasNumber ? '✓' : '○' }} {{ $t('auth.reqNumber') }}
                </div>
              </div>
            </div>

            <div class="form-group">
              <label for="confirmPassword">{{ $t('auth.confirmNewPassword') }}</label>
              <div class="password-input-wrapper">
                <input
                  :type="showConfirmPassword ? 'text' : 'password'"
                  id="confirmPassword"
                  v-model="confirmPassword"
                  required
                  :placeholder="$t('auth.confirmPasswordPlaceholder')"
                  minlength="8"
                  :disabled="loading"
                />
                <button
                  type="button"
                  class="password-toggle"
                  @click="showConfirmPassword = !showConfirmPassword"
                  :disabled="loading"
                  tabindex="-1"
                >
                  <svg v-if="showConfirmPassword" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>
                  <svg v-else xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                    <line x1="1" y1="1" x2="23" y2="23"></line>
                  </svg>
                </button>
              </div>
              <div v-if="confirmPassword && confirmPassword !== password" class="error-hint">
                {{ $t('auth.passwordMismatch') }}
              </div>
            </div>

            <div v-if="error" class="error-message">
              {{ error }}
            </div>

            <button
              type="submit"
              class="btn-primary"
              :disabled="loading || !isPasswordValid || password !== confirmPassword"
            >
              {{ loading ? $t('auth.resetting') : $t('auth.resetPassword') }}
            </button>
          </form>

          <!-- 成功狀態 -->
          <div v-else class="success-message">
            <div class="success-icon">✓</div>
            <p class="success-title">{{ $t('auth.passwordResetSuccess') }}</p>
            <p class="success-subtitle">
              {{ $t('auth.passwordResetSuccessDescription') }}
            </p>
            <button
              type="button"
              class="btn-primary"
              @click="router.push('/login')"
            >
              {{ $t('auth.goToLogin') }}
            </button>
          </div>
        </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../../stores/auth'
import api from '../../utils/api'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t: $t } = useI18n()

const token = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const showConfirmPassword = ref(false)
const loading = ref(false)
const error = ref('')
const success = ref(false)
const invalidToken = ref(false)
const checking = ref(true)

const passwordChecks = ref({
  length: false,
  hasUpper: false,
  hasLower: false,
  hasNumber: false
})

const isPasswordValid = computed(() => {
  return passwordChecks.value.length &&
         passwordChecks.value.hasUpper &&
         passwordChecks.value.hasLower &&
         passwordChecks.value.hasNumber
})

function validatePassword() {
  const pwd = password.value
  passwordChecks.value = {
    length: pwd.length >= 8,
    hasUpper: /[A-Z]/.test(pwd),
    hasLower: /[a-z]/.test(pwd),
    hasNumber: /[0-9]/.test(pwd)
  }
}

onMounted(async () => {
  // 從 URL 獲取 token
  token.value = route.query.token || ''
  if (!token.value) {
    invalidToken.value = true
    checking.value = false
    return
  }
  // 點開連結當下就驗證有效性 / 是否過期，過期/無效直接顯示重新申請
  try {
    await api.get('/auth/reset-password', { params: { token: token.value } })
  } catch {
    invalidToken.value = true
  } finally {
    checking.value = false
  }
})

async function handleSubmit() {
  if (password.value !== confirmPassword.value) {
    error.value = $t('auth.passwordMismatch')
    return
  }

  if (!isPasswordValid.value) {
    error.value = $t('auth.passwordRequirements')
    return
  }

  loading.value = true
  error.value = ''

  const result = await authStore.resetPassword(token.value, password.value)

  if (result.success) {
    success.value = true
  } else {
    // 檢查是否為 token 無效錯誤
    if (result.error && (result.error.includes('無效') || result.error.includes('過期'))) {
      invalidToken.value = true
    } else {
      error.value = result.error
    }
  }

  loading.value = false
}
</script>

<style scoped>
.auth-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--main-bg);
  position: relative;
}

.auth-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-image:
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(255, 255, 255, 0.015) 2px,
      rgba(255, 255, 255, 0.015) 3px
    ),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 8px,
      rgba(255, 255, 255, 0.03) 8px,
      rgba(255, 255, 255, 0.03) 10px
    ),
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 21px,
      rgba(255, 255, 255, 0.04) 21px,
      rgba(255, 255, 255, 0.04) 23px
    ),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 4px,
      rgba(0, 0, 0, 0.015) 4px,
      rgba(0, 0, 0, 0.015) 5px
    ),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 11px,
      rgba(0, 0, 0, 0.03) 11px,
      rgba(0, 0, 0, 0.03) 13px
    ),
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 27px,
      rgba(0, 0, 0, 0.04) 27px,
      rgba(0, 0, 0, 0.04) 29px
    );
  pointer-events: none;
  opacity: 0.2;
  z-index: 0;
}

.auth-card {
  width: 100%;
  max-width: 450px;
  margin: 0 auto;
  background: var(--upload-bg);
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(var(--color-text-dark-rgb), 0.08);
  border: 1px solid rgba(var(--color-divider-rgb), 0.2);
  position: relative;
  z-index: 1;
}

.auth-content {
  padding: 40px 30px;
}

.auth-title {
  font-size: 2rem;
  margin: 0 0 10px 0;
  text-align: center;
  color: var(--main-primary);
  font-weight: 700;
}

.auth-subtitle {
  text-align: center;
  color: var(--main-text-light);
  margin: 0 0 30px 0;
  font-size: 0.9rem;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-description {
  font-size: 0.95rem;
  color: var(--main-text-light);
  margin: 0;
  line-height: 1.6;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-size: 0.9rem;
  color: var(--main-text);
  font-weight: 600;
}

.form-group input {
  padding: 12px 16px;
  border: 2px solid rgba(var(--color-divider-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-white);
  color: var(--main-text);
  font-size: 1rem;
  transition: all 0.2s ease;
}

.form-group input:focus {
  outline: none;
  border-color: var(--main-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.1);
}

.form-group input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: var(--main-bg);
}

.password-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.password-input-wrapper input {
  width: 100%;
  padding-right: 44px;
}

.password-toggle {
  position: absolute;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--main-text-light);
  cursor: pointer;
  transition: all 0.2s ease;
}

.password-toggle:hover:not(:disabled) {
  color: var(--main-primary);
  background: rgba(var(--color-primary-rgb), 0.1);
}

.password-toggle:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.password-requirements {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding: 12px 16px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 8px;
  border: 1px solid rgba(var(--color-divider-rgb), 0.2);
}

.requirement {
  font-size: 0.85rem;
  color: var(--main-text-light);
  transition: color 0.2s ease;
  font-weight: 500;
}

.requirement.met {
  color: var(--main-primary);
  font-weight: 600;
}

.error-hint {
  font-size: 0.85rem;
  color: var(--color-danger-dark);
  margin-top: 4px;
  font-weight: 500;
}

.error-message {
  color: var(--color-danger-dark);
  font-size: 0.85rem;
  text-align: left;
  font-weight: 500;
  margin-bottom: 4px;
}

.error-state {
  text-align: center;
  padding: 20px 0;
}

.error-icon {
  font-size: 3rem;
  margin-bottom: 16px;
}

.error-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--color-danger-dark);
  margin: 0 0 12px 0;
}

.error-subtitle {
  font-size: 0.95rem;
  color: var(--main-text-light);
  margin: 0 0 24px 0;
  line-height: 1.6;
}

.success-message {
  padding: 24px;
  background: var(--color-success-bg);
  border-radius: 12px;
  text-align: center;
  border: 1px solid color-mix(in srgb, var(--color-success) 30%, transparent);
}

.success-icon {
  font-size: 3rem;
  margin-bottom: 12px;
  color: var(--color-success-dark);
}

.success-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--color-success-dark);
  margin: 0 0 12px 0;
}

.success-subtitle {
  font-size: 0.95rem;
  color: var(--color-success-dark);
  margin: 0 0 20px 0;
  line-height: 1.5;
}

.btn-primary {
  padding: 14px 24px;
  background: var(--main-primary-dark);
  color: var(--color-white);
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 10px;
  width: 100%;
}

.btn-primary:hover:not(:disabled) {
  color: var(--color-white);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(var(--color-text-dark-rgb), 0.15);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(var(--color-text-dark-rgb), 0.1);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
