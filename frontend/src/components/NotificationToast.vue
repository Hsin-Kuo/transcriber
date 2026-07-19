<template>
  <div class="notification-container" aria-live="polite" aria-atomic="false" role="status">
    <TransitionGroup name="notification">
        <div
          v-for="notification in notifications"
          :key="notification.id"
          class="notification-toast"
          :class="`notification-${notification.type}`"
          @click="removeNotification(notification.id)"
          @mouseenter="handleToastMouseEnter(notification)"
          @mouseleave="handleToastMouseLeave(notification)"
        >
          <div class="notification-icon">
            <svg v-if="notification.type === 'info'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            <svg v-else-if="notification.type === 'success'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
            <svg v-else-if="notification.type === 'error'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="15" y1="9" x2="9" y2="15"></line>
              <line x1="9" y1="9" x2="15" y2="15"></line>
            </svg>
            <svg v-else-if="notification.type === 'processing'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
          </div>
          <div class="notification-content">
            <div class="notification-title">{{ notification.title }}</div>
            <div v-if="notification.message" class="notification-message">{{ notification.message }}</div>
            <button
              v-if="notification.action"
              type="button"
              class="notification-action"
              @click.stop="handleAction(notification)"
            >
              {{ notification.action.label }}
            </button>
          </div>
          <button class="notification-close" @click.stop="removeNotification(notification.id)" :aria-label="$t('common.close')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      </TransitionGroup>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const notifications = ref([])
let notificationId = 0

function addNotification({ title, message, type = 'info', duration, action }) {
  // 預設停留時間依類型決定（呼叫端仍可顯式傳 duration 覆寫）：
  //   error / warning → 永久停留（duration 0），需使用者點擊整則或按關閉鈕才消失，避免重要訊息被錯過
  //   success / info / processing → 10 秒後自動關閉
  if (duration === undefined) {
    duration = (type === 'error' || type === 'warning') ? 0 : 10000
  }

  const id = ++notificationId
  const notification = {
    id,
    title,
    message,
    type,
    // optional 動作按鈕（如上傳完成的「查看」）：{ label, handler }
    action
  }

  notifications.value.push(notification)

  // error/warning（duration 0）永久停留；其餘存下自動關閉 timer，
  // 以便 hover-and-leave 提早關時一併清除，避免殘留 setTimeout 空跑
  if (duration > 0) {
    notification.timer = setTimeout(() => {
      removeNotification(id)
    }, duration)
  }

  return id
}

function removeNotification(id) {
  const index = notifications.value.findIndex(n => n.id === id)
  if (index !== -1) {
    const [removed] = notifications.value.splice(index, 1)
    if (removed?.timer) clearTimeout(removed.timer)
  }
  hoverEnterTimes.delete(id)
}

// 一次清空所有 toast（登出時呼叫）：連同各自的 auto-close timer 一起清，
// 避免前一位使用者的通知（尤其 error/warning 是 duration 0 永久停留）跨 session 殘留。
function clearAll() {
  notifications.value.forEach(n => { if (n.timer) clearTimeout(n.timer) })
  notifications.value = []
  hoverEnterTimes.clear()
}

// 動作按鈕（如「查看」）：執行 handler 後關閉該則通知。
function handleAction(notification) {
  notification.action?.handler?.()
  removeNotification(notification.id)
}

// hover-and-leave 關閉（所有 toast 皆適用）：記錄進入時間，離開時若停留夠久才關。
// 對 error/warning 是唯一的自動關閉途徑；對 success 等則是「提早關、忽略剩餘的 10 秒」。
// dwell 門檻避免滑鼠快速「掠過」誤關。
const hoverEnterTimes = new Map()
const HOVER_DWELL_MS = 250

function handleToastMouseEnter(notification) {
  hoverEnterTimes.set(notification.id, performance.now())
}

function handleToastMouseLeave(notification) {
  const enteredAt = hoverEnterTimes.get(notification.id)
  hoverEnterTimes.delete(notification.id)
  // 沒有進入紀錄，或停留太短（掠過）→ 不關
  if (enteredAt === undefined || performance.now() - enteredAt < HOVER_DWELL_MS) return
  removeNotification(notification.id)
}

// Expose methods to parent component
defineExpose({
  addNotification,
  removeNotification,
  clearAll
})

// Listen to global notification events
function handleGlobalNotification(event) {
  addNotification(event.detail)
}

onMounted(() => {
  window.addEventListener('show-notification', handleGlobalNotification)
})

onUnmounted(() => {
  window.removeEventListener('show-notification', handleGlobalNotification)
})
</script>

<style scoped>
/* 定位由 App.vue 的 .notify-stack 共用容器負責；這裡只排列自身 toast 堆疊 */
.notification-container {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
  pointer-events: none;
}

.notification-toast {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  /* 與 GlobalUploadProgress 一致的固定寬度，兩者堆疊時對齊 */
  width: 340px;
  max-width: calc(100vw - 40px);
  padding: 14px 16px;
  background: var(--main-bg);
  /* 與 GlobalUploadProgress 一致的卡片樣式（圓角 / 陰影 / 邊框） */
  border-radius: 14px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
  border: 1px solid rgba(var(--color-primary-rgb), 0.15);
  pointer-events: auto;
  cursor: pointer;
  transition: all 0.3s ease;
}

.notification-toast:hover {
  transform: translateY(-2px);
}

.notification-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--main-bg);
}

.notification-info .notification-icon {
  color: var(--color-info);
}

.notification-success .notification-icon {
  color: var(--color-success);
}

.notification-error .notification-icon {
  color: var(--color-danger);
}

.notification-processing .notification-icon {
  color: var(--main-primary);
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.notification-content {
  flex: 1;
  min-width: 0;
}

.notification-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--main-text);
  margin-bottom: 4px;
}

.notification-message {
  font-size: 0.85rem;
  color: var(--main-text-light);
  line-height: 1.4;
  /* 保留訊息中的換行（批次部分失敗會用 \n 列出各檔原因）；單行訊息不受影響 */
  white-space: pre-line;
}

.notification-action {
  margin-top: 8px;
  padding: 5px 14px;
  font-size: 0.8rem;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  background: var(--color-primary, #6366f1);
  color: #fff;
  cursor: pointer;
  transition: background 0.2s ease;
}

.notification-action:hover {
  background: var(--color-primary-dark, #4f46e5);
}

.notification-close {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--main-text-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.notification-close:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--main-text);
}

/* Animation */
.notification-enter-active,
.notification-leave-active {
  transition: all 0.3s ease;
}

.notification-enter-from {
  opacity: 0;
  transform: translateX(100px);
}

.notification-leave-to {
  opacity: 0;
  transform: translateX(100px) scale(0.9);
}

.notification-move {
  transition: transform 0.3s ease;
}

@media (max-width: 768px) {
  /* 定位由 .notify-stack 負責；行動裝置滿版 */
  .notification-toast {
    min-width: auto;
    max-width: none;
    width: 100%;
  }
}
</style>
