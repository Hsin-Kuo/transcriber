<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-content">
          <h1 class="auth-title">忘記密碼</h1>
          <p class="auth-subtitle">Sound Lite 轉錄服務</p>

          <form v-if="!success" @submit.prevent="handleSubmit" class="auth-form">
            <p class="form-description">
              請輸入您註冊時使用的 Email，我們將發送密碼重設連結給您。
            </p>

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

            <div v-if="error" class="error-message">
              {{ error }}
            </div>

            <button
              type="submit"
              class="btn-primary"
              :disabled="loading || !email"
            >
              {{ loading ? '發送中...' : '發送重設郵件' }}
            </button>
          </form>

          <div v-else class="success-message">
            <div class="success-icon">📧</div>
            <p class="success-title">{{ successMessage }}</p>
            <p class="success-subtitle">
              如果 <strong>{{ email }}</strong> 已註冊，您將會收到密碼重設郵件。
            </p>
            <p class="success-note">
              沒收到郵件？請檢查垃圾郵件資料夾，或稍後再試。
            </p>

            <button
              type="button"
              class="btn-secondary"
              @click="router.push('/login')"
            >
              返回登入頁面
            </button>
          </div>

          <div v-if="!success" class="auth-footer">
            <p>想起密碼了？<router-link to="/login">返回登入</router-link></p>
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
const loading = ref(false)
const error = ref('')
const success = ref(false)
const successMessage = ref('')

async function handleSubmit() {
  loading.value = true
  error.value = ''

  const result = await authStore.forgotPassword(email.value)

  if (result.success) {
    success.value = true
    successMessage.value = result.message || '重設郵件已發送'
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

.error-message {
  color: var(--color-danger-dark);
  font-size: 0.85rem;
  text-align: left;
  font-weight: 500;
  margin-bottom: 4px;
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
}

.success-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--color-success-dark);
  margin: 0 0 12px 0;
}

.success-subtitle {
  font-size: 0.95rem;
  color: var(--color-success-dark);
  margin: 0 0 16px 0;
  line-height: 1.5;
}

.success-subtitle strong {
  font-weight: 700;
  color: var(--color-success-dark);
}

.success-note {
  font-size: 0.85rem;
  color: var(--color-success-dark);
  margin: 0 0 20px 0;
  line-height: 1.6;
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

.btn-secondary {
  padding: 14px 24px;
  background: var(--color-white);
  color: var(--main-primary);
  border: 2px solid var(--main-primary);
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  margin-top: 10px;
  width: 100%;
}

.btn-secondary:hover {
  background: var(--main-primary);
  color: var(--color-white);
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(var(--color-text-dark-rgb), 0.15);
}

.btn-secondary:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(var(--color-text-dark-rgb), 0.1);
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
