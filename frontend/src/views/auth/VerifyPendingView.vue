<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-content">
        <div class="pending-icon">{{ initialSent ? '✉️' : '⚠️' }}</div>

        <h1 class="auth-title">
          {{ initialSent ? '請查看您的信箱' : '帳號已建立，請重發驗證信' }}
        </h1>

        <p class="auth-subtitle">
          <template v-if="initialSent">
            我們已將驗證連結寄到 <strong>{{ email }}</strong>，點開連結即可完成註冊。
          </template>
          <template v-else>
            帳號 <strong>{{ email }}</strong> 已建立，但驗證信寄送暫時失敗。請按下方按鈕重新寄送。
          </template>
        </p>

        <div class="hint-box">
          <p class="hint-title">沒收到信？</p>
          <ul class="hint-list">
            <li>確認是否進到「垃圾郵件」或「促銷活動」資料夾</li>
            <li>確認 email 地址沒打錯（目前是 <code>{{ email }}</code>）</li>
            <li>等候一兩分鐘後再重新寄送</li>
          </ul>
        </div>

        <!-- 重發按鈕 + cooldown -->
        <button
          type="button"
          class="btn-primary"
          :disabled="cooldownRemaining > 0 || resending"
          @click="handleResend"
        >
          <span v-if="resending">寄送中...</span>
          <span v-else-if="cooldownRemaining > 0">{{ cooldownRemaining }} 秒後可重新寄送</span>
          <span v-else>重新寄送驗證信</span>
        </button>

        <!-- 重發結果訊息 -->
        <div v-if="resendNotice" :class="['notice', resendError ? 'notice-error' : 'notice-success']">
          {{ resendNotice }}
        </div>

        <div class="auth-footer">
          <p>
            收到信並完成驗證後，
            <router-link to="/login">前往登入</router-link>
          </p>
          <p class="muted">
            打錯 email？<router-link to="/register">回到註冊頁</router-link>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../utils/api'

const route = useRoute()
const router = useRouter()

// 後端 cooldown = 60s（src/routers/auth.py: RESEND_VERIFICATION_COOLDOWN_SECONDS）
const COOLDOWN_SECONDS = 60

const email = computed(() => String(route.query.email || ''))
// 從 query.sent 判斷初次寄信是否成功；缺省當作 sent=true
const initialSent = computed(() => route.query.sent !== 'false')

const cooldownRemaining = ref(COOLDOWN_SECONDS)
const resending = ref(false)
const resendNotice = ref('')
const resendError = ref(false)

let timer = null

function startCooldown(seconds = COOLDOWN_SECONDS) {
  cooldownRemaining.value = seconds
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    cooldownRemaining.value -= 1
    if (cooldownRemaining.value <= 0) {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

onMounted(() => {
  // 沒帶 email 進來直接踢回 register（避免空頁誤導）
  if (!email.value) {
    router.replace('/register')
    return
  }
  // 初次寄信失敗時，不啟動 cooldown，讓使用者可以立刻按重發
  if (initialSent.value) {
    startCooldown()
  } else {
    cooldownRemaining.value = 0
  }
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

async function handleResend() {
  if (resending.value || cooldownRemaining.value > 0) return
  resending.value = true
  resendNotice.value = ''
  resendError.value = false

  try {
    await api.post('/auth/resend-verification', { email: email.value })
    resendNotice.value = '驗證信已重新寄出，請查看您的信箱'
    resendError.value = false
    startCooldown()
  } catch (err) {
    const status = err.response?.status
    const detail = err.response?.data?.detail
    resendError.value = true
    resendNotice.value = detail || '寄送失敗，請稍後再試'
    // 429: 後端告訴我們再等多久；解析訊息中的秒數啟動 cooldown
    if (status === 429) {
      const match = String(detail || '').match(/(\d+)\s*秒/)
      const secs = match ? parseInt(match[1], 10) : COOLDOWN_SECONDS
      startCooldown(secs)
    }
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
  padding: 50px 40px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}

.pending-icon {
  font-size: 3.5rem;
}

.auth-title {
  font-size: 1.6rem;
  color: var(--main-text);
  margin: 0;
  font-weight: 700;
}

.auth-subtitle {
  font-size: 1rem;
  color: var(--main-text-light);
  margin: 0;
  line-height: 1.6;
}

.auth-subtitle strong {
  color: var(--main-text);
}

.hint-box {
  background: rgba(0, 0, 0, 0.03);
  border-radius: 10px;
  padding: 16px 20px;
  text-align: left;
  width: 100%;
}

.hint-title {
  font-size: 0.95rem;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: var(--main-text);
}

.hint-list {
  margin: 0;
  padding-left: 20px;
  font-size: 0.9rem;
  color: var(--main-text-light);
  line-height: 1.7;
}

.hint-list code {
  background: rgba(0, 0, 0, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em;
}

.btn-primary {
  padding: 14px 28px;
  background: var(--main-primary-dark, var(--main-primary));
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  min-width: 240px;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.notice {
  width: 100%;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 0.95rem;
  margin: 0;
}

.notice-success {
  background: #d4edda;
  color: #155724;
  border: 1px solid #c3e6cb;
}

.notice-error {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

.auth-footer {
  font-size: 0.9rem;
  color: var(--main-text-light);
  margin-top: 4px;
}

.auth-footer p {
  margin: 4px 0;
}

.auth-footer .muted {
  font-size: 0.85rem;
  opacity: 0.85;
}

.auth-footer a {
  color: var(--main-primary);
  text-decoration: none;
  font-weight: 600;
}

.auth-footer a:hover {
  text-decoration: underline;
}
</style>
