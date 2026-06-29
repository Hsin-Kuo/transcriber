<template>
  <div class="auth-container">
    <ElectricBorder />

    <div class="auth-card electric-card">
      <div class="electric-inner">
        <div class="auth-content">
          <!-- 1. 預檢 token 中 -->
          <div v-if="state === 'checking'" class="verifying-state">
            <div class="spinner-large"></div>
            <h2>{{ $t('auth.verifyCheckingTitle') }}</h2>
            <p>{{ $t('auth.verifyPleaseWait') }}</p>
          </div>

          <!-- 2. token 有效，等待使用者確認 -->
          <div v-else-if="state === 'ready'" class="ready-state">
            <h2>{{ $t('auth.verifyConfirmTitle') }}</h2>
            <p class="confirm-message">
              {{ $t('auth.verifyConfirmMessage', { email }) }}
            </p>
            <p class="confirm-hint">{{ $t('auth.verifyConfirmHint') }}</p>
            <button
              class="btn-primary"
              :disabled="submitting"
              @click="confirmVerification"
            >
              {{ submitting ? $t('auth.verifying') : $t('auth.completeVerification') }}
            </button>
          </div>

          <!-- 3. 驗證成功（短暫顯示後跳轉） -->
          <div v-else-if="state === 'success'" class="success-state">
            <h2>{{ $t('auth.verifySuccessTitle') }}</h2>
            <p class="success-message">{{ $t('auth.verifySuccessMessage') }}</p>
          </div>

          <!-- 4. 連結過期：提供重發按鈕 -->
          <div v-else-if="state === 'expired'" class="error-state">
            <h2>{{ $t('auth.verifyExpiredTitle') }}</h2>
            <p class="error-message">{{ errorMessage }}</p>
            <div class="resend-form">
              <input
                v-model="resendEmail"
                type="email"
                :placeholder="$t('auth.enterYourEmail')"
                class="resend-input"
                :disabled="resending"
              />
              <button
                class="btn-primary"
                :disabled="resending || !resendEmail"
                @click="handleResend"
              >
                {{ resending ? $t('auth.resending') : $t('auth.resendVerificationEmail') }}
              </button>
            </div>
            <p v-if="resendNotice" class="resend-notice">{{ resendNotice }}</p>
          </div>

          <!-- 5. 其他錯誤 -->
          <div v-else class="error-state">
            <h2>{{ $t('auth.verifyFailedTitle') }}</h2>
            <p class="error-message">{{ errorMessage }}</p>
            <div class="error-actions">
              <button class="btn-primary" @click="router.push('/login')">
                {{ $t('auth.goToLogin') }}
              </button>
              <button class="btn-secondary" @click="router.push('/register')">
                {{ $t('auth.reRegister') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import ElectricBorder from '../../components/shared/ElectricBorder.vue'

const router = useRouter()
const route = useRoute()
const { t: $t } = useI18n()

// 'checking' | 'ready' | 'success' | 'expired' | 'error'
const state = ref('checking')
const email = ref('')
const errorMessage = ref('')
const submitting = ref(false)

// 重發驗證信 UI 狀態
const resendEmail = ref('')
const resending = ref(false)
const resendNotice = ref('')

const token = route.query.token

onMounted(async () => {
  if (!token) {
    state.value = 'error'
    errorMessage.value = $t('auth.missingToken')
    return
  }

  // 預檢：只查 token 是否有效，不消耗
  try {
    const { data } = await api.get('/auth/verify-email', {
      params: { token }
    })
    email.value = data.email
    state.value = 'ready'
  } catch (err) {
    const status = err.response?.status
    const detail = err.response?.data?.detail
    if (status === 410) {
      state.value = 'expired'
      errorMessage.value = detail || $t('auth.verifyLinkExpired')
      resendEmail.value = '' // 不預填，讓使用者自己輸入避免錯誤連結帶錯 email
    } else {
      state.value = 'error'
      errorMessage.value = detail || $t('auth.verifyLinkInvalid')
    }
  }
})

async function confirmVerification() {
  if (submitting.value) return
  submitting.value = true
  try {
    await api.post('/auth/verify-email', { token })
    state.value = 'success'
    // 不自動登入：導去登入頁並預填 email，由使用者自行登入
    setTimeout(() => router.push({ path: '/login', query: { email: email.value } }), 1500)
  } catch (err) {
    const status = err.response?.status
    const detail = err.response?.data?.detail
    if (status === 410) {
      state.value = 'expired'
      errorMessage.value = detail || $t('auth.verifyLinkExpired')
    } else {
      state.value = 'error'
      errorMessage.value = detail || $t('auth.verifyFailedRetry')
    }
  } finally {
    submitting.value = false
  }
}

async function handleResend() {
  if (resending.value || !resendEmail.value) return
  resending.value = true
  resendNotice.value = ''
  try {
    await api.post('/auth/resend-verification', { email: resendEmail.value })
    resendNotice.value = $t('auth.resendSuccess')
  } catch (err) {
    const detail = err.response?.data?.detail
    resendNotice.value = detail || $t('auth.resendFailed')
  } finally {
    resending.value = false
  }
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
}

.auth-card {
  width: 100%;
  max-width: 500px;
  margin: 0 auto;
}

.auth-content {
  padding: 60px 40px;
  text-align: center;
}

.verifying-state,
.ready-state,
.success-state,
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
}

.spinner-large {
  width: 60px;
  height: 60px;
  border: 5px solid rgba(var(--color-primary-rgb), 0.1);
  border-top: 5px solid var(--main-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

h2 {
  font-size: 1.8rem;
  color: var(--main-text);
  margin: 0;
  font-weight: 700;
}

.confirm-message,
.confirm-hint,
.success-message,
.error-message {
  font-size: 1.05rem;
  color: var(--main-text-light);
  margin: 0;
  line-height: 1.6;
}

.confirm-hint {
  font-size: 0.95rem;
  opacity: 0.85;
}

.error-message {
  color: var(--color-danger-dark);
  font-weight: 500;
}

.error-actions {
  display: flex;
  gap: 12px;
  margin-top: 10px;
}

.resend-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
  max-width: 360px;
  margin-top: 12px;
}

.resend-input {
  padding: 12px 16px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 10px;
  font-size: 1rem;
  outline: none;
  background: var(--main-bg);
  color: var(--main-text);
}

.resend-input:focus {
  border-color: var(--main-primary);
}

.resend-notice {
  font-size: 0.95rem;
  color: var(--main-text-light);
  margin: 0;
}

.btn-primary,
.btn-secondary {
  padding: 14px 28px;
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-primary {
  background: var(--gradient-cool);
  color: var(--main-primary);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--gradient-cool);
  color: var(--main-text);
}

.btn-secondary:hover {
  transform: translateY(-2px);
  color: var(--main-primary);
}

.btn-secondary:active {
  transform: translateY(0);
}
</style>
