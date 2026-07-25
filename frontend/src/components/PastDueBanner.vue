<template>
  <!-- Dunning 橫幅：訂閱轉 past_due（續扣失敗、寬限期內仍保留服務）時顯示，
       引導使用者更新付款方式挽回。狀態來源為 authStore.subscriptionStatus
       （由 getSubscriptionStatus() 寫入），非 past_due 一律不渲染。 -->
  <div v-if="authStore.isPastDue" class="past-due-banner" role="alert">
    <div class="past-due-icon" aria-hidden="true">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
        <line x1="12" y1="9" x2="12" y2="13"></line>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
      </svg>
    </div>
    <div class="past-due-content">
      <p class="past-due-title">
        {{ authStore.needsCardUpdate ? $t('userSettings.pastDue.titleNeedsCard') : $t('userSettings.pastDue.title') }}
      </p>
      <p class="past-due-message">
        {{ authStore.needsCardUpdate ? $t('userSettings.pastDue.messageNeedsCard') : $t('userSettings.pastDue.message') }}
      </p>
      <p v-if="authStore.graceDeadline" class="past-due-grace">
        {{ $t('userSettings.pastDue.graceDeadline', { date: formatDate(authStore.graceDeadline) }) }}
      </p>
      <button class="past-due-cta" @click="handleUpdateCard">
        {{ $t('userSettings.pastDue.updateCardCta') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useDateFormatter } from '../composables/useDateFormatter'

const { t: $t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const { formatDate: formatDateTz } = useDateFormatter()

function formatDate(timestamp) {
  if (!timestamp) return ''
  return formatDateTz(timestamp, { month: 'long', day: 'numeric' })
}

// 進入 CheckoutView 的換卡挽回模式（recovery），重用既有 91APP SDK 流程。
function handleUpdateCard() {
  router.push({ path: '/checkout', query: { mode: 'update-card' } })
}
</script>

<style scoped>
/* 橘/黃警示風格，比照既有 sub-notice.warning / cancel-scheduled-badge */
.past-due-banner {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 16px;
  margin-bottom: 16px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 10px;
}

.past-due-icon {
  color: #d97706;
  flex-shrink: 0;
  margin-top: 1px;
}

.past-due-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.past-due-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--main-text);
  margin: 0;
}

.past-due-message {
  font-size: 13px;
  color: var(--main-text-light);
  margin: 0;
  line-height: 1.5;
}

.past-due-grace {
  font-size: 13px;
  font-weight: 600;
  color: #d97706;
  margin: 2px 0 0;
}

.past-due-cta {
  align-self: flex-start;
  margin-top: 8px;
  padding: 8px 16px;
  background: #d97706;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.past-due-cta:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}
</style>
