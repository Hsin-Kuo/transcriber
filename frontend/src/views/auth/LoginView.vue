<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-content">
          <h1 class="auth-title">🎙️ 登入</h1>
          <p class="auth-subtitle">Whisper 轉錄服務</p>

          <form @submit.prevent="handleLogin" class="auth-form">
            <div class="form-group">
              <label for="email">帳號</label>
              <input
                type="email"
                id="email"
                v-model="email"
                required
                placeholder="your@email.com"
                :disabled="loading"
              />
            </div>

            <div class="form-group">
              <label for="password">密碼</label>
              <input
                type="password"
                id="password"
                v-model="password"
                required
                placeholder="至少 8 個字元"
                minlength="8"
                :disabled="loading"
              />
            </div>

            <div v-if="error" class="error-message">
              {{ error }}
              <div v-if="needsVerification" class="verification-prompt">
                <p class="verification-text">
                  沒收到驗證郵件嗎？
                </p>
                <button
                  type="button"
                  class="btn-resend"
                  @click="resendVerification"
                  :disabled="resendLoading"
                >
                  {{ resendLoading ? '發送中...' : '重新發送驗證郵件' }}
                </button>
                <p v-if="resendSuccess" class="resend-success">
                  ✓ 驗證郵件已發送，請查看您的郵箱
                </p>
              </div>
            </div>

            <button
              type="submit"
              class="btn-primary"
              :disabled="loading"
            >
              {{ loading ? '登入中...' : '登入' }}
            </button>
          </form>

          <div class="auth-footer">
            <p>還沒有帳號？<router-link to="/register">立即註冊</router-link></p>
          </div>
        </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const needsVerification = ref(false)
const resendLoading = ref(false)
const resendSuccess = ref(false)

async function handleLogin() {
  loading.value = true
  error.value = ''
  needsVerification.value = false
  resendSuccess.value = false

  const result = await authStore.login(email.value, password.value)

  if (result.success) {
    // 登入成功，跳轉到原頁面或首頁
    const redirect = router.currentRoute.value.query.redirect || '/'
    router.push(redirect)
  } else {
    error.value = result.error
    // 檢查是否為 email 未驗證的錯誤
    if (result.error && result.error.includes('驗證')) {
      needsVerification.value = true
    }
  }

  loading.value = false
}

async function resendVerification() {
  resendLoading.value = true
  resendSuccess.value = false

  try {
    const response = await fetch(
      `${import.meta.env.VITE_API_URL || 'http://100.66.247.23:8000'}/auth/resend-verification`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email: email.value })
      }
    )

    const data = await response.json()

    if (response.ok) {
      resendSuccess.value = true
      // 3 秒後隱藏成功訊息
      setTimeout(() => {
        resendSuccess.value = false
      }, 5000)
    } else {
      error.value = data.detail || '發送驗證郵件失敗'
    }
  } catch (err) {
    error.value = '網路錯誤，請稍後再試'
  } finally {
    resendLoading.value = false
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
    /* 垂直 - 密集細線 */
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(255, 255, 255, 0.015) 2px,
      rgba(255, 255, 255, 0.015) 3px
    ),
    /* 垂直 - 中等間距 */
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 8px,
      rgba(255, 255, 255, 0.03) 8px,
      rgba(255, 255, 255, 0.03) 10px
    ),
    /* 垂直 - 稀疏粗線 */
    repeating-linear-gradient(
      0deg,
      transparent,
      transparent 21px,
      rgba(255, 255, 255, 0.04) 21px,
      rgba(255, 255, 255, 0.04) 23px
    ),
    /* 水平 - 密集細線 */
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 4px,
      rgba(0, 0, 0, 0.015) 4px,
      rgba(0, 0, 0, 0.015) 5px
    ),
    /* 水平 - 中等間距 */
    repeating-linear-gradient(
      90deg,
      transparent,
      transparent 11px,
      rgba(0, 0, 0, 0.03) 11px,
      rgba(0, 0, 0, 0.03) 13px
    ),
    /* 水平 - 稀疏粗線 */
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

.error-message {
  color: var(--color-danger-dark);
  font-size: 0.85rem;
  text-align: left;
  font-weight: 500;
  margin-bottom: 4px;
}

.verification-prompt {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(var(--color-danger-rgb), 0.2);
}

.verification-text {
  margin: 0 0 12px 0;
  font-size: 0.85rem;
  color: var(--color-danger-dark);
  font-weight: 500;
}

.btn-resend {
  padding: 10px 20px;
  background: var(--color-white);
  color: var(--main-primary);
  border: 2px solid var(--main-primary);
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  width: 100%;
}

.btn-resend:hover:not(:disabled) {
  background: var(--main-primary);
  color: var(--color-white);
}

.btn-resend:active:not(:disabled) {
  transform: scale(0.98);
}

.btn-resend:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.resend-success {
  margin: 12px 0 0 0;
  padding: 10px;
  background: var(--color-success-bg);
  border-radius: 6px;
  color: var(--color-success-dark);
  font-size: 0.85rem;
  font-weight: 600;
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

.auth-footer {
  margin-top: 30px;
  text-align: center;
  color: var(--main-text-light);
  font-size: 0.9rem;
}

.auth-footer a {
  color: var(--main-primary);
  text-decoration: none;
  font-weight: 600;
  transition: color 0.2s ease;
}

.auth-footer a:hover {
  color: var(--main-primary-dark);
  text-decoration: underline;
}
</style>
