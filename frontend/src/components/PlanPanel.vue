<template>
  <Teleport to="body">
    <!-- Overlay -->
    <div v-if="modelValue" class="plan-overlay" @click="$emit('update:modelValue', false)"></div>
    <!-- Panel -->
    <div ref="panelRef" class="plan-panel" :class="{ open: modelValue }">
      <div class="plan-panel-header">
        <h2>{{ $t('userSettings.planPanel.title') }}</h2>
        <button class="plan-panel-close" @click="$emit('update:modelValue', false)" :aria-label="$t('common.close')">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <!-- Monthly / Yearly toggle -->
      <div class="billing-toggle">
        <button
          class="billing-btn"
          :class="{ active: billing === 'monthly' }"
          @click="billing = 'monthly'"
        >
          {{ $t('userSettings.planPanel.monthly') }}
        </button>
        <button
          class="billing-btn"
          :class="{ active: billing === 'yearly' }"
          @click="billing = 'yearly'"
        >
          {{ $t('userSettings.planPanel.yearly') }}
          <span class="yearly-badge">{{ $t('userSettings.planPanel.yearlyDiscount') }}</span>
        </button>
      </div>

      <!-- Plans -->
      <div class="plans-grid">
        <div
          v-for="plan in plans"
          :key="plan.key"
          class="plan-card"
          :class="{ current: currentTier === plan.key }"
        >
          <div class="plan-card-header">
            <h3>{{ $t('userSettings.planPanel.' + plan.key) }}</h3>
            <div class="plan-price">
              <span class="price-amount">{{ getPrice(plan) }}</span>
              <span class="price-period">{{ billing === 'yearly' ? $t('userSettings.planPanel.perMonthYearly') : $t('userSettings.planPanel.perMonth') }}</span>
            </div>
          </div>

          <button
            v-if="currentTier !== plan.key"
            class="plan-select-btn"
            :class="{ 'upgrade-btn': isUpgrade(plan.key), 'downgrade-btn': isDowngrade(plan.key) }"
            :disabled="changingPlan"
            @click="selectPlan(plan.key)"
          >
            {{ getButtonLabel(plan.key) }}
          </button>
          <div v-else class="plan-current-badge">
            {{ $t('userSettings.planPanel.currentPlan') }}
          </div>

          <div class="plan-features">
            <!-- Quota items -->
            <div class="feature-item">
              <svg class="feature-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <span>{{ plan.duration >= 999999
                ? $t('userSettings.planPanel.unlimitedDuration')
                : $t('userSettings.planPanel.durationMinutes', { n: plan.duration }) }}</span>
            </div>
            <div class="feature-item">
              <svg class="feature-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <span>{{ plan.aiSummaries >= 999999
                ? $t('userSettings.planPanel.unlimitedAiSummaries')
                : $t('userSettings.planPanel.aiSummaries', { n: plan.aiSummaries }) }}</span>
            </div>
            <div class="feature-item">
              <svg class="feature-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <span>{{ $t('userSettings.planPanel.audioRetention', { n: plan.audioRetention }) }}</span>
            </div>
            <div class="feature-item" :class="{ disabled: plan.keepAudio === 0 }">
              <svg v-if="plan.keepAudio > 0" class="feature-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <svg v-else class="feature-icon disabled" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              <span>{{ plan.keepAudio >= 999999
                ? $t('userSettings.planPanel.unlimitedKeepAudio')
                : plan.keepAudio === 0
                  ? $t('userSettings.planPanel.keepAudioFiles')
                  : $t('userSettings.planPanel.keepAudio', { n: plan.keepAudio }) }}</span>
            </div>

            <!-- Feature flags -->
            <div class="feature-item" :class="{ disabled: !plan.features.speaker_diarization }">
              <svg v-if="plan.features.speaker_diarization" class="feature-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <svg v-else class="feature-icon disabled" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              <span>{{ $t('userSettings.planPanel.speakerDiarization') }}</span>
            </div>
            <div class="feature-item" :class="{ disabled: !plan.features.batch_operations }">
              <svg v-if="plan.features.batch_operations" class="feature-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
              <svg v-else class="feature-icon disabled" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              <span>{{ $t('userSettings.planPanel.batchOperations') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 加購額度（basic / pro 用戶才顯示；一次性購買、跨月保留）-->
      <div v-if="currentTier !== 'free' && addons.length" class="addons-section">
        <h3 class="addons-title">{{ $t('userSettings.planPanel.addonsTitle') }}</h3>
        <p class="addons-subtitle">{{ $t('userSettings.planPanel.addonsSubtitle') }}</p>
        <div class="addons-grid">
          <div v-for="addon in addons" :key="addon._id" class="addon-card">
            <div class="addon-info">
              <span class="addon-label">{{ addonLabel(addon) }}</span>
              <span class="addon-price">NT${{ addon.price_twd }}</span>
            </div>
            <button class="addon-buy-btn" @click="buyAddon(addon)">
              {{ $t('userSettings.planPanel.buyAddon') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, toRef, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useFocusTrap } from '../composables/useFocusTrap'
import { useAddonLabel } from '../composables/useAddonLabel'
import { TIER_PRICES } from '../constants/pricing'

const { t: $t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const addonLabel = useAddonLabel()

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  currentTier: { type: String, default: 'free' }
})

const emit = defineEmits(['update:modelValue', 'planChanged'])

const panelRef = ref(null)
useFocusTrap(panelRef, toRef(props, 'modelValue'))

const changingPlan = ref(false)
const tierOrder = { free: 0, basic: 1, pro: 2 }

// 加購額度套餐（一次性購買）— basic/pro 用戶開啟面板時才載入
const addons = ref([])

async function loadAddons() {
  if (props.currentTier === 'free' || addons.value.length) return
  try {
    addons.value = (await authStore.getPackages()) || []
  } catch (e) {
    addons.value = []  // 載入失敗不影響方案瀏覽
  }
}

watch(() => props.modelValue, (open) => {
  if (open) {
    loadPlans()
    loadAddons()
  }
})

function buyAddon(addon) {
  emit('update:modelValue', false)
  router.push({ path: '/checkout', query: { addon: addon._id } })
}

function isUpgrade(planKey) {
  return tierOrder[planKey] > tierOrder[props.currentTier]
}

function isDowngrade(planKey) {
  return tierOrder[planKey] < tierOrder[props.currentTier]
}

function getButtonLabel(planKey) {
  if (changingPlan.value) return $t('userSettings.planPanel.processing')
  if (props.currentTier === 'free') return $t('userSettings.planPanel.selectPlan')
  if (isUpgrade(planKey)) return $t('userSettings.planPanel.upgrade')
  if (isDowngrade(planKey)) {
    return planKey === 'free'
      ? $t('userSettings.planPanel.cancelSubscription')
      : $t('userSettings.planPanel.downgrade')
  }
  return $t('userSettings.planPanel.selectPlan')
}

async function selectPlan(planKey) {
  if (props.currentTier === 'free') {
    if (planKey === 'free') return
    emit('update:modelValue', false)
    router.push({ path: '/checkout', query: { plan: planKey, billing: billing.value } })
    return
  }

  if (planKey === 'free') {
    emit('update:modelValue', false)
    emit('planChanged', { action: 'cancel' })
    return
  }

  changingPlan.value = true
  try {
    const result = await authStore.changePlan(planKey, billing.value)

    if (result.form) {
      // 升級或降級需要付款：auto-submit 到藍新
      emit('update:modelValue', false)
      if (result.action === 'upgrade' && (result.extra_duration_minutes > 0 || result.extra_ai_summaries > 0)) {
        const durMsg = result.extra_duration_minutes > 0 ? $t('userSettings.planPanel.extraMinutes', { n: result.extra_duration_minutes }) : ''
        const aiMsg = result.extra_ai_summaries > 0 ? $t('userSettings.planPanel.extraAiSummaries', { n: result.extra_ai_summaries }) : ''
        const parts = [durMsg, aiMsg].filter(Boolean).join($t('common.listSeparator'))
        alert($t('userSettings.planPanel.upgradeKeepQuota', { parts }))
      }
      if (result.action === 'downgrade') {
        const msg = result.effective === 'end_of_period'
          ? $t('userSettings.planPanel.downgradeScheduled', { date: result.scheduled_date, plan: planKey })
          : $t('userSettings.planPanel.downgradeImmediate')
        if (!confirm(msg)) {
          changingPlan.value = false
          return
        }
      }
      authStore.submitNewebpayForm(result.form)
    }
  } catch (err) {
    const detail = err.response?.data?.detail || $t('userSettings.planPanel.changeFailed')
    alert(detail)
  } finally {
    changingPlan.value = false
  }
}

const billing = ref('monthly')

// 方案定義（額度 + features）的唯一真實來源在後端 QUOTA_TIERS，透過 /subscriptions/tiers 下發。
// 價格仍由前端 pricing.js 提供（綁金流設定，見該檔註解）。
const plans = ref([])

async function loadPlans() {
  if (plans.value.length) return
  try {
    plans.value = (await authStore.getTiers()) || []
  } catch (e) {
    plans.value = []  // 載入失敗不影響面板開啟；不 hardcode fallback 以維持單一來源
  }
}

onMounted(loadPlans)

function getPrice(plan) {
  const prices = TIER_PRICES[plan.key] || { monthly: 0, yearly: 0 }
  if (billing.value === 'yearly') {
    return prices.yearly > 0
      ? `NT$${Math.round(prices.yearly / 12)}`
      : 'NT$0'
  }
  return prices.monthly > 0 ? `NT$${prices.monthly}` : 'NT$0'
}
</script>

<style scoped>
.plan-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 1000;
}

.plan-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 720px;
  max-width: 100vw;
  background: var(--upload-bg, #fff);
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.15);
  z-index: 1001;
  transform: translateX(100%);
  transition: transform 0.3s ease;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.plan-panel.open {
  transform: translateX(0);
}

.plan-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 28px 0;
}

.plan-panel-header h2 {
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0;
}

.plan-panel-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--main-text-light);
  padding: 4px;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.plan-panel-close:hover {
  background: rgba(163, 177, 198, 0.15);
  color: var(--main-text);
}

/* Billing toggle */
.billing-toggle {
  display: flex;
  gap: 4px;
  padding: 4px;
  margin: 20px 28px 24px;
  background: var(--color-bg, #f5f5f5);
  border-radius: 10px;
  width: fit-content;
}

.billing-btn {
  padding: 8px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  background: transparent;
  color: var(--main-text-light);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}

.billing-btn.active {
  background: var(--upload-bg, #fff);
  color: var(--main-text);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.yearly-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-success, #28a745);
  background: rgba(40, 167, 69, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
}

/* Plans grid */
.plans-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 0 28px 28px;
  flex: 1;
}

.plan-card {
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  transition: all 0.2s ease;
}

.plan-card.current {
  border-color: var(--main-primary);
  box-shadow: 0 0 0 1px var(--main-primary);
}

.plan-card-header {
  margin-bottom: 16px;
}

.plan-card-header h3 {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0 0 8px 0;
}

.plan-price {
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.price-amount {
  font-size: 1.75rem;
  font-weight: 800;
  color: var(--main-text);
}

.price-period {
  font-size: 0.85rem;
  color: var(--main-text-light);
  font-weight: 500;
}

/* Select button */
.plan-select-btn {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  background: transparent;
  color: var(--main-text);
  transition: all 0.2s ease;
  margin-bottom: 16px;
}

.plan-select-btn:hover:not(:disabled) {
  background: var(--main-primary);
  border-color: var(--main-primary);
  color: white;
}

.plan-select-btn.upgrade-btn {
  background: var(--main-primary);
  border-color: var(--main-primary);
  color: white;
}

.plan-select-btn.upgrade-btn:hover:not(:disabled) {
  opacity: 0.9;
}

.plan-select-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.plan-current-badge {
  width: 100%;
  padding: 10px;
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--main-text-light);
  margin-bottom: 16px;
}

/* Features */
.plan-features {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 0.82rem;
  color: var(--main-text);
  line-height: 1.3;
}

.feature-item.disabled {
  color: var(--main-text-light);
  opacity: 0.5;
}

.feature-icon {
  flex-shrink: 0;
  margin-top: 1px;
  color: var(--color-success, #28a745);
}

.feature-icon.disabled {
  color: var(--main-text-light);
}

/* 加購額度區 */
.addons-section {
  padding: 0 28px 28px;
  margin-top: 4px;
  padding-top: 20px;
}

.addons-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0 0 4px 0;
}

.addons-subtitle {
  font-size: 0.8rem;
  color: var(--main-text-light);
  margin: 0 0 16px 0;
  line-height: 1.4;
}

.addons-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.addon-card {
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.addon-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.addon-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--main-text);
}

.addon-price {
  font-size: 1.4rem;
  font-weight: 800;
  color: var(--main-text);
}

/* 比照 .plan-select-btn（中性框 + 主文字色，hover 填滿主色）*/
.addon-buy-btn {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  background: transparent;
  color: var(--main-text);
  transition: all 0.2s ease;
}

.addon-buy-btn:hover {
  background: var(--main-primary);
  border-color: var(--main-primary);
  color: white;
}

/* Responsive */
@media (max-width: 768px) {
  .plan-panel {
    width: 100vw;
  }

  .addons-section {
    padding: 20px 16px 16px;
  }

  .addons-grid {
    grid-template-columns: 1fr;
  }

  .plans-grid {
    grid-template-columns: 1fr;
    gap: 12px;
    padding: 0 16px 16px;
  }

  .plan-panel-header {
    padding: 16px 16px 0;
  }

  .billing-toggle {
    margin: 16px 16px 20px;
  }
}
</style>
