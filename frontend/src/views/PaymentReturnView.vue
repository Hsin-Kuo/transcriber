<template>
  <div class="return-container">
    <div class="return-card">
      <!-- 處理中 -->
      <template v-if="status === 'processing'">
        <div v-if="!timedOut" class="spinner"></div>
        <h2>{{ $t('paymentReturn.processing') }}</h2>
        <p>{{ timedOut ? $t('paymentReturn.timeoutHint') : $t('paymentReturn.processingHint') }}</p>
        <button v-if="timedOut" class="action-btn secondary" @click="$router.push('/settings')">{{ $t('paymentReturn.backToSettings') }}</button>
      </template>

      <!-- 成功 -->
      <template v-else-if="status === 'success'">
        <div class="icon-success">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
        <h2>{{ $t('paymentReturn.success') }}</h2>
        <p>{{ successMessage }}</p>
        <button class="action-btn" @click="$router.push('/settings')">{{ $t('paymentReturn.backToSettings') }}</button>
      </template>

      <!-- 失敗 -->
      <template v-else-if="status === 'failed'">
        <div class="icon-failed">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </div>
        <h2>{{ $t('paymentReturn.failed') }}</h2>
        <p>{{ $t('paymentReturn.failedHint') }}</p>
        <button class="action-btn secondary" @click="$router.push('/settings')">{{ $t('common.back') }}</button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const route = useRoute()
const authStore = useAuthStore()

// 換卡挽回導回（?recovered=1）：past_due → active 屬「恢復」，用專屬文案。
// 加購導回（?extra=1）：訂閱狀態不變（本就 active），成功後額度入帳，用專屬文案。
// 3D 導回由後端控制 URL 不帶此旗標，此時走一般 planActivated 文案，語意仍正確。
const isRecovered = route.query.recovered === '1'
const isExtra = route.query.extra === '1'

const status = ref('processing')
const timedOut = ref(false)
const successMessage = ref(t(
  isExtra ? 'paymentReturn.extraQuotaReady'
    : isRecovered ? 'paymentReturn.subscriptionResumed'
    : 'paymentReturn.subscriptionActivated'
))

// 91APP 3D 導回後只帶 order_no，扣款結果由後端 webhook 非同步落地，
// 因此前端輪詢 /subscriptions/status 直到 active。每 2 秒一次、最多約 30 秒。
const MAX_POLLS = 15
const POLL_INTERVAL = 2000

onMounted(async () => {
  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise(r => setTimeout(r, POLL_INTERVAL))
    try {
      const sub = await authStore.getSubscriptionStatus()
      if (sub.status === 'active') {
        await authStore.fetchCurrentUser()
        successMessage.value = isExtra
          ? t('paymentReturn.extraQuotaReady')
          : isRecovered
            ? t('paymentReturn.subscriptionResumed')
            : t('paymentReturn.planActivated', { plan: sub.tier === 'pro' ? 'Pro' : 'Basic' })
        status.value = 'success'
        return
      }
    } catch (e) {
      // 忽略暫時性錯誤，繼續輪詢
    }
  }

  // 逾時：扣款可能仍在處理，提示稍後於設定頁查看（保留 processing 狀態）
  await authStore.fetchCurrentUser()
  timedOut.value = true
})
</script>

<style scoped>
.return-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.return-card {
  background: var(--upload-bg, #fff);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
  border-radius: 16px;
  padding: 48px 40px;
  text-align: center;
  max-width: 400px;
  width: 100%;
}

.return-card h2 {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 16px 0 8px;
}

.return-card p {
  font-size: 15px;
  color: var(--main-text-light);
  margin: 0 0 24px;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-top-color: var(--main-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 16px;
}

@keyframes spin { to { transform: rotate(360deg); } }

.icon-success, .icon-failed {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}

.icon-success {
  background: rgba(40, 167, 69, 0.1);
  color: var(--color-success, #28a745);
}

.icon-failed {
  background: rgba(220, 53, 69, 0.1);
  color: var(--color-danger, #dc3545);
}

.action-btn {
  padding: 10px 32px;
  background: var(--main-primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.action-btn:hover { opacity: 0.9; }

.action-btn.secondary {
  background: transparent;
  color: var(--main-text);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
}
</style>
