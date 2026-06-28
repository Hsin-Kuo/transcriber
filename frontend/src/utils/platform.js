/**
 * 平台偵測工具
 * Mac 使用 ⌘ (Command)，Windows/Linux 使用 Ctrl
 */

// navigator.platform 已 deprecated，優先用 userAgentData.platform，fallback 回舊 API
const _platform = navigator.userAgentData?.platform || navigator.platform || ''
export const isMac = /mac/i.test(_platform) || /iPhone|iPod|iPad/.test(navigator.platform || '')

/** 顯示用的修飾鍵標籤（Mac 上 Alt 鍵標示為 Option/⌥） */
export const modifierKeyLabel = isMac ? 'Option' : 'Alt'

/** 檢查事件中是否按下了平台對應的修飾鍵 */
export function isModifierPressed(event) {
  return isMac ? event.metaKey : event.ctrlKey
}
