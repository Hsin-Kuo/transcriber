<script setup>
/**
 * ShareDialog — 公開分享連結管理對話框。
 *
 * 完全自包含：UI + state + API calls，parent 只需傳 taskId 與初始
 * share 狀態，並用 v-model:show 控制可見性。
 *
 * 對應後端：src/routers/shared.py
 * - POST /shared/{task_id}/toggle?expires_in_days=N
 * - PATCH /shared/{task_id}/expiry?expires_in_days=N
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import { NEW_ENDPOINTS } from '../../api/endpoints'
import { useFocusTrap } from '../../composables/useFocusTrap'

const props = defineProps({
  taskId: { type: String, required: true },
  /** 從 task 載入時帶入的初始 share token；後續以本元件內部 state 為準 */
  initialShareToken: { type: String, default: null },
  /** unix seconds；null = 永久 */
  initialShareExpiresAt: { type: Number, default: null },
})

const show = defineModel('show', { type: Boolean, default: false })

const { t } = useI18n()

const dialogRef = ref(null)
useFocusTrap(dialogRef, show)

// 內部 state：用 props 初值，後續 enable/disable/update_expiry 自行維護
const shareToken = ref(props.initialShareToken)
const shareExpiresAt = ref(props.initialShareExpiresAt)
const shareExpiryDays = ref(0) // 開啟前選的天數；0 = 永久
const shareLoading = ref(false)
const shareLinkCopied = ref(false)

// 切換到新 task 時重置內部 state（dialog 被重用於不同任務時）
watch(
  () => props.taskId,
  () => {
    shareToken.value = props.initialShareToken
    shareExpiresAt.value = props.initialShareExpiresAt
    shareExpiryDays.value = 0
    shareLinkCopied.value = false
  },
)

const origin = window.location.origin

const shareExpiryText = computed(() => {
  if (!shareExpiresAt.value) return t('shared.expiryNever')
  return new Date(shareExpiresAt.value * 1000).toLocaleString()
})

async function toggleShare() {
  shareLoading.value = true
  try {
    const url = NEW_ENDPOINTS.shared.toggle(props.taskId)
    // 已開啟 → toggle off 不帶 expires；首次開啟才帶 expires_in_days
    const params = shareToken.value || !shareExpiryDays.value
      ? {}
      : { expires_in_days: shareExpiryDays.value }
    const response = await api.post(url, null, { params })
    if (response.data.shared) {
      shareToken.value = response.data.share_token
      shareExpiresAt.value = response.data.expires_at
    } else {
      shareToken.value = null
      shareExpiresAt.value = null
      show.value = false
    }
  } catch (error) {
    const detail = error.response?.data?.detail
    alert(detail || t('shared.paidOnly'))
    if (error.response?.status === 403) {
      show.value = false
    }
  } finally {
    shareLoading.value = false
  }
}

async function updateShareExpiry(days) {
  // days = 0 → 改為永久；> 0 → 從現在起 N 天後過期
  shareLoading.value = true
  try {
    const url = NEW_ENDPOINTS.shared.expiry(props.taskId)
    const params = days ? { expires_in_days: days } : {}
    const response = await api.patch(url, null, { params })
    shareExpiresAt.value = response.data.expires_at
  } catch (error) {
    alert(error.response?.data?.detail || 'update failed')
  } finally {
    shareLoading.value = false
  }
}

function copyShareLink() {
  if (!shareToken.value) return
  const url = `${origin}/s/${shareToken.value}`
  navigator.clipboard.writeText(url).then(() => {
    shareLinkCopied.value = true
    setTimeout(() => { shareLinkCopied.value = false }, 2000)
  })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="share-overlay" @click.self="show = false">
      <div ref="dialogRef" class="share-dialog" role="dialog" aria-modal="true" :aria-label="t('shared.shareTitle')">
        <div class="share-header">
          <h3>{{ t('shared.shareTitle') }}</h3>
          <button class="share-close-btn" @click="show = false" :aria-label="t('common.close')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <div class="share-body">
          <p class="share-desc">{{ t('shared.shareDesc') }}</p>

          <div v-if="shareToken" class="share-link-section">
            <div class="share-link-row">
              <input
                type="text"
                :value="`${origin}/s/${shareToken}`"
                readonly
                class="share-link-input"
                :aria-label="t('shared.shareLink')"
                @click="$event.target.select()"
              />
              <button class="share-copy-btn" @click="copyShareLink">
                {{ shareLinkCopied ? t('shared.linkCopied') : t('shared.copyLink') }}
              </button>
            </div>

            <div class="share-expiry-card">
              <div class="share-expiry-info">
                <span class="share-expiry-label">{{ t('shared.expiryLabel') }}：</span>
                <span class="share-expiry-value">{{ shareExpiryText }}</span>
              </div>
              <div class="share-select-wrap">
                <select
                  class="share-expiry-select"
                  :disabled="shareLoading"
                  :value="shareExpiresAt ? -1 : 0"
                  @change="updateShareExpiry(Number($event.target.value))"
                >
                  <option v-if="shareExpiresAt" :value="-1" disabled hidden>{{ t('shared.changeExpiry') }}</option>
                  <option :value="0">{{ t('shared.expiryNever') }}</option>
                  <option :value="7">{{ t('shared.expiry7d') }}</option>
                  <option :value="30">{{ t('shared.expiry30d') }}</option>
                  <option :value="90">{{ t('shared.expiry90d') }}</option>
                </select>
                <svg class="share-select-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </div>
            </div>
          </div>

          <div v-else class="share-enable-section">
            <div class="share-expiry-card">
              <div class="share-expiry-info">
                <label class="share-expiry-label">{{ t('shared.expiryLabel') }}</label>
              </div>
              <div class="share-select-wrap">
                <select
                  v-model.number="shareExpiryDays"
                  class="share-expiry-select"
                  :disabled="shareLoading"
                >
                  <option :value="0">{{ t('shared.expiryNever') }}</option>
                  <option :value="7">{{ t('shared.expiry7d') }}</option>
                  <option :value="30">{{ t('shared.expiry30d') }}</option>
                  <option :value="90">{{ t('shared.expiry90d') }}</option>
                </select>
                <svg class="share-select-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
              </div>
            </div>
          </div>
        </div>

        <div class="share-footer">
          <button
            v-if="shareToken"
            class="share-disable-btn"
            :disabled="shareLoading"
            @click="toggleShare"
          >
            {{ t('shared.disableShare') }}
          </button>
          <button
            v-else
            class="share-enable-btn"
            :disabled="shareLoading"
            @click="toggleShare"
          >
            {{ shareLoading ? '...' : t('shared.enableShare') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.share-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: shareFadeIn 0.2s ease;
}

@keyframes shareFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.share-dialog {
  background: var(--main-bg);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  width: 460px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: shareSlideUp 0.3s ease;
}

@keyframes shareSlideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

/* Header */
.share-header {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(160, 145, 124, 0.2);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.share-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--main-text);
}

.share-close-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 8px;
  border-radius: 8px;
  color: var(--main-text-light);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.share-close-btn:hover {
  background: rgba(160, 145, 124, 0.15);
  color: var(--main-text);
}

/* Body */
.share-body {
  padding: 20px 24px 4px;
}

.share-desc {
  color: var(--main-text-light);
  font-size: 13px;
  line-height: 1.5;
  margin: 0 0 18px 0;
}

.share-link-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Link row */
.share-link-row {
  display: flex;
  gap: 8px;
}

.share-link-input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid rgba(160, 145, 124, 0.3);
  border-radius: 10px;
  font-size: 13px;
  color: var(--main-text);
  background: rgba(160, 145, 124, 0.08);
  outline: none;
  transition: all 0.2s ease;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.share-link-input:focus {
  border-color: var(--main-primary);
  background: var(--main-bg);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.12);
}

.share-copy-btn {
  padding: 10px 18px;
  background: var(--main-primary-dark);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.share-copy-btn:hover {
  background: var(--color-primary);
  transform: translateY(-1px);
}

/* Expiry card：水平排列，窄螢幕自動換成垂直 */
.share-expiry-card {
  background: rgba(160, 145, 124, 0.1);
  border-radius: 12px;
  padding: 12px 16px;
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.share-expiry-info {
  display: flex;
  align-items: baseline;
  gap: 2px;
  min-width: 0;
  flex: 1 1 auto;
  font-size: 12px;
  line-height: 1.4;
}

.share-expiry-label {
  font-weight: 500;
  color: var(--main-text-light);
}

.share-expiry-value {
  font-weight: 600;
  color: var(--main-text);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Select 自訂樣式（移除原生外觀） */
.share-select-wrap {
  position: relative;
  flex: 0 0 auto;
  min-width: 140px;
}

.share-expiry-select {
  width: 100%;
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  padding: 8px 32px 8px 12px;
  border: 1px solid rgba(160, 145, 124, 0.3);
  border-radius: 8px;
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  outline: none;
  transition: all 0.2s ease;
}

/* Option 樣式（瀏覽器允許的有限部分） */
.share-expiry-select option {
  background: var(--main-bg);
  color: var(--main-text);
  padding: 8px 12px;
  font-size: 13px;
}

.share-expiry-select option:disabled {
  color: var(--main-text-light);
}

/* 窄螢幕：select 撐滿一行 */
@media (max-width: 420px) {
  .share-select-wrap {
    width: 100%;
    min-width: 0;
  }
}

.share-expiry-select:hover:not(:disabled) {
  border-color: rgba(160, 145, 124, 0.5);
  background: rgba(255, 255, 255, 0.6);
}

.share-expiry-select:focus {
  border-color: var(--main-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.12);
}

.share-expiry-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.share-select-chevron {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--main-text-light);
}

/* Enable section */
.share-enable-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Footer */
.share-footer {
  padding: 16px 24px 20px;
  display: flex;
  justify-content: flex-end;
}

.share-enable-btn {
  padding: 11px 24px;
  background: var(--main-primary-dark);
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: all 0.2s ease;
}

.share-enable-btn:hover:not(:disabled) {
  background: var(--color-primary);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(var(--color-primary-rgb), 0.25);
}

.share-enable-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.share-disable-btn {
  padding: 10px 18px;
  background: transparent;
  color: var(--color-danger);
  border: 1px solid rgba(var(--color-danger-rgb), 0.3);
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.share-disable-btn:hover:not(:disabled) {
  background: rgba(var(--color-danger-rgb), 0.08);
  border-color: rgba(var(--color-danger-rgb), 0.5);
}

.share-disable-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
