/**
 * 平台偵測工具
 * Mac 使用 ⌘ (Command)，Windows/Linux 使用 Ctrl
 */

export const isMac = /Mac|iPhone|iPod|iPad/.test(navigator.platform)

/** 顯示用的修飾鍵標籤 */
export const modifierKeyLabel = isMac ? '⌘' : 'Ctrl'

/** 檢查事件中是否按下了平台對應的修飾鍵 */
export function isModifierPressed(event) {
  return isMac ? event.metaKey : event.ctrlKey
}
