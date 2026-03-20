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

    <div class="checkout-grid">
      <!-- Left: Form -->
      <div class="checkout-form">
        <!-- Billing Info -->
        <section class="form-section">
          <h2>{{ $t('userSettings.checkout.billing') }}</h2>
          <div class="form-row">
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.firstName') }}</label>
              <input v-model="form.firstName" type="text" class="form-input" />
            </div>
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.lastName') }}</label>
              <input v-model="form.lastName" type="text" class="form-input" />
            </div>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.checkout.email') }}</label>
            <input v-model="form.email" type="email" class="form-input" />
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.checkout.country') }}</label>
            <select v-model="form.country" class="form-input">
              <option value="TW">Taiwan</option>
              <option value="US">United States</option>
              <option value="JP">Japan</option>
              <option value="HK">Hong Kong</option>
              <option value="GB">United Kingdom</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ $t('userSettings.checkout.address') }}</label>
            <input v-model="form.address" type="text" class="form-input" />
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.city') }}</label>
              <input v-model="form.city" type="text" class="form-input" />
            </div>
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.postalCode') }}</label>
              <input v-model="form.postalCode" type="text" class="form-input" />
            </div>
          </div>
        </section>

        <!-- Payment -->
        <section class="form-section">
          <h2>{{ $t('userSettings.checkout.payment') }}</h2>
          <div class="payment-methods">
            <label class="payment-method active">
              <input type="radio" value="card" v-model="form.paymentMethod" />
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="1" y="4" width="22" height="16" rx="2" ry="2"></rect>
                <line x1="1" y1="10" x2="23" y2="10"></line>
              </svg>
              {{ $t('userSettings.checkout.creditCard') }}
            </label>
          </div>

          <div class="card-fields">
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.cardNumber') }}</label>
              <input
                v-model="form.cardNumber"
                type="text"
                class="form-input"
                :placeholder="$t('userSettings.checkout.cardNumberPlaceholder')"
                maxlength="19"
                @input="formatCardNumber"
              />
            </div>
            <div class="form-row form-row-3">
              <div class="form-group">
                <label>{{ $t('userSettings.checkout.expiry') }}</label>
                <input
                  v-model="form.expiry"
                  type="text"
                  class="form-input"
                  :placeholder="$t('userSettings.checkout.expiryPlaceholder')"
                  maxlength="5"
                  @input="formatExpiry"
                />
              </div>
              <div class="form-group">
                <label>{{ $t('userSettings.checkout.cvc') }}</label>
                <input
                  v-model="form.cvc"
                  type="text"
                  class="form-input"
                  :placeholder="$t('userSettings.checkout.cvcPlaceholder')"
                  maxlength="4"
                />
              </div>
            </div>
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.cardholderName') }}</label>
              <input
                v-model="form.cardholderName"
                type="text"
                class="form-input"
                :placeholder="$t('userSettings.checkout.cardholderNamePlaceholder')"
              />
            </div>
          </div>
        </section>
      </div>

      <!-- Right: Order Summary -->
      <div class="order-summary">
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
          <div class="summary-row">
            <span class="summary-label">{{ $t('userSettings.checkout.tax') }}</span>
            <span class="summary-value">$0.00</span>
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

const prices = { free: 0, basic: 9.99, pro: 29.99 }

const planLabel = computed(() => {
  const labels = { free: 'Free', basic: 'Basic', pro: 'Pro' }
  return labels[plan.value] || plan.value
})

const monthlyPrice = computed(() => {
  const base = prices[plan.value] || 0
  if (billing.value === 'yearly') {
    return (Math.round(base * 11 / 12 * 100) / 100).toFixed(2)
  }
  return base.toFixed(2)
})

const totalPrice = computed(() => {
  const base = prices[plan.value] || 0
  if (billing.value === 'yearly') {
    return (Math.round(base * 11 * 100) / 100).toFixed(2)
  }
  return base.toFixed(2)
})

const form = ref({
  firstName: '',
  lastName: '',
  email: authStore.user?.email || '',
  country: 'TW',
  address: '',
  city: '',
  postalCode: '',
  paymentMethod: 'card',
  cardNumber: '',
  expiry: '',
  cvc: '',
  cardholderName: ''
})

function formatCardNumber() {
  let v = form.value.cardNumber.replace(/\D/g, '').substring(0, 16)
  form.value.cardNumber = v.replace(/(.{4})/g, '$1 ').trim()
}

function formatExpiry() {
  let v = form.value.expiry.replace(/\D/g, '').substring(0, 4)
  if (v.length >= 3) {
    v = v.substring(0, 2) + '/' + v.substring(2)
  }
  form.value.expiry = v
}

function handlePay() {
  paying.value = true
  // TODO: integrate payment provider
  setTimeout(() => {
    paying.value = false
  }, 2000)
}

onMounted(() => {
  if (plan.value === 'free') {
    router.push('/settings')
  }
})
</script>

<style scoped>
.checkout-container {
  max-width: 960px;
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

.checkout-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 32px;
  align-items: start;
}

/* Form sections */
.form-section {
  margin-bottom: 32px;
}

.form-section h2 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--main-text);
  margin: 0 0 16px 0;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-divider, rgba(163, 177, 198, 0.2));
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-row-3 {
  grid-template-columns: 1fr 1fr;
}

.form-group {
  margin-bottom: 14px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--main-text-light);
  margin-bottom: 6px;
}

.form-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 8px;
  background: var(--color-bg-light, var(--color-bg, #fff));
  font-size: 14px;
  color: var(--main-text);
  box-sizing: border-box;
  transition: border-color 0.2s ease;
}

.form-input:focus {
  outline: none;
  border-color: var(--main-primary);
  box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb), 0.1);
}

.form-input::placeholder {
  color: var(--main-text-light);
  opacity: 0.6;
}

select.form-input {
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 32px;
}

/* Payment methods */
.payment-methods {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.payment-method {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--main-text);
  cursor: pointer;
  transition: all 0.2s ease;
}

.payment-method input {
  display: none;
}

.payment-method.active {
  border-color: var(--main-primary);
  background: rgba(var(--color-primary-rgb), 0.05);
}

/* Order Summary */
.order-summary {
  position: sticky;
  top: 32px;
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

.summary-discount {
  text-decoration: line-through;
  opacity: 0.5;
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

.secure-note {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--main-text-light);
}

/* Responsive */
@media (max-width: 768px) {
  .checkout-container {
    padding: 16px;
  }

  .checkout-grid {
    grid-template-columns: 1fr;
    gap: 24px;
  }

  .order-summary {
    position: static;
  }

  .checkout-header h1 {
    font-size: 1.25rem;
  }
}

@media (max-width: 480px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}
</style>
