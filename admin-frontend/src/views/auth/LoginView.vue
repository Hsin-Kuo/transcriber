<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <div class="brand-icon">
          <svg width="48" height="48" viewBox="0 0 28 28">
            <rect x="0" y="0" width="28" height="28" rx="4" fill="currentColor"/>
            <circle cx="14" cy="14" r="2" fill="#f4ecd5"/>
            <circle cx="14" cy="9" r="1.5" fill="#f4ecd5"/>
            <circle cx="18.3" cy="11.5" r="1.5" fill="#f4ecd5"/>
            <circle cx="18.3" cy="16.5" r="1.5" fill="#f4ecd5"/>
            <circle cx="14" cy="19" r="1.5" fill="#f4ecd5"/>
            <circle cx="9.7" cy="16.5" r="1.5" fill="#f4ecd5"/>
            <circle cx="9.7" cy="11.5" r="1.5" fill="#f4ecd5"/>
          </svg>
        </div>
        <h1 class="login-title">管理後台</h1>
        <p class="login-subtitle">Whisper 轉錄服務</p>
      </div>

      <form @submit.prevent="handleLogin" class="login-form">
        <div class="form-group">
          <label for="email">Email</label>
          <input
            type="email"
            id="email"
            v-model="email"
            required
            placeholder="admin@example.com"
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
            placeholder="輸入密碼"
            minlength="8"
            :disabled="loading"
          />
        </div>

        <div v-if="error" class="error-alert">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          {{ error }}
        </div>

        <button type="submit" class="submit-btn" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '登入中...' : '登入' }}
        </button>
      </form>

      <div class="login-footer">
        <p>僅限管理員帳號登入</p>
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

async function handleLogin() {
  loading.value = true
  error.value = ''

  const result = await authStore.login(email.value, password.value)

  if (result.success) {
    // 檢查是否為管理員
    if (!authStore.isAdmin) {
      error.value = '此帳號沒有管理員權限'
      await authStore.logout()
      loading.value = false
      return
    }

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
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: linear-gradient(135deg, #f5f5f5 0%, #e8e4db 100%);
}

.login-card {
  width: 100%;
  max-width: 420px;
  background: white;
  border-radius: 16px;
  padding: 40px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.08);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.brand-icon {
  display: inline-flex;
  color: var(--color-primary, #dd8448);
  margin-bottom: 16px;
}

.login-title {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--color-text, rgb(145, 106, 45));
  margin: 0 0 8px 0;
}

.login-subtitle {
  font-size: 0.9rem;
  color: var(--color-text-light, #a0917c);
  margin: 0;
}

.login-form {
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
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, rgb(145, 106, 45));
}

.form-group input {
  padding: 14px 16px;
  border: 1px solid rgba(163, 177, 198, 0.4);
  border-radius: 10px;
  font-size: 15px;
  transition: border-color 0.2s, box-shadow 0.2s;
  background: #fafafa;
}

.form-group input:focus {
  outline: none;
  border-color: var(--color-primary, #dd8448);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.12);
  background: white;
}

.form-group input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.form-group input::placeholder {
  color: #aaa;
}

.error-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  background: #fff5f5;
  border: 1px solid #fed7d7;
  border-radius: 10px;
  color: #c53030;
  font-size: 14px;
  font-weight: 500;
}

.error-alert svg {
  flex-shrink: 0;
}

.submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 24px;
  background: var(--color-primary, #dd8448);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s, transform 0.2s;
  margin-top: 8px;
}

.submit-btn:hover:not(:disabled) {
  background: var(--color-primary-dark, #b8762d);
  transform: translateY(-1px);
}

.submit-btn:active:not(:disabled) {
  transform: translateY(0);
}

.submit-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  transform: none;
}

.submit-btn .spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
}

.login-footer {
  margin-top: 28px;
  text-align: center;
}

.login-footer p {
  font-size: 13px;
  color: var(--color-text-light, #a0917c);
}

@media (max-width: 480px) {
  .login-card {
    padding: 28px 24px;
  }

  .login-title {
    font-size: 1.5rem;
  }
}
</style>
