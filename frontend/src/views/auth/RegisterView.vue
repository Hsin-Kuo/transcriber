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
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
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
  background: linear-gradient(135deg, #00f2ff 0%, #00aaff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.auth-subtitle {
  text-align: center;
  color: #8892b0;
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
  color: #8892b0;
  font-weight: 500;
}

.form-group input {
  padding: 12px 16px;
  border: 2px solid rgba(100, 255, 218, 0.3);
  border-radius: 8px;
  background: rgba(17, 34, 64, 0.5);
  color: #e6f1ff;
  font-size: 1rem;
  transition: all 0.3s ease;
}

.form-group input:focus {
  outline: none;
  border-color: #64ffda;
  box-shadow: 0 0 15px rgba(100, 255, 218, 0.3);
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
  padding: 12px;
  background: rgba(17, 34, 64, 0.3);
  border-radius: 6px;
}

.requirement {
  font-size: 0.85rem;
  color: #8892b0;
  transition: color 0.3s ease;
}

.requirement.met {
  color: #64ffda;
}

.error-hint {
  font-size: 0.85rem;
  color: #ff6b6b;
  margin-top: 4px;
}

.error-message {
  padding: 12px;
  background: rgba(255, 107, 107, 0.1);
  border: 1px solid rgba(255, 107, 107, 0.3);
  border-radius: 6px;
  color: #ff6b6b;
  font-size: 0.9rem;
  text-align: center;
}

.btn-primary {
  padding: 14px 24px;
  background: linear-gradient(135deg, #00f2ff 0%, #00aaff 100%);
  color: #0a192f;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  margin-top: 10px;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 5px 20px rgba(0, 242, 255, 0.4);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.auth-footer {
  margin-top: 30px;
  text-align: center;
  color: #8892b0;
  font-size: 0.9rem;
}

.auth-footer a {
  color: #64ffda;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.3s ease;
}

.auth-footer a:hover {
  color: #00f2ff;
}

.quota-info {
  margin-top: 30px;
  padding: 20px;
  background: rgba(100, 255, 218, 0.05);
  border: 1px solid rgba(100, 255, 218, 0.2);
  border-radius: 8px;
}

.quota-title {
  font-size: 0.95rem;
  color: #64ffda;
  margin: 0 0 15px 0;
  text-align: center;
  font-weight: 500;
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
  color: #8892b0;
}

.quota-value {
  font-size: 1.1rem;
  color: #e6f1ff;
  font-weight: 600;
}
</style>
