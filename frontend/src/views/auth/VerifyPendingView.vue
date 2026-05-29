<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-content">
        <!-- ===== Bounced / Complained 狀態：email 收信異常 ===== -->
        <template v-if="bounced">
          <div class="pending-icon">❌</div>

          <h1 class="auth-title">
            {{ status === 'complained' ? '此 Email 已標記為拒收' : 'Email 似乎無法送達' }}
          </h1>

          <p class="auth-subtitle">
            <template v-if="status === 'complained'">
              我們收到了 <strong>{{ email }}</strong> 的收件方標示「不想再收信」，將不再嘗試寄送。
            </template>
            <template v-else>
              <strong>{{ email }}</strong> 收信失敗 — 信箱可能不存在或拼字有誤。
            </template>
          </p>

          <div class="hint-box hint-box-warning">
            <p class="hint-title">您可以：</p>
            <ul class="hint-list">
              <li>確認 email 拼字（漏字母 / 多字母 / 域名打錯）</li>
              <li>使用其他 email 重新註冊</li>
            </ul>
          </div>

          <button
            type="button"
            class="btn-primary"
            :disabled="abandoning"
            @click="handleAbandon"
          >
            <span v-if="abandoning">處理中...</span>
            <span v-else>改用其他 email 重新註冊</span>
          </button>

          <div class="auth-footer">
            <p class="muted">
              如果您確定 email 沒打錯，請聯絡支援團隊
            </p>
          </div>
        </template>

        <!-- ===== 正常 pending / verified 狀態 ===== -->
        <template v-else>
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

          <!-- Polling 5 分鐘超時提示 -->
          <div v-if="pollTimedOut" class="notice notice-info">
            已停止自動偵測。若您已完成驗證，請手動<router-link to="/login">前往登入</router-link>。
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
        </template>
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

// 'pending' | 'verified' | 'bounced' | 'complained'
const status = ref('pending')
const bounced = computed(() => status.value === 'bounced' || status.value === 'complained')
const abandoning = ref(false)
const pollTimedOut = ref(false)  // 5min polling 結束仍 pending 時顯示提示

let timer = null
let pollTimer = null
const POLL_INTERVAL_MS = 15_000
const POLL_MAX_DURATION_MS = 5 * 60_000  // 5 分鐘上限
let pollStartedAt = 0

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

async function pollStatus() {
  if (!email.value) return
  try {
    const { data } = await api.get('/auth/registration-status', {
      params: { email: email.value },
      // 背景 polling — 撞 429 不要彈全域 rate-limit toast 騷擾用戶
      _silentRateLimit: true,
    })
    status.value = data.status || 'pending'

    // verified 狀態被後端故意隱藏（防 enumeration），前端不再 auto-redirect
    if (bounced.value) {
      // bounce / complaint → 終態，停止 poll
      stopPolling()
    }
  } catch (err) {
    // poll 失敗只是暫時 — 不打斷 user，下次再試
  }
}

function startPolling() {
  pollStartedAt = Date.now()
  pollTimedOut.value = false
  // 立即跑一次（剛收到 webhook 的 case）
  pollStatus()
  pollTimer = setInterval(() => {
    if (Date.now() - pollStartedAt > POLL_MAX_DURATION_MS) {
      stopPolling()
      // 仍 pending（非 bounced）才顯示 timeout 提示
      if (!bounced.value) {
        pollTimedOut.value = true
      }
      return
    }
    pollStatus()
  }, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
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
  startPolling()
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  stopPolling()
})

async function handleAbandon() {
  if (abandoning.value) return
  abandoning.value = true
  try {
    // 後端永遠回 200，這裡的 await 主要是等刪除完成再跳轉
    await api.post('/auth/abandon-registration', { email: email.value })
  } catch (err) {
    // 即使失敗也帶用戶回 register — UX 比 strict 重要
  } finally {
    router.replace('/register')
  }
}

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
    // 重新計算 poll 視窗，給新一輪寄信完整 5 分鐘的監測時間
    stopPolling()
    startPolling()
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

.hint-box.hint-box-warning {
  background: #fff3cd;
  border: 1px solid #ffeeba;
}

.hint-box.hint-box-warning .hint-title,
.hint-box.hint-box-warning .hint-list {
  color: #856404;
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

.notice-info {
  background: #d1ecf1;
  color: #0c5460;
  border: 1px solid #bee5eb;
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
