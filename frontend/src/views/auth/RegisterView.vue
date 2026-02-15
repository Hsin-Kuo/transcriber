<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-content">
          <h1 class="auth-title">註冊帳號</h1>
          <p class="auth-subtitle">Whisper 轉錄服務</p>

          <form @submit.prevent="handleRegister" class="auth-form">
            <div class="form-group">
              <label for="email">Email</label>
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
              <div class="password-input-wrapper">
                <input
                  :type="showPassword ? 'text' : 'password'"
                  id="password"
                  v-model="password"
                  required
                  placeholder="至少 8 個字元"
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
                  {{ passwordChecks.length ? '✓' : '○' }} 至少 8 個字元
                </div>
                <div class="requirement" :class="{ met: passwordChecks.hasUpper }">
                  {{ passwordChecks.hasUpper ? '✓' : '○' }} 包含大寫字母
                </div>
                <div class="requirement" :class="{ met: passwordChecks.hasLower }">
                  {{ passwordChecks.hasLower ? '✓' : '○' }} 包含小寫字母
                </div>
                <div class="requirement" :class="{ met: passwordChecks.hasNumber }">
                  {{ passwordChecks.hasNumber ? '✓' : '○' }} 包含數字
                </div>
              </div>
            </div>

            <div class="form-group">
              <label for="confirmPassword">確認密碼</label>
              <div class="password-input-wrapper">
                <input
                  :type="showConfirmPassword ? 'text' : 'password'"
                  id="confirmPassword"
                  v-model="confirmPassword"
                  required
                  placeholder="再次輸入密碼"
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
                密碼不一致
              </div>
            </div>

            <div v-if="error" class="error-message">
              {{ error }}
            </div>

            <div v-if="success" class="success-message">
              <div class="success-icon">✉️</div>
              <p class="success-title">{{ successMessage }}</p>
              <p class="success-subtitle">
                請查看您的郵箱 <strong>{{ email }}</strong>，點擊驗證連結完成註冊。
              </p>
              <p class="success-note">
                沒收到郵件？請檢查垃圾郵件資料夾，或
                <a href="#" @click.prevent="resendEmail" class="resend-link">重新發送驗證郵件</a>
              </p>
            </div>

            <button
              v-if="!success"
              type="submit"
              class="btn-primary"
              :disabled="loading || !isPasswordValid || password !== confirmPassword"
            >
              {{ loading ? '註冊中...' : '註冊' }}
            </button>

            <button
              v-else
              type="button"
              class="btn-secondary"
              @click="router.push('/login')"
            >
              前往登入頁面
            </button>
          </form>

          <!-- Google 註冊 -->
          <div v-if="!success && googleClientId" class="oauth-section">
            <div class="divider">
              <span>或</span>
            </div>
            <GoogleSignInButton
              :client-id="googleClientId"
              button-text="signup_with"
              :width="350"
              @success="handleGoogleSuccess"
              @error="handleGoogleError"
            />
          </div>

          <div v-if="!success" class="auth-footer">
            <p>已有帳號？<router-link to="/login">立即登入</router-link></p>
          </div>

          <div class="quota-info">
            <p class="quota-title">🎁 註冊即享免費配額</p>
            <div class="quota-details">
              <div class="quota-item">
                <span class="quota-label">轉錄次數</span>
                <span class="quota-value">10 次/月</span>
              </div>
              <div class="quota-item">
                <span class="quota-label">轉錄時長</span>
                <span class="quota-value">60 分鐘/月</span>
              </div>
            </div>
          </div>
        </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import GoogleSignInButton from '../../components/GoogleSignInButton.vue'

const router = useRouter()
const authStore = useAuthStore()

// Google OAuth Client ID（從環境變數取得）
const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const showConfirmPassword = ref(false)
const loading = ref(false)
const error = ref('')

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

const success = ref(false)
const successMessage = ref('')

async function resendEmail() {
  loading.value = true
  error.value = ''

  try {
    const response = await fetch(`${import.meta.env.VITE_API_URL ?? ''}/auth/resend-verification`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email: email.value })
    })

    const data = await response.json()

    if (response.ok) {
      successMessage.value = data.message || '驗證郵件已重新發送'
    } else {
      error.value = data.detail || '重新發送失敗'
    }
  } catch (err) {
    error.value = '網路錯誤，請稍後再試'
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  if (password.value !== confirmPassword.value) {
    error.value = '密碼不一致'
    return
  }

  if (!isPasswordValid.value) {
    error.value = '密碼不符合要求'
    return
  }

  loading.value = true
  error.value = ''
  success.value = false

  const result = await authStore.register(email.value, password.value)

  if (result.success) {
    // 註冊成功，顯示驗證郵件提示
    success.value = true
    successMessage.value = result.message || '註冊成功！請查看您的郵箱完成驗證'
  } else {
    error.value = result.error
  }

  loading.value = false
}

async function handleGoogleSuccess(credential) {
  loading.value = true
  error.value = ''

  const result = await authStore.googleLogin(credential)

  if (result.success) {
    router.push('/')
  } else {
    error.value = result.error
  }

  loading.value = false
}

function handleGoogleError(err) {
  error.value = 'Google 註冊失敗：' + err
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
  max-width: 500px;
  margin: 0 auto;
  background: var(--upload-bg);
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border: 1px solid rgba(160, 145, 124, 0.2);
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
  border: 2px solid rgba(160, 145, 124, 0.3);
  border-radius: 8px;
  background: white;
  color: var(--main-text);
  font-size: 1rem;
  transition: all 0.2s ease;
}

.form-group input:focus {
  outline: none;
  border-color: var(--main-primary);
  box-shadow: 0 0 0 3px rgba(68, 70, 91, 0.1);
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
  background: rgba(68, 70, 91, 0.1);
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
  border: 1px solid rgba(160, 145, 124, 0.2);
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

.success-message {
  padding: 24px;
  background: #d4edda;
  border-radius: 12px;
  text-align: center;
  border: 1px solid #c3e6cb;
}

.success-icon {
  font-size: 3rem;
  margin-bottom: 12px;
}

.success-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #155724;
  margin: 0 0 12px 0;
}

.success-subtitle {
  font-size: 0.95rem;
  color: #155724;
  margin: 0 0 16px 0;
  line-height: 1.5;
}

.success-subtitle strong {
  font-weight: 700;
  color: #0d3f1a;
}

.success-note {
  font-size: 0.85rem;
  color: #155724;
  margin: 0;
  line-height: 1.6;
}

.resend-link {
  color: var(--main-primary);
  text-decoration: underline;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.2s ease;
}

.resend-link:hover {
  color: var(--main-primary-dark);
}

.btn-primary {
  padding: 14px 24px;
  background: var(--main-primary-dark);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 10px;
}

.btn-primary:hover:not(:disabled) {
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 14px 24px;
  background: white;
  color: var(--main-primary);
  border: 2px solid var(--main-primary);
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 10px;
}

.btn-secondary:hover {
  background: var(--main-primary);
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

.btn-secondary:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
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

.quota-info {
  margin-top: 30px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 12px;
  border: 1px solid rgba(160, 145, 124, 0.2);
}

.quota-title {
  font-size: 0.95rem;
  color: var(--main-primary);
  margin: 0 0 15px 0;
  text-align: center;
  font-weight: 600;
}

.quota-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px;
}

.quota-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.quota-label {
  font-size: 0.85rem;
  color: var(--main-text-light);
  font-weight: 500;
}

.quota-value {
  font-size: 1.1rem;
  color: var(--main-text);
  font-weight: 700;
}

.oauth-section {
  margin-top: 24px;
}

.divider {
  display: flex;
  align-items: center;
  margin: 20px 0;
  color: var(--main-text-light);
  font-size: 0.85rem;
}

.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(160, 145, 124, 0.3);
}

.divider span {
  padding: 0 16px;
}
</style>
