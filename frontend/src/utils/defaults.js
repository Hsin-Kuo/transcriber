/**
 * 瀏覽器環境偵測 — 為新使用者提供合理的預設值
 */

const SUPPORTED_LOCALES = ['zh-TW', 'en']
const SUPPORTED_TIMEZONES = [
  'Asia/Taipei', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Hong_Kong',
  'America/New_York', 'America/Los_Angeles', 'Europe/London'
]

/**
 * 偵測瀏覽器語言，對應到支援的 locale
 * navigator.language: "zh-TW", "en-US", "ja", ...
 */
export function detectLanguage() {
  const langs = navigator.languages || [navigator.language]
  for (const lang of langs) {
    // 完全匹配 (e.g. "zh-TW")
    if (SUPPORTED_LOCALES.includes(lang)) return lang
    // 前綴匹配 (e.g. "en-US" → "en", "zh" → "zh-TW")
    const prefix = lang.split('-')[0]
    if (prefix === 'zh') return 'zh-TW'
    const match = SUPPORTED_LOCALES.find(l => l.startsWith(prefix))
    if (match) return match
  }
  return 'zh-TW'
}

/**
 * 偵測系統時區，如果不在支援清單就回傳最接近的
 * Intl.DateTimeFormat().resolvedOptions().timeZone: "Asia/Taipei", ...
 */
export function detectTimezone() {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    if (SUPPORTED_TIMEZONES.includes(tz)) return tz
    return 'Asia/Taipei'
  } catch {
    return 'Asia/Taipei'
  }
}

/**
 * 偵測 OS 色彩偏好
 */
export function detectTheme() {
  try {
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark'
  } catch { /* ignore */ }
  return 'light'
}
