<template>
  <transition name="upload-slide">
    <div v-if="store.active" class="global-upload" :class="`is-${store.status}`" role="status" aria-live="polite">
      <div class="gu-icon">
        <span v-if="store.status === 'uploading'" class="gu-spinner"></span>
        <span v-else-if="store.status === 'done'" class="gu-mark gu-mark--ok">✓</span>
        <span v-else-if="store.status === 'error'" class="gu-mark gu-mark--err">!</span>
        <span v-else class="gu-mark gu-mark--cancel">×</span>
      </div>

      <div class="gu-body">
        <div class="gu-head">
          <span class="gu-status">{{ statusText }}</span>
          <span v-if="store.status === 'uploading' && percentText" class="gu-percent">{{ percentText }}</span>
        </div>

        <div class="gu-label" :title="store.label">{{ store.label }}</div>

        <!-- 進度條：分片上傳顯示百分比；單次 POST（progress 為 0）顯示不確定動畫 -->
        <div v-if="store.status === 'uploading'" class="gu-bar" :class="{ indeterminate: store.progress === 0 }">
          <div class="gu-bar-fill" :style="{ width: store.progress > 0 ? store.progress + '%' : '100%' }"></div>
        </div>

        <div v-if="store.status === 'uploading' && store.kind === 'batch' && store.batchTotal > 0" class="gu-sub">
          {{ $t('globalUpload.batchProgress', { current: store.batchCurrent, total: store.batchTotal }) }}
        </div>
        <div v-else-if="store.status === 'error' && store.errorMessage" class="gu-sub gu-sub--err" :title="store.errorMessage">
          {{ store.errorMessage }}
        </div>
      </div>

      <div class="gu-actions">
        <button v-if="store.status === 'uploading'" type="button" class="gu-btn gu-btn--cancel" @click="store.cancel()">
          {{ $t('globalUpload.cancel') }}
        </button>
        <button v-else-if="store.status === 'done'" type="button" class="gu-btn gu-btn--view" @click="goToTasks">
          {{ $t('globalUpload.view') }}
        </button>
        <button
          v-if="store.status !== 'uploading'"
          type="button"
          class="gu-close"
          :aria-label="$t('globalUpload.close')"
          @click="store.dismiss()"
        >
          ×
        </button>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { computed, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useUploadStore } from '../stores/upload'

const { t: $t } = useI18n()
const router = useRouter()
const store = useUploadStore()

const statusText = computed(() => {
  switch (store.status) {
    case 'done':
      return $t('globalUpload.statusDone')
    case 'error':
      return $t('globalUpload.statusError')
    case 'cancelled':
      return $t('globalUpload.statusCancelled')
    default:
      return $t('globalUpload.statusUploading')
  }
})

const percentText = computed(() => (store.progress > 0 ? `${store.progress}%` : $t('globalUpload.processing')))

function goToTasks() {
  // 已在任務列表頁：push 同一路由 Vue Router 會忽略 → 點了沒反應。
  // 改整頁重新整理，確保使用者看到明確結果（新任務刷新出現）。
  if (router.currentRoute.value.name === 'tasks') {
    window.location.reload()
    return
  }
  store.dismiss()
  router.push({ name: 'tasks' })
}

// 完成後 8 秒自動收起（仍可手動關閉；若期間又有新上傳則不誤關）
let dismissTimer = null
watch(
  () => store.status,
  (status) => {
    if (dismissTimer) {
      clearTimeout(dismissTimer)
      dismissTimer = null
    }
    if (status === 'done') {
      dismissTimer = setTimeout(() => {
        if (store.status === 'done') store.dismiss()
      }, 8000)
    }
  },
)

onUnmounted(() => {
  if (dismissTimer) clearTimeout(dismissTimer)
})
</script>

<style scoped>
.global-upload {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 1200;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 320px;
  max-width: calc(100vw - 40px);
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--main-bg, #fff);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
  border: 1px solid rgba(var(--color-primary-rgb), 0.15);
}

.global-upload.is-done {
  border-color: color-mix(in srgb, var(--color-teal, #10b981) 40%, transparent);
}

.global-upload.is-error {
  border-color: color-mix(in srgb, var(--color-danger, #ef4444) 40%, transparent);
}

/* 圖示 */
.gu-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gu-spinner {
  width: 20px;
  height: 20px;
  border: 2.5px solid rgba(var(--color-primary-rgb), 0.25);
  border-top-color: var(--color-primary, #6366f1);
  border-radius: 50%;
  animation: gu-spin 0.8s linear infinite;
}

@keyframes gu-spin {
  to {
    transform: rotate(360deg);
  }
}

.gu-mark {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 15px;
  color: #fff;
}

.gu-mark--ok {
  background: var(--color-teal, #10b981);
}
.gu-mark--err {
  background: var(--color-danger, #ef4444);
}
.gu-mark--cancel {
  background: var(--color-gray-400, #9ca3af);
}

/* 內容 */
.gu-body {
  flex: 1;
  min-width: 0;
}

.gu-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.gu-status {
  font-size: 13px;
  font-weight: 600;
  color: var(--main-text, #1f2937);
}

.gu-percent {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-primary, #6366f1);
  flex-shrink: 0;
}

.gu-label {
  margin-top: 2px;
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gu-bar {
  margin-top: 8px;
  height: 6px;
  border-radius: 3px;
  background: rgba(var(--color-primary-rgb), 0.12);
  overflow: hidden;
}

.gu-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--color-primary, #6366f1), var(--color-primary-dark, #4f46e5));
  transition: width 0.3s ease;
}

/* 不確定狀態（單次 POST 無逐步進度）：跑馬燈動畫 */
.gu-bar.indeterminate .gu-bar-fill {
  width: 40% !important;
  animation: gu-indeterminate 1.2s ease-in-out infinite;
}

@keyframes gu-indeterminate {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(350%);
  }
}

.gu-sub {
  margin-top: 6px;
  font-size: 11px;
  color: rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.55);
}

.gu-sub--err {
  color: var(--color-danger, #ef4444);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 動作 */
.gu-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.gu-btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.gu-btn--cancel {
  background: transparent;
  color: rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.6);
  border: 1px solid rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.2);
}
.gu-btn--cancel:hover {
  color: var(--color-danger, #ef4444);
  border-color: color-mix(in srgb, var(--color-danger, #ef4444) 50%, transparent);
}

.gu-btn--view {
  background: var(--color-primary, #6366f1);
  color: #fff;
}
.gu-btn--view:hover {
  background: var(--color-primary-dark, #4f46e5);
}

.gu-close {
  width: 22px;
  height: 22px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: 50%;
  font-size: 18px;
  line-height: 1;
  color: rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.45);
  cursor: pointer;
  transition: all 0.2s;
}
.gu-close:hover {
  background: rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.08);
  color: rgba(var(--color-text-dark-rgb, 31, 41, 55), 0.8);
}

/* 進出場動畫 */
.upload-slide-enter-active,
.upload-slide-leave-active {
  transition: transform 0.3s ease, opacity 0.3s ease;
}
.upload-slide-enter-from,
.upload-slide-leave-to {
  transform: translateY(16px);
  opacity: 0;
}

/* 手機版：貼齊底部、避開底部導航 */
@media (max-width: 768px) {
  .global-upload {
    left: 12px;
    right: 12px;
    width: auto;
    bottom: calc(60px + env(safe-area-inset-bottom, 0px) + 8px);
  }
}
</style>
