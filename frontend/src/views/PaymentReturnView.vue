<template>
  <div class="return-container">
    <div class="return-card">
      <!-- 處理中 -->
      <template v-if="status === 'processing'">
        <div class="spinner"></div>
        <h2>{{ $t('paymentReturn.processing') }}</h2>
        <p>{{ $t('paymentReturn.processingHint') }}</p>
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
import api from '../utils/api'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const status = ref('processing')
const successMessage = ref(t('paymentReturn.subscriptionActivated'))

const MAX_POLLS = 10
const POLL_INTERVAL = 1500

// 藍新 ReturnURL 的 MerchantOrderNo 前綴對應訂單類型
function detectOrderType(orderNo) {
  if (!orderNo) return 'subscription'
  if (orderNo.startsWith('SLEXT')) return 'extra_quota'
  if (orderNo.startsWith('SLDWN')) return 'downgrade'
  return 'subscription'
}

onMounted(async () => {
  const newebpayStatus = route.query.Status
  if (newebpayStatus && newebpayStatus !== 'SUCCESS') {
    status.value = 'failed'
    return
  }

  const orderNo = route.query.MerchantOrderNo || ''
  const orderType = detectOrderType(orderNo)
  const isExtraQuota = orderType === 'extra_quota'

  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise(r => setTimeout(r, POLL_INTERVAL))
    try {
      const resp = await api.get('/subscriptions/status')
      const sub = resp.data

      if (isExtraQuota) {
        // 額外額度：等 extra_quota 有值或 Notify 延遲後直接成功
        const hasExtra = (sub.extra_quota?.duration_minutes > 0) || (sub.extra_quota?.ai_summaries > 0)
        if (hasExtra || i >= 4) {
          await authStore.fetchCurrentUser()
          successMessage.value = t('paymentReturn.extraQuotaReady')
          status.value = 'success'
          return
        }
      } else {
        // 訂閱類：等 status 變為 active
        if (sub.status === 'active') {
          await authStore.fetchCurrentUser()
          successMessage.value = t('paymentReturn.planActivated', { plan: sub.tier === 'pro' ? 'Pro' : 'Basic' })
          status.value = 'success'
          return
        }
      }
    } catch (e) {
      // ignore, keep polling
    }
  }

  await authStore.fetchCurrentUser()
  status.value = 'success'
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
