<template>
  <div class="auth-container">
    <ElectricBorder />

    <div class="auth-card electric-card">
      <div class="electric-inner">
        <div class="auth-content">
          <!-- 驗證中 -->
          <div v-if="verifying" class="verifying-state">
            <div class="spinner-large"></div>
            <h2>正在驗證您的 Email...</h2>
            <p>請稍候</p>
          </div>

          <!-- 驗證成功 -->
          <div v-else-if="success" class="success-state">
            <h2>Email 驗證成功！</h2>
            <p class="success-message">您的帳號已啟用，現在可以登入使用了</p>
            <button class="btn-primary" @click="router.push('/login')">
              前往登入
            </button>
          </div>

          <!-- 驗證失敗 -->
          <div v-else class="error-state">
            <h2>驗證失敗</h2>
            <p class="error-message">{{ errorMessage }}</p>
            <div class="error-actions">
              <button class="btn-primary" @click="router.push('/login')">
                前往登入
              </button>
              <button class="btn-secondary" @click="router.push('/register')">
                重新註冊
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
import ElectricBorder from '../../components/shared/ElectricBorder.vue'

const router = useRouter()
const route = useRoute()

const verifying = ref(true)
const success = ref(false)
const errorMessage = ref('')

onMounted(async () => {
  const token = route.query.token

  if (!token) {
    verifying.value = false
    errorMessage.value = '缺少驗證 token'
    return
  }

  try {
    const response = await fetch(
      `${import.meta.env.VITE_API_URL || 'http://100.66.247.23:8000'}/auth/verify-email?token=${token}`
    )

    const data = await response.json()

    if (response.ok) {
      success.value = true
    } else {
      errorMessage.value = data.detail || '驗證失敗，請重試'
    }
  } catch (error) {
    errorMessage.value = '網路錯誤，請稍後再試'
  } finally {
    verifying.value = false
  }
})
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

.success-message,
.error-message {
  font-size: 1.1rem;
  color: var(--main-text-light);
  margin: 0;
  line-height: 1.6;
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

.btn-primary:hover {
  transform: translateY(-2px);
}

.btn-primary:active {
  transform: translateY(0);
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
