<template>
  <div class="checkout-container">
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
      <div class="summary-card">
        <h2>{{ $t('userSettings.checkout.orderSummary') }}</h2>

        <!-- 加購模式：品項 + 份數 + 單價 -->
        <template v-if="isAddon">
          <div class="summary-plan">
            <span class="summary-label">{{ $t('userSettings.checkout.addonItem') }}</span>
            <span class="summary-value plan-name">{{ addonLabel(addon) }}</span>
          </div>
          <div class="summary-row qty-row">
            <span class="summary-label">{{ $t('userSettings.checkout.quantity') }}</span>
            <div class="qty-stepper">
              <button class="qty-btn" :disabled="effectiveQty <= 1" @click="decQty" :aria-label="$t('userSettings.checkout.decreaseQty')">−</button>
              <input class="qty-input" type="number" min="1" max="99" v-model.number="quantity" @change="clampQty" />
              <button class="qty-btn" :disabled="effectiveQty >= 99" @click="incQty" :aria-label="$t('userSettings.checkout.increaseQty')">+</button>
            </div>
          </div>
          <div class="summary-row">
            <span class="summary-label">{{ $t('userSettings.checkout.unitPrice') }}</span>
            <span class="summary-value">NT${{ addon?.price_twd }} × {{ effectiveQty }}</span>
          </div>

          <div class="summary-divider"></div>

          <div class="summary-row total">
            <span class="summary-label">{{ $t('userSettings.checkout.total') }}</span>
            <span class="summary-value">NT${{ totalPrice }}</span>
          </div>
        </template>

        <!-- 訂閱模式：方案 + 計費週期 -->
        <template v-else>
          <div class="summary-plan">
            <span class="summary-label">{{ $t('userSettings.checkout.plan') }}</span>
            <span class="summary-value plan-name">{{ planLabel }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">{{ $t('userSettings.checkout.billingCycle') }}</span>
            <span class="summary-value">{{ billing === 'yearly' ? $t('userSettings.checkout.yearly') : $t('userSettings.checkout.monthly') }}</span>
          </div>

          <div class="summary-divider"></div>

          <div class="summary-row total">
            <span class="summary-label">{{ $t('userSettings.checkout.total') }}</span>
            <span class="summary-value">NT${{ totalPrice }}{{ billing === 'yearly' ? $t('userSettings.checkout.perYear') : $t('userSettings.checkout.perMonth') }}</span>
          </div>
        </template>

        <!-- 電子發票 -->
        <div class="invoice-section">
          <h3 class="invoice-title">{{ $t('userSettings.checkout.invoiceTitle') }}</h3>
          <div class="invoice-type-toggle">
            <button
              class="invoice-type-btn"
              :class="{ active: invoiceType === 'personal' }"
              @click="invoiceType = 'personal'"
            >{{ $t('userSettings.checkout.invoicePersonal') }}</button>
            <button
              class="invoice-type-btn"
              :class="{ active: invoiceType === 'company' }"
              @click="invoiceType = 'company'"
            >{{ $t('userSettings.checkout.invoiceCompany') }}</button>
          </div>

          <template v-if="invoiceType === 'personal'">
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.carrierLabel') }}</label>
              <input v-model="carrierNum" type="text" :placeholder="$t('userSettings.checkout.carrierPlaceholder')" class="form-input" />
              <span class="form-hint">{{ $t('userSettings.checkout.carrierHint') }}</span>
            </div>
          </template>

          <template v-else>
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.companyTaxId') }}</label>
              <input v-model="companyTaxId" type="text" :placeholder="$t('userSettings.checkout.companyTaxIdPlaceholder')" class="form-input" maxlength="8" />
            </div>
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.companyName') }}</label>
              <input v-model="companyName" type="text" :placeholder="$t('userSettings.checkout.companyNamePlaceholder')" class="form-input" />
            </div>
          </template>

          <label class="save-label">
            <input v-model="saveInvoice" type="checkbox" />
            {{ $t('userSettings.checkout.saveInvoice') }}
          </label>
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
          {{ isAddon ? $t('userSettings.checkout.oneTimeNote') : $t('userSettings.checkout.subscriptionNote') }}
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
import { useAddonLabel } from '../composables/useAddonLabel'
import { tierPrice } from '../constants/pricing'

const { t: $t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const addonLabel = useAddonLabel()

const plan = ref(route.query.plan || 'basic')
const billing = ref(route.query.billing || 'monthly')
const paying = ref(false)
const errorMsg = ref(null)

// 加購模式（route.query.addon = package _id）
const isAddon = computed(() => !!route.query.addon)
const addonId = ref(route.query.addon || null)
const addon = ref(null)       // 套餐明細：{ _id, label, price_twd, type, amount }
const quantity = ref(1)

const invoiceType = ref('personal')
const carrierNum = ref('')
const companyTaxId = ref('')
const companyName = ref('')
const saveInvoice = ref(true)

onMounted(async () => {
  if (isAddon.value) {
    // 加購模式：載入套餐明細，找不到就退回設定頁
    try {
      const pkgs = await authStore.getPackages()
      addon.value = (pkgs || []).find(p => p._id === addonId.value) || null
    } catch (e) {
      addon.value = null
    }
    if (!addon.value) {
      router.push('/settings')
      return
    }
  } else if (plan.value === 'free') {
    router.push('/settings')
    return
  }

  // 預填已儲存的發票資訊
  const info = authStore.user?.invoice_info
  if (info) {
    invoiceType.value = info.type || 'personal'
    carrierNum.value = info.carrier_num || ''
    companyTaxId.value = info.company_tax_id || ''
    companyName.value = info.company_name || ''
  }
})

const planLabel = computed(() => ({ basic: 'Basic', pro: 'Pro' })[plan.value] || plan.value)

// 有效份數：clamp 到 1–99，供總價與送出使用（即使輸入框暫時為空也不會算出 0/NaN）
const effectiveQty = computed(() => {
  const n = parseInt(quantity.value, 10)
  if (isNaN(n) || n < 1) return 1
  return n > 99 ? 99 : n
})

const totalPrice = computed(() => {
  if (isAddon.value) return addon.value ? addon.value.price_twd * effectiveQty.value : 0
  return tierPrice(plan.value, billing.value)
})

function incQty() { quantity.value = Math.min(99, effectiveQty.value + 1) }
function decQty() { quantity.value = Math.max(1, effectiveQty.value - 1) }
function clampQty() { quantity.value = effectiveQty.value }

async function handlePay() {
  paying.value = true
  errorMsg.value = null
  try {
    const invoiceData = {
      invoice_type: invoiceType.value,
      carrier_type: invoiceType.value === 'personal' && carrierNum.value ? '1' : '',
      carrier_num: invoiceType.value === 'personal' ? carrierNum.value : '',
      company_tax_id: invoiceType.value === 'company' ? companyTaxId.value : '',
      company_name: invoiceType.value === 'company' ? companyName.value : '',
      save_invoice: saveInvoice.value,
    }
    const result = isAddon.value
      ? await authStore.purchaseExtraQuota(addonId.value, effectiveQty.value, invoiceData)
      : await authStore.createCheckoutSession(plan.value, billing.value, invoiceData)
    authStore.submitNewebpayForm(result.form)
  } catch (err) {
    errorMsg.value = err.response?.data?.detail || $t('userSettings.checkout.error')
    paying.value = false
  }
}
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

.back-btn:hover { color: var(--main-text); }

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

.summary-plan, .summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
}

.summary-plan { margin-bottom: 4px; }

.summary-label { font-size: 14px; color: var(--main-text-light); }
.summary-value { font-size: 14px; color: var(--main-text); font-weight: 500; }
.plan-name { font-weight: 700; color: var(--main-primary); }

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

/* 份數 stepper */
.qty-row { padding: 8px 0; }

.qty-stepper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.qty-btn {
  width: 28px;
  height: 28px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.4));
  border-radius: 6px;
  background: var(--upload-bg, #fff);
  color: var(--main-text);
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s ease;
}

.qty-btn:hover:not(:disabled) {
  border-color: var(--main-primary);
  color: var(--main-primary);
}

.qty-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.qty-input {
  width: 48px;
  height: 28px;
  text-align: center;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.4));
  border-radius: 6px;
  font-size: 14px;
  color: var(--main-text);
  background: var(--upload-bg, #fff);
  -moz-appearance: textfield;
}

.qty-input::-webkit-outer-spin-button,
.qty-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.qty-input:focus { outline: none; border-color: var(--main-primary); }

/* 發票區塊 */
.invoice-section {
  margin: 20px 0;
  padding: 16px;
  background: var(--color-bg, #f8f9fa);
  border-radius: 8px;
}

.invoice-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--main-text);
  margin: 0 0 12px 0;
}

.invoice-type-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
}

.invoice-type-btn {
  padding: 6px 16px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  background: transparent;
  color: var(--main-text-light);
  transition: all 0.2s ease;
}

.invoice-type-btn.active {
  background: var(--main-primary);
  border-color: var(--main-primary);
  color: white;
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 13px;
  color: var(--main-text-light);
  margin-bottom: 4px;
}

.form-input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 6px;
  font-size: 14px;
  color: var(--main-text);
  background: var(--upload-bg, #fff);
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: var(--main-primary);
}

.form-hint {
  font-size: 11px;
  color: var(--main-text-light);
  margin-top: 3px;
  display: block;
}

.save-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--main-text-light);
  cursor: pointer;
  margin-top: 8px;
}

.pay-btn {
  width: 100%;
  padding: 12px;
  margin-top: 4px;
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

.pay-btn:hover:not(:disabled) { opacity: 0.9; transform: translateY(-1px); }
.pay-btn:disabled { opacity: 0.6; cursor: not-allowed; }

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
  .checkout-container { padding: 16px; }
  .checkout-header h1 { font-size: 1.25rem; }
}
</style>
