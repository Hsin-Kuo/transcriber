<template>
  <div class="checkout-container">
    <!-- Header -->
    <div class="checkout-header">
      <button class="back-btn" @click="$router.push('/settings')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
        {{ $t('userSettings.checkout.backToPlans') }}
      </button>
      <h1>{{ $t('userSettings.checkout.title') }}</h1>
    </div>

    <div class="checkout-content">
      <!-- Order Summary -->
      <div class="summary-card">
        <h2>{{ $t('userSettings.checkout.orderSummary') }}</h2>

        <div class="summary-plan">
          <span class="summary-label">{{ $t('userSettings.checkout.plan') }}</span>
          <span class="summary-value plan-name">{{ planLabel }}</span>
        </div>
        <div class="summary-row">
          <span class="summary-label">{{ $t('userSettings.checkout.billingCycle') }}</span>
          <span class="summary-value">{{ billing === 'yearly' ? $t('userSettings.checkout.yearly') : $t('userSettings.checkout.monthly') }}</span>
        </div>

        <div class="summary-divider"></div>

        <div class="summary-row">
          <span class="summary-label">{{ $t('userSettings.checkout.subtotal') }}</span>
          <span class="summary-value">${{ billing === 'yearly' ? (prices[plan] * 12).toFixed(2) : prices[plan].toFixed(2) }}</span>
        </div>
        <div v-if="billing === 'yearly'" class="summary-row discount-row">
          <span class="summary-label">{{ $t('userSettings.checkout.yearlyDiscount') }}</span>
          <span class="summary-value discount-value">-${{ prices[plan].toFixed(2) }}</span>
        </div>

        <div class="summary-divider"></div>

        <div class="summary-row total">
          <span class="summary-label">{{ $t('userSettings.checkout.total') }}</span>
          <span class="summary-value">${{ totalPrice }}{{ billing === 'yearly' ? $t('userSettings.checkout.perYear') : $t('userSettings.checkout.perMonth') }}</span>
        </div>

        <button class="pay-btn" :disabled="paying" @click="handlePay">
          <svg v-if="!paying" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
          {{ paying ? $t('userSettings.checkout.processing') : $t('userSettings.checkout.pay') }}
        </button>

        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>

        <p class="secure-note">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
          {{ $t('userSettings.checkout.secure') }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const plan = ref(route.query.plan || 'basic')
const billing = ref(route.query.billing || 'monthly')
const paying = ref(false)
const errorMsg = ref(null)

const prices = { free: 0, basic: 9.99, pro: 29.99 }

const planLabel = computed(() => {
  const labels = { free: 'Free', basic: 'Basic', pro: 'Pro' }
  return labels[plan.value] || plan.value
})

const totalPrice = computed(() => {
  const base = prices[plan.value] || 0
  if (billing.value === 'yearly') {
    return (Math.round(base * 11 * 100) / 100).toFixed(2)
  }
  return base.toFixed(2)
})

async function handlePay() {
  paying.value = true
  errorMsg.value = null
  try {
    const result = await authStore.createCheckoutSession(plan.value, billing.value)
    // 跳轉到 Stripe Checkout 頁面
    window.location.href = result.checkout_url
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || $t('userSettings.checkout.error')
    paying.value = false
  }
}

onMounted(() => {
  if (plan.value === 'free') {
    router.push('/settings')
  }
})
</script>

<style scoped>
.checkout-container {
  max-width: 520px;
  margin: 0 auto;
  padding: 32px 24px;
}

.checkout-header {
  margin-bottom: 32px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: var(--main-text-light);
  font-size: 14px;
  cursor: pointer;
  padding: 0;
  margin-bottom: 12px;
  transition: color 0.2s ease;
}

.back-btn:hover {
  color: var(--main-text);
}

.checkout-header h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0;
}

.summary-card {
  background: var(--upload-bg, #fff);
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
  border-radius: 12px;
  padding: 24px;
}

.summary-card h2 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--main-text);
  margin: 0 0 20px 0;
}

.summary-plan {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.plan-name {
  font-weight: 700;
  color: var(--main-primary);
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
}

.summary-label {
  font-size: 14px;
  color: var(--main-text-light);
}

.summary-value {
  font-size: 14px;
  color: var(--main-text);
  font-weight: 500;
}

.discount-row .summary-label {
  color: var(--color-success, #28a745);
}

.discount-value {
  color: var(--color-success, #28a745) !important;
  font-weight: 600 !important;
}

.summary-row.total .summary-label,
.summary-row.total .summary-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--main-text);
}

.summary-divider {
  height: 1px;
  background: var(--color-divider, rgba(163, 177, 198, 0.2));
  margin: 12px 0;
}

.pay-btn {
  width: 100%;
  padding: 12px;
  margin-top: 20px;
  background: var(--main-primary);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.pay-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}

.pay-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-msg {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--color-danger, #dc3545);
  text-align: center;
}

.secure-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--main-text-light);
}

@media (max-width: 768px) {
  .checkout-container {
    padding: 16px;
  }

  .checkout-header h1 {
    font-size: 1.25rem;
  }
}
</style>
