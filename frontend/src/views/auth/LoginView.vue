<template>
  <div class="auth-container">
    <ElectricBorder />

    <div class="auth-card electric-card">
      <div class="electric-inner">
        <div class="auth-content">
          <h1 class="auth-title">🎙️ 登入</h1>
          <p class="auth-subtitle">Whisper 轉錄服務</p>

          <form @submit.prevent="handleLogin" class="auth-form">
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
              />
            </div>

            <div v-if="error" class="error-message">
              {{ error }}
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
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import ElectricBorder from '../../components/shared/ElectricBorder.vue'

const router = useRouter()
const authStore = useAuthStore()

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  loading.value = true
  error.value = ''

  const result = await authStore.login(email.value, password.value)

  if (result.success) {
    // 登入成功，跳轉到原頁面或首頁
    const redirect = router.currentRoute.value.query.redirect || '/'
    router.push(redirect)
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
  max-width: 450px;
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
</style>
