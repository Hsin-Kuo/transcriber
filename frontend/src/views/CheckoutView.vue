<template>
  <div class="checkout-container">
    <div class="checkout-header">
      <button class="back-btn" @click="$router.push('/settings')">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
        {{ isRecovery ? $t('common.back') : $t('userSettings.checkout.backToPlans') }}
      </button>
      <h1>{{ headerTitle }}</h1>
    </div>

    <div class="checkout-content">
      <div class="summary-card">
        <h2>{{ isRecovery ? $t('userSettings.updateCard.summaryTitle') : $t('userSettings.checkout.orderSummary') }}</h2>

        <!-- 換卡挽回模式：說明 + 補扣金額 -->
        <template v-if="isRecovery">
          <p class="recovery-note">{{ $t('userSettings.updateCard.intro') }}</p>
          <div class="summary-plan">
            <span class="summary-label">{{ $t('userSettings.updateCard.itemLabel') }}</span>
            <span class="summary-value plan-name">{{ $t('userSettings.updateCard.itemValue') }}</span>
          </div>

          <div class="summary-divider"></div>

          <div class="summary-row total">
            <span class="summary-label">{{ $t('userSettings.updateCard.amountLabel') }}</span>
            <span class="summary-value">NT${{ totalPrice }}</span>
          </div>
        </template>

        <!-- 升級模式：升級後方案 + 計費週期 + 額度轉存說明（升級單已於進頁時建立） -->
        <template v-else-if="isUpgrade">
          <div class="summary-plan">
            <span class="summary-label">{{ $t('userSettings.checkout.upgradeItem') }}</span>
            <span class="summary-value plan-name">{{ planLabel }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">{{ $t('userSettings.checkout.billingCycle') }}</span>
            <span class="summary-value">{{ billing === 'yearly' ? $t('userSettings.checkout.yearly') : $t('userSettings.checkout.monthly') }}</span>
          </div>

          <p v-if="hasCarryover" class="carryover-note">
            {{ $t('userSettings.planPanel.upgradeKeepQuota', { parts: carryoverParts.join('、') }) }}
          </p>

          <div class="summary-divider"></div>

          <div class="summary-row total">
            <span class="summary-label">{{ $t('userSettings.checkout.total') }}</span>
            <span class="summary-value">NT${{ totalPrice }}</span>
          </div>
        </template>

        <!-- 加購模式：品項 + 份數 + 單價 -->
        <template v-else-if="isAddon">
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

        <!-- 電子發票：僅在按付款時才建單的模式（新訂閱 / 加購）顯示可編輯發票區。
             換卡挽回、升級的訂單已於進頁時建立，發票沿用已儲存資訊，不重複填寫。 -->
        <div v-if="showInvoice" class="invoice-section">
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

        <!-- 91APP Web SDK 信用卡欄位（tokenize，卡號不經過我方伺服器）。所有需收款的模式共用 -->
        <div class="card-fields">
          <h3 class="invoice-title">{{ $t('userSettings.checkout.payment') }}</h3>
          <div class="form-group">
            <label>{{ $t('userSettings.checkout.cardNumber') }}</label>
            <!-- SDK 會在此容器內注入 iframe -->
            <div id="card-number" class="form-input sdk-field"></div>
          </div>
          <div class="card-fields-row">
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.expiry') }}</label>
              <div id="card-expiration-date" class="form-input sdk-field"></div>
            </div>
            <div class="form-group">
              <label>{{ $t('userSettings.checkout.cvc') }}</label>
              <div id="card-ccv" class="form-input sdk-field"></div>
            </div>
          </div>
        </div>

        <button
          class="pay-btn"
          :disabled="paying || !sdkReady || !cardCanToken"
          @click="handlePay"
        >
          <svg v-if="!paying" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
          {{ paying ? $t('userSettings.checkout.processing') : (isRecovery ? $t('userSettings.updateCard.submit') : $t('userSettings.checkout.pay')) }}
        </button>

        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>

        <p class="secure-note">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
          {{ secureNote }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
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

// 91APP Web SDK 版本；integrity（SRI）尚未取得官方 hash，先不加以免載入失敗。
// TODO: 取得 SDK 3.9.3 的 sha256 SRI hash 後補上 integrity 屬性。
const SDK_URL = 'https://checkout.payments.91app.com/sdk/3.9.3/index.js'

const plan = ref(route.query.plan || 'basic')
const billing = ref(route.query.billing || 'monthly')
const paying = ref(false)
const errorMsg = ref(null)

// 結帳頁一般化 mode：
//   'new'（無 mode）  一般新訂閱：按付款時 createCheckoutSession 建單（/checkout 有 30s 冷卻）
//   'update-card'     換卡挽回（Dunning）：進頁 updateCard() 建 recovery 單，補扣本期款
//   'upgrade'         升級：進頁 changePlan() 建 upgrade 單，回補價金額 + 轉存額度 + SDK 參數
//   'extra'           加購：按付款時 purchaseExtra() 建 extra_quota 單（以帶入份數/發票）
// 四種模式共用同一組 SDK tokenize → /pay → 3D → /payment/return 流程。
const mode = computed(() => route.query.mode || 'new')
const isRecovery = computed(() => mode.value === 'update-card')
const isUpgrade = computed(() => mode.value === 'upgrade')
const isAddon = computed(() => mode.value === 'extra')
// 訂單已於進頁時建立（不在按付款時建）→ 換卡挽回 + 升級。
// 這兩種模式發票沿用已儲存資訊、不提供編輯（訂單此時已成立無法回改）。
const orderPrebuilt = computed(() => isRecovery.value || isUpgrade.value)
const showInvoice = computed(() => !orderPrebuilt.value)

const recoveryAmount = ref(0)

// 升級模式：/change 回傳的補價金額與「轉存為加值額度」的原方案剩餘量
const upgradeAmount = ref(0)
const extraDurationMinutes = ref(0)
const extraAiSummaries = ref(0)

// 加購模式（route.query.package_id = package _id，quantity = 份數）
const addonId = ref(route.query.package_id || null)
const addon = ref(null)       // 套餐明細：{ _id, label, price_twd, type, amount }
const quantity = ref(parseInt(route.query.quantity, 10) > 0 ? parseInt(route.query.quantity, 10) : 1)

const invoiceType = ref('personal')
const carrierNum = ref('')
const companyTaxId = ref('')
const companyName = ref('')
const saveInvoice = ref(true)

// ===== 91APP SDK 狀態 =====
const sdkReady = ref(false)      // setupSDK + card.setup 完成
const cardCanToken = ref(false)  // card 'update' 事件回報可取 token（三欄填妥且有效）
const orderNo = ref(null)        // 建單後的訂單編號
let publishableKey = null        // /checkout 回傳（商戶層，跟 order 無關）
let sdkServerType = 'sandbox'    // 'sandbox' | 'production'
let cardSdk = null               // Payments91APP.card 實例（非響應式）

function buildInvoiceData() {
  return {
    invoice_type: invoiceType.value,
    carrier_type: invoiceType.value === 'personal' && carrierNum.value ? '1' : '',
    carrier_num: invoiceType.value === 'personal' ? carrierNum.value : '',
    company_tax_id: invoiceType.value === 'company' ? companyTaxId.value : '',
    company_name: invoiceType.value === 'company' ? companyName.value : '',
    save_invoice: saveInvoice.value,
  }
}

// 預填表單發票欄位（新訂閱 / 加購：使用者可再編輯）
function prefillInvoice() {
  const info = authStore.user?.invoice_info
  if (!info) return
  invoiceType.value = info.type || 'personal'
  carrierNum.value = info.carrier_num || ''
  companyTaxId.value = info.company_tax_id || ''
  companyName.value = info.company_name || ''
}

// 從已儲存的發票資訊組出送給後端的 invoice payload（升級：進頁建單、不提供編輯）
function savedInvoiceData() {
  const info = authStore.user?.invoice_info
  if (!info) return {}
  const isCompany = info.type === 'company'
  return {
    invoice_type: info.type || 'personal',
    carrier_type: !isCompany && info.carrier_num ? '1' : '',
    carrier_num: !isCompany ? (info.carrier_num || '') : '',
    company_tax_id: isCompany ? (info.company_tax_id || '') : '',
    company_name: isCompany ? (info.company_name || '') : '',
    save_invoice: false,
  }
}

// 動態載入 91APP SDK（若已載入則直接 resolve）
function loadSdk() {
  return new Promise((resolve, reject) => {
    if (window.Payments91APP) return resolve(window.Payments91APP)
    const existing = document.querySelector('script[data-sdk="91app"]')
    if (existing) {
      existing.addEventListener('load', () => resolve(window.Payments91APP))
      existing.addEventListener('error', () => reject(new Error('SDK load failed')))
      return
    }
    const s = document.createElement('script')
    s.src = SDK_URL
    s.async = true
    s.dataset.sdk = '91app'
    // TODO: 補 s.integrity + s.crossOrigin 一旦取得官方 SRI hash
    s.onload = () => resolve(window.Payments91APP)
    s.onerror = () => reject(new Error('SDK load failed'))
    document.head.appendChild(s)
  })
}

// setupSDK + card.setup（三個容器需已 render）
function setupCard() {
  const Payments91APP = window.Payments91APP
  if (!Payments91APP) throw new Error('SDK not available')
  Payments91APP.setupSDK(publishableKey, sdkServerType)
  cardSdk = Payments91APP.card
  cardSdk.setup({
    enableIcon: false,
    fields: {
      number:         { element: '#card-number',          placeholder: $t('userSettings.checkout.cardNumberPlaceholder') },
      expirationDate: { element: '#card-expiration-date', placeholder: $t('userSettings.checkout.expiryPlaceholder') },
      ccv:            { element: '#card-ccv',              placeholder: $t('userSettings.checkout.cvcPlaceholder') },
    },
    styles: {
      normal:  { color: 'black' },
      focus:   { color: 'blue' },
      error:   { color: 'red' },
      success: { color: 'green' },
    },
  })
  // SDK 3.4.0+：canGetToken 為 true 才可取 token
  cardSdk.on('update', (s) => { cardCanToken.value = !!s?.canGetToken })
  sdkReady.value = true
}

onMounted(async () => {
  if (isRecovery.value) {
    // 換卡挽回：建 recovery 單，取 SDK 參數 + 補扣金額，然後 setupSDK 讓使用者填卡。
    // 建單在此一次完成（update-card 由後端保證 past_due 才建，非冷卻型 checkout）。
    try {
      const rec = await authStore.updateCard()
      orderNo.value = rec.order_no
      recoveryAmount.value = rec.amount
      publishableKey = rec.publishable_key
      sdkServerType = rec.sdk_server_type || 'sandbox'
      await loadSdk()
      await nextTick()   // 確保三個 card 容器已 render
      setupCard()
    } catch (err) {
      errorMsg.value = resolveErr(err)
    }
    return
  }

  if (isUpgrade.value) {
    // 升級：進頁即呼叫 /change 建 upgrade 單，取回補價金額、轉存額度與 SDK 參數。
    // 發票沿用已儲存資訊（單已於此建立，故不提供編輯，與換卡挽回一致）。
    plan.value = route.query.plan || 'pro'
    billing.value = route.query.billing || 'monthly'
    try {
      const res = await authStore.changePlan(plan.value, billing.value, savedInvoiceData())
      // 目標 tier 非高於現有 → 後端會回 downgrade（不扣款）或 400；此頁只處理升級收款，
      // 其餘情況導回設定頁，避免在收款頁誤觸發降級/同級。
      if (res.action !== 'upgrade' || !res.order_no) {
        router.push('/settings')
        return
      }
      orderNo.value = res.order_no
      upgradeAmount.value = res.amount
      extraDurationMinutes.value = res.extra_duration_minutes || 0
      extraAiSummaries.value = res.extra_ai_summaries || 0
      publishableKey = res.publishable_key
      sdkServerType = res.sdk_server_type || 'sandbox'
      await loadSdk()
      await nextTick()
      setupCard()
    } catch (err) {
      errorMsg.value = resolveErr(err)
    }
    return
  }

  if (isAddon.value) {
    // 加購：載入套餐明細供顯示（找不到就退回設定頁）。
    // 建單延到按付款時（purchaseExtra），以帶入使用者調整後的份數與發票資訊。
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
    prefillInvoice()
    // SDK 參數用 payment-config（商戶層，不建單）
    try {
      const cfg = await authStore.getPaymentConfig()
      publishableKey = cfg.publishable_key
      sdkServerType = cfg.sdk_server_type || 'sandbox'
      await loadSdk()
      await nextTick()
      setupCard()
    } catch (err) {
      errorMsg.value = resolveErr(err)
    }
    return
  }

  if (plan.value === 'free') {
    router.push('/settings')
    return
  }

  // 預填已儲存的發票資訊
  prefillInvoice()

  // 訂閱模式：先取 SDK 參數（不建單）setupSDK 讓使用者填卡；
  // 建單延到按付款時一次完成（/checkout 有 30s 建單冷卻，onMounted 建單會導致付款時 429）。
  try {
    const cfg = await authStore.getPaymentConfig()
    publishableKey = cfg.publishable_key
    sdkServerType = cfg.sdk_server_type || 'sandbox'
    await loadSdk()
    await nextTick()   // 確保三個 card 容器已 render
    setupCard()
  } catch (err) {
    errorMsg.value = resolveErr(err)
  }
})

function resolveErr(err) {
  const detail = err?.response?.data?.detail
  return (typeof detail === 'string' ? detail : detail?.message) || $t('userSettings.checkout.error')
}

const planLabel = computed(() => ({ basic: 'Basic', pro: 'Pro' })[plan.value] || plan.value)

// 頁首標題：換卡挽回 / 升級 / 一般結帳
const headerTitle = computed(() => {
  if (isRecovery.value) return $t('userSettings.updateCard.title')
  if (isUpgrade.value) return $t('userSettings.checkout.upgradeTitle')
  return $t('userSettings.checkout.title')
})

// 升級「原方案剩餘額度轉為加值額度」的顯示片段（分鐘 / AI 摘要）
const carryoverParts = computed(() => {
  const parts = []
  if (extraDurationMinutes.value > 0)
    parts.push($t('userSettings.planPanel.extraMinutes', { n: extraDurationMinutes.value }))
  if (extraAiSummaries.value > 0)
    parts.push($t('userSettings.planPanel.extraAiSummaries', { n: extraAiSummaries.value }))
  return parts
})
const hasCarryover = computed(() => carryoverParts.value.length > 0)

// 安全/扣款揭露文案：加購=一次性；升級/月繳=每月自動扣款；年繳=一次性、到期不自動續訂
const secureNote = computed(() => {
  if (isRecovery.value) return $t('userSettings.updateCard.secureNote')
  if (isAddon.value) return $t('userSettings.checkout.oneTimeNote')
  if (billing.value === 'yearly') return $t('userSettings.checkout.subscriptionNoteYearly')
  return $t('userSettings.checkout.subscriptionNote')
})

// 有效份數：clamp 到 1–99，供總價與送出使用（即使輸入框暫時為空也不會算出 0/NaN）
const effectiveQty = computed(() => {
  const n = parseInt(quantity.value, 10)
  if (isNaN(n) || n < 1) return 1
  return n > 99 ? 99 : n
})

const totalPrice = computed(() => {
  if (isRecovery.value) return recoveryAmount.value
  if (isUpgrade.value) return upgradeAmount.value
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
    // (a) 取 txn token（卡號等敏感資料由 SDK iframe 直送 91APP，不經過我方）
    const res = await cardSdk.getTxnToken()
    if (!res || !res.txnToken) throw new Error('txn_token_failed')

    // (b) 建單：換卡挽回 / 升級的訂單已在 onMounted 建好（orderPrebuilt），直接沿用 orderNo。
    //     新訂閱 → createCheckoutSession；加購 → purchaseExtra（於此帶入份數與發票）。
    if (!orderPrebuilt.value) {
      if (isAddon.value) {
        const s = await authStore.purchaseExtraQuota(addonId.value, effectiveQty.value, buildInvoiceData())
        orderNo.value = s.order_no
      } else {
        const session = await authStore.createCheckoutSession(plan.value, billing.value, buildInvoiceData())
        orderNo.value = session.order_no
      }
    }

    // (c) 發動扣款（重用既有 /pay）
    const pay = await authStore.payOrder(orderNo.value, res.txnToken)

    // (d) 需 3D → 導去 payment_url；否則直接成功導回 return 頁
    if (pay.payment_url) {
      window.location.href = pay.payment_url
      return
    }
    if (pay.status === 'success') {
      // 帶模式旗標讓 return 頁顯示對應文案：recovered=換卡恢復；extra=加購入帳
      const query = { order_no: orderNo.value }
      if (isRecovery.value) query.recovered = '1'
      if (isAddon.value) query.extra = '1'
      router.push({ path: '/payment/return', query })
      return
    }
    throw new Error('unexpected_pay_response')
  } catch (err) {
    errorMsg.value = resolveErr(err)
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

/* 91APP SDK 信用卡欄位 */
.card-fields {
  margin: 20px 0;
}

.card-fields-row {
  display: flex;
  gap: 12px;
}

.card-fields-row .form-group {
  flex: 1;
}

/* SDK 在容器內注入 iframe；給固定高度讓 iframe 有版面 */
.sdk-field {
  min-height: 40px;
  display: flex;
  align-items: center;
  padding: 0 10px;
}

/* 換卡挽回說明 */
.recovery-note {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--main-text-light);
  line-height: 1.5;
}

/* 升級「額度轉存為加值額度」說明 */
.carryover-note {
  margin: 8px 0 0;
  padding: 10px 12px;
  background: var(--color-bg, #f8f9fa);
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--main-text-light);
  line-height: 1.5;
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
