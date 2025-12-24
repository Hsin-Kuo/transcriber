<template>
  <div class="auth-container">
    <ElectricBorder />

    <div class="auth-card electric-card">
      <div class="electric-inner">
        <div class="auth-content">
          <h1 class="auth-title">🎙️ 註冊帳號</h1>
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
              <input
                type="password"
                id="password"
                v-model="password"
                required
                placeholder="至少 8 個字元"
                minlength="8"
                :disabled="loading"
                @input="validatePassword"
              />
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
              <input
                type="password"
                id="confirmPassword"
                v-model="confirmPassword"
                required
                placeholder="再次輸入密碼"
                minlength="8"
                :disabled="loading"
              />
              <div v-if="confirmPassword && confirmPassword !== password" class="error-hint">
                密碼不一致
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
              {{ loading ? '註冊中...' : '註冊' }}
            </button>
          </form>

          <div class="auth-footer">
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
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import ElectricBorder from '../../components/shared/ElectricBorder.vue'

const router = useRouter()
const authStore = useAuthStore()

const email = ref('')
const password = ref('')
const confirmPassword = ref('')
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

  const result = await authStore.register(email.value, password.value)

  if (result.success) {
    // 註冊成功，跳轉到首頁
    router.push('/')
  } else {
    error.value = result.error
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
  background: var(--neu-bg);
}

.auth-card {
  width: 100%;
  max-width: 500px;
  margin: 0 auto;
}

.auth-content {
  padding: 40px 30px;
}

.auth-title {
  font-size: 2rem;
  margin: 0 0 10px 0;
  text-align: center;
  color: var(--neu-primary);
  font-weight: 700;
}

.auth-subtitle {
  text-align: center;
  color: var(--neu-text-light);
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
  color: var(--neu-text);
  font-weight: 600;
}

.form-group input {
  padding: 14px 18px;
  border: none;
  border-radius: 12px;
  background: var(--neu-bg);
  color: var(--neu-text);
  font-size: 1rem;
  transition: all 0.3s ease;
  box-shadow: var(--neu-shadow-inset);
}

.form-group input:focus {
  outline: none;
  box-shadow:
    inset 6px 6px 10px var(--neu-shadow-dark),
    inset -6px -6px 10px var(--neu-shadow-light),
    0 0 0 3px rgba(108, 139, 163, 0.2);
}

.form-group input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.password-requirements {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding: 12px 16px;
  background: var(--neu-bg);
  border-radius: 12px;
  box-shadow:
    inset 3px 3px 6px var(--neu-shadow-dark),
    inset -3px -3px 6px var(--neu-shadow-light);
}

.requirement {
  font-size: 0.85rem;
  color: var(--neu-text-light);
  transition: color 0.3s ease;
  font-weight: 500;
}

.requirement.met {
  color: var(--neu-primary);
  font-weight: 600;
}

.error-hint {
  font-size: 0.85rem;
  color: #c62828;
  margin-top: 4px;
  font-weight: 600;
}

.error-message {
  padding: 14px;
  background: linear-gradient(145deg, #f5c4c4, #e8a8a8);
  border-radius: 12px;
  color: #c62828;
  font-size: 0.9rem;
  text-align: center;
  font-weight: 600;
  box-shadow:
    4px 4px 8px var(--neu-shadow-dark),
    -4px -4px 8px var(--neu-shadow-light);
}

.btn-primary {
  padding: 14px 24px;
  background: linear-gradient(145deg, #e9eef5, #d1d9e6);
  color: var(--neu-primary);
  border: none;
  border-radius: 12px;
  font-size: 1rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s ease;
  margin-top: 10px;
  box-shadow: var(--neu-shadow-btn);
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: var(--neu-shadow-btn-hover);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: var(--neu-shadow-btn-active);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.auth-footer {
  margin-top: 30px;
  text-align: center;
  color: var(--neu-text-light);
  font-size: 0.9rem;
}

.auth-footer a {
  color: var(--neu-primary);
  text-decoration: none;
  font-weight: 600;
  transition: color 0.3s ease;
}

.auth-footer a:hover {
  color: var(--neu-primary-dark);
}

.quota-info {
  margin-top: 30px;
  padding: 20px;
  background: var(--neu-bg);
  border-radius: 16px;
  box-shadow:
    inset 4px 4px 8px var(--neu-shadow-dark),
    inset -4px -4px 8px var(--neu-shadow-light);
}

.quota-title {
  font-size: 0.95rem;
  color: var(--neu-primary);
  margin: 0 0 15px 0;
  text-align: center;
  font-weight: 700;
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
  color: var(--neu-text-light);
  font-weight: 500;
}

.quota-value {
  font-size: 1.1rem;
  color: var(--neu-text);
  font-weight: 700;
}
</style>
