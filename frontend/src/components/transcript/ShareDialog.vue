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

const props = defineProps({
  taskId: { type: String, required: true },
  /** 從 task 載入時帶入的初始 share token；後續以本元件內部 state 為準 */
  initialShareToken: { type: String, default: null },
  /** unix seconds；null = 永久 */
  initialShareExpiresAt: { type: Number, default: null },
})

const show = defineModel('show', { type: Boolean, default: false })

const { t } = useI18n()

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
      <div class="share-dialog">
        <h3>{{ t('shared.shareTitle') }}</h3>
        <p class="share-desc">{{ t('shared.shareDesc') }}</p>

        <div v-if="shareToken" class="share-link-section">
          <div class="share-link-row">
            <input
              type="text"
              :value="`${origin}/s/${shareToken}`"
              readonly
              class="share-link-input"
              @click="$event.target.select()"
            />
            <button class="share-copy-btn" @click="copyShareLink">
              {{ shareLinkCopied ? t('shared.linkCopied') : t('shared.copyLink') }}
            </button>
          </div>
          <div class="share-expiry-row">
            <span class="share-expiry-label">{{ t('shared.expiryLabel') }}：{{ shareExpiryText }}</span>
            <select
              class="share-expiry-select"
              :disabled="shareLoading"
              :value="shareExpiresAt ? -1 : 0"
              @change="updateShareExpiry(Number($event.target.value))"
            >
              <option :value="0">{{ t('shared.expiryNever') }}</option>
              <option :value="7">{{ t('shared.expiry7d') }}</option>
              <option :value="30">{{ t('shared.expiry30d') }}</option>
              <option :value="90">{{ t('shared.expiry90d') }}</option>
            </select>
          </div>
          <button
            class="share-disable-btn"
            :disabled="shareLoading"
            @click="toggleShare"
          >
            {{ t('shared.disableShare') }}
          </button>
        </div>

        <div v-else class="share-enable-section">
          <div class="share-expiry-row">
            <label class="share-expiry-label">{{ t('shared.expiryLabel') }}</label>
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
          </div>
          <button
            class="share-enable-btn"
            :disabled="shareLoading"
            @click="toggleShare"
          >
            {{ shareLoading ? '...' : t('shared.enableShare') }}
          </button>
        </div>

        <button class="share-close-btn" @click="show = false">✕</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.share-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.share-dialog {
  background: white;
  border-radius: 12px;
  padding: 24px;
  width: 420px;
  max-width: 90vw;
  position: relative;
}

.share-dialog h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  font-weight: 600;
}

.share-desc {
  color: #78716c;
  font-size: 13px;
  margin: 0 0 20px 0;
}

.share-link-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.share-link-row {
  display: flex;
  gap: 8px;
}

.share-link-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #d6d3d1;
  border-radius: 6px;
  font-size: 13px;
  color: #44403c;
  background: #fafaf9;
  outline: none;
}

.share-link-input:focus {
  border-color: #a8a29e;
}

.share-copy-btn {
  padding: 8px 16px;
  background: #292524;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}

.share-copy-btn:hover {
  background: #1c1917;
}

.share-disable-btn {
  padding: 8px 16px;
  background: none;
  color: #dc2626;
  border: 1px solid #fecaca;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.share-disable-btn:hover {
  background: #fef2f2;
}

.share-enable-section {
  text-align: center;
}

.share-enable-btn {
  padding: 10px 24px;
  background: #292524;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  width: 100%;
}

.share-enable-btn:hover {
  background: #1c1917;
}

.share-enable-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.share-close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  background: none;
  border: none;
  font-size: 18px;
  color: #a8a29e;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
}

.share-close-btn:hover {
  color: #44403c;
}
</style>
