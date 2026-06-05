<template>
  <Teleport to="body">
    <div v-if="modelValue" class="billing-overlay" @click="$emit('update:modelValue', false)"></div>
    <div ref="billingPanelRef" class="billing-panel" :class="{ open: modelValue }">
      <div class="billing-panel-header">
        <h2>{{ $t('userSettings.subscription.manageBilling') }}</h2>
        <button class="billing-panel-close" @click="$emit('update:modelValue', false)" :aria-label="$t('common.close')">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="billing-panel-body">

        <!-- 取消訂閱 -->
        <div v-if="authStore.hasActiveSubscription" class="billing-section">
          <h3 class="billing-section-title">{{ $t('userSettings.subscription.currentPlan') }}</h3>
          <div class="billing-plan-row">
            <div class="billing-plan-info">
              <span class="billing-plan-name">{{ currentTierLabel }}</span>
              <span class="billing-plan-cycle">{{ currentCycleLabel }}</span>
            </div>
            <template v-if="authStore.subscription?.cancel_at_period_end">
              <div class="cancel-actions">
                <span class="cancel-scheduled-badge">
                  {{ $t('userSettings.subscription.cancelScheduled', { date: formatDate(authStore.subscription?.current_period_end) }) }}
                </span>
                <button class="reactivate-btn" :disabled="reactivating" @click="handleReactivate">
                  {{ reactivating ? $t('userSettings.processing') : $t('userSettings.subscription.reactivate') }}
                </button>
              </div>
            </template>
            <button
              v-else
              class="cancel-sub-btn"
              :disabled="canceling"
              @click="handleCancel"
            >
              {{ canceling ? $t('userSettings.processing') : $t('userSettings.subscription.cancelSubscription') }}
            </button>
          </div>
        </div>

        <!-- 付款紀錄 -->
        <div class="billing-section">
          <h3 class="billing-section-title">{{ $t('userSettings.subscription.ordersTitle') }}</h3>

          <div v-if="loading && orders.length === 0" class="billing-loading">
            {{ $t('userSettings.subscription.ordersLoading') }}
          </div>

          <div v-else-if="orders.length === 0" class="billing-empty">
            {{ $t('userSettings.subscription.ordersEmpty') }}
          </div>

          <div v-else class="orders-list">
            <div v-for="order in orders" :key="order._id" class="order-row">
              <div class="order-left">
                <span class="order-date">{{ formatDate(order.paid_at || order.created_at) }}</span>
                <span class="order-desc">{{ formatOrderDesc(order) }}</span>
              </div>
              <div class="order-right">
                <span class="order-amount">NT${{ order.amount_twd?.toLocaleString() }}</span>
                <span class="order-status" :class="order.status === 'paid' ? 'status-paid' : 'status-failed'">
                  {{ order.status === 'paid' ? $t('userSettings.subscription.orderStatusPaid') : $t('userSettings.subscription.orderStatusFailed') }}
                </span>
              </div>
            </div>
          </div>

          <button
            v-if="hasMore"
            class="load-more-btn"
            :disabled="loading"
            @click="loadMore"
          >
            {{ loading ? $t('userSettings.subscription.ordersLoading') : $t('userSettings.subscription.ordersLoadMore') }}
          </button>
        </div>

      </div>
    </div>
  </Teleport>

  <!-- 取消確認 Modal -->
  <div v-if="showCancelConfirm" class="modal-overlay" @click.self="showCancelConfirm = false">
    <div class="modal-box">
      <h3 class="modal-title">{{ $t('userSettings.subscription.cancelConfirmTitle') }}</h3>
      <p class="modal-message">{{ $t('userSettings.subscription.cancelConfirmMessage') }}</p>
      <div class="modal-actions">
        <button @click="showCancelConfirm = false" class="btn-cancel">{{ $t('userSettings.cancel') }}</button>
        <button @click="confirmCancel" class="btn-confirm btn-danger" :disabled="canceling">
          {{ canceling ? $t('userSettings.processing') : $t('userSettings.subscription.cancelConfirmBtn') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useFocusTrap } from '../composables/useFocusTrap'
import { useDateFormatter } from '../composables/useDateFormatter'

const { t: $t } = useI18n()
const { formatDate: formatDateTz } = useDateFormatter()
const authStore = useAuthStore()

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'cancelled'])

const billingPanelRef = ref(null)
useFocusTrap(billingPanelRef, toRef(props, 'modelValue'))

const LIMIT = 6
const orders = ref([])
const loading = ref(false)
const hasMore = ref(false)
const skip = ref(0)
const canceling = ref(false)
const reactivating = ref(false)
const showCancelConfirm = ref(false)

const currentTierLabel = computed(() => {
  const tier = authStore.subscription?.tier
  return { basic: 'Basic', pro: 'Pro' }[tier] || tier || ''
})

const currentCycleLabel = computed(() => {
  const cycle = authStore.subscription?.billing_cycle
  return cycle === 'yearly'
    ? $t('userSettings.subscription.orderCycleYearly')
    : $t('userSettings.subscription.orderCycleMonthly')
})

function formatDate(timestamp) {
  if (!timestamp) return ''
  return formatDateTz(timestamp, { month: 'long', day: 'numeric' })
}

function formatOrderDesc(order) {
  const tierLabel = { basic: 'Basic', pro: 'Pro' }[order.tier] || ''
  const cycle = order.billing_cycle === 'yearly'
    ? $t('userSettings.subscription.orderCycleYearly')
    : $t('userSettings.subscription.orderCycleMonthly')

  if (order.type === 'extra_quota') {
    const parts = []
    if (order.extra_duration_minutes > 0)
      parts.push($t('userSettings.subscription.orderExtraDuration', { n: order.extra_duration_minutes }))
    if (order.extra_ai_summaries > 0)
      parts.push($t('userSettings.subscription.orderExtraAi', { n: order.extra_ai_summaries }))
    return $t('userSettings.subscription.orderTypeExtraQuota', { items: parts.join('、') })
  }
  if (order.type === 'upgrade_subscription')
    return $t('userSettings.subscription.orderTypeUpgrade', { tier: tierLabel, cycle })
  if (order.type === 'downgrade_subscription')
    return $t('userSettings.subscription.orderTypeDowngrade', { tier: tierLabel, cycle })
  return $t('userSettings.subscription.orderTypeSubscription', { tier: tierLabel, cycle })
}

async function fetchOrders(reset = false) {
  if (loading.value) return
  loading.value = true
  try {
    const currentSkip = reset ? 0 : skip.value
    const data = await authStore.getOrders(currentSkip, LIMIT)
    if (reset) {
      orders.value = data.orders
    } else {
      orders.value.push(...data.orders)
    }
    hasMore.value = data.has_more
    skip.value = currentSkip + data.orders.length
  } catch {
    // silent
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  await fetchOrders(false)
}

function handleCancel() {
  showCancelConfirm.value = true
}

async function handleReactivate() {
  reactivating.value = true
  try {
    const result = await authStore.reactivateSubscription()
    if (result?.form) {
      authStore.submitNewebpayForm(result.form)
    } else {
      emit('cancelled') // reuse event to trigger parent toast
    }
  } catch {
    // silent
  } finally {
    reactivating.value = false
  }
}

async function confirmCancel() {
  canceling.value = true
  try {
    await authStore.cancelSubscription()
    showCancelConfirm.value = false
    emit('cancelled')
  } catch (e) {
    // parent handles toast
  } finally {
    canceling.value = false
  }
}

// 開啟時載入紀錄
watch(() => props.modelValue, (open) => {
  if (open) {
    skip.value = 0
    fetchOrders(true)
  }
})
</script>

<style scoped>
.billing-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 1000;
}

.billing-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 480px;
  max-width: 100vw;
  background: var(--upload-bg, #fff);
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.15);
  z-index: 1001;
  transform: translateX(100%);
  transition: transform 0.3s ease;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.billing-panel.open {
  transform: translateX(0);
}

.billing-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24px 24px 0;
  flex-shrink: 0;
}

.billing-panel-header h2 {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0;
}

.billing-panel-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--main-text-light);
  padding: 4px;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.billing-panel-close:hover {
  background: rgba(163, 177, 198, 0.15);
  color: var(--main-text);
}

.billing-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.billing-section-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--main-text-light);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0 0 14px 0;
}

/* 目前方案 */
.billing-plan-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.billing-plan-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.billing-plan-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--main-text);
}

.billing-plan-cycle {
  font-size: 13px;
  color: var(--main-text-light);
}

.cancel-sub-btn {
  padding: 7px 14px;
  border: 1px solid var(--color-danger, #dc3545);
  border-radius: 6px;
  background: transparent;
  color: var(--color-danger, #dc3545);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  flex-shrink: 0;
}

.cancel-sub-btn:hover:not(:disabled) {
  background: var(--color-danger, #dc3545);
  color: white;
}

.cancel-sub-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cancel-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.cancel-scheduled-badge {
  font-size: 12px;
  color: var(--main-text-light);
  text-align: right;
}

.reactivate-btn {
  padding: 5px 12px;
  border: 1px solid var(--main-primary);
  border-radius: 6px;
  background: transparent;
  color: var(--main-primary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.reactivate-btn:hover:not(:disabled) {
  background: var(--main-primary);
  color: white;
}

.reactivate-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 付款紀錄 */
.billing-loading,
.billing-empty {
  font-size: 14px;
  color: var(--main-text-light);
  padding: 4px 0;
}

.orders-list {
  display: flex;
  flex-direction: column;
}

.order-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 0;
  border-bottom: 1px solid var(--color-divider, rgba(163, 177, 198, 0.12));
}

.order-row:last-child {
  border-bottom: none;
}

.order-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.order-date {
  font-size: 12px;
  color: var(--main-text-light);
}

.order-desc {
  font-size: 14px;
  color: var(--main-text);
}

.order-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.order-amount {
  font-size: 14px;
  font-weight: 600;
  color: var(--main-text);
}

.order-status {
  font-size: 12px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 4px;
}

.status-paid {
  background: rgba(40, 167, 69, 0.1);
  color: var(--color-success, #28a745);
}

.status-failed {
  background: rgba(220, 53, 69, 0.1);
  color: var(--color-danger, #dc3545);
}

.load-more-btn {
  margin-top: 12px;
  padding: 7px 0;
  background: transparent;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 6px;
  font-size: 13px;
  color: var(--main-text-light);
  cursor: pointer;
  width: 100%;
  transition: all 0.2s ease;
}

.load-more-btn:hover:not(:disabled) {
  border-color: var(--main-text-light);
  color: var(--main-text);
}

.load-more-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Cancel confirm modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.modal-box {
  background: var(--upload-bg, #fff);
  border-radius: 12px;
  padding: 28px;
  max-width: 420px;
  width: 100%;
}

.modal-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0 0 10px 0;
}

.modal-message {
  font-size: 14px;
  color: var(--main-text-light);
  margin: 0 0 20px 0;
  line-height: 1.5;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.btn-cancel {
  padding: 8px 18px;
  background: transparent;
  border: 1px solid var(--color-divider, rgba(163, 177, 198, 0.3));
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  color: var(--main-text);
}

.btn-confirm {
  padding: 8px 18px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.btn-danger {
  background: var(--color-danger, #dc3545);
  color: white;
}

.btn-danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .billing-panel {
    width: 100vw;
  }
}
</style>
