import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'

// 解析要套用的時區：使用者偏好 → localStorage → 瀏覽器偵測值
// 未登入（分享頁）或沒設定時，fallback 到瀏覽器時區，行為與舊版一致。
function resolveTimezone(authStore) {
  return (
    authStore.preferences?.timezone ||
    localStorage.getItem('timezone') ||
    Intl.DateTimeFormat().resolvedOptions().timeZone
  )
}

// 後端時間統一為 UTC Unix timestamp（秒）或 ISO 字串
function toDate(value) {
  if (value == null || value === '') return null
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return isNaN(date.getTime()) ? null : date
}

/**
 * 統一的日期時間格式化 composable。
 * 所有顯示時間的元件都應改用這裡，避免各自呼叫 toLocale* 卻漏帶 timeZone，
 * 導致使用者的時區偏好顯示不出來。
 */
export function useDateFormatter() {
  const authStore = useAuthStore()
  const { locale } = useI18n()

  function localeCode() {
    return locale.value === 'zh-TW' ? 'zh-TW' : 'en-US'
  }

  // 完整日期 + 時間（年/月/日 時:分）
  function formatDateTime(value, opts = {}) {
    const date = toDate(value)
    if (!date) return value == null ? '' : String(value)
    return date.toLocaleString(localeCode(), {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: resolveTimezone(authStore),
      ...opts
    })
  }

  // 只要日期（年/月/日）
  function formatDate(value, opts = {}) {
    const date = toDate(value)
    if (!date) return value == null ? '' : String(value)
    return date.toLocaleDateString(localeCode(), {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      timeZone: resolveTimezone(authStore),
      ...opts
    })
  }

  return { formatDate, formatDateTime }
}
