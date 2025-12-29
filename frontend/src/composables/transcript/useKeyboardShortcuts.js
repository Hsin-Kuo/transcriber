import { onMounted, onUnmounted } from 'vue'

/**
 * 鍵盤快捷鍵管理 Composable
 *
 * 職責：
 * - 處理音訊播放器相關的鍵盤快捷鍵
 * - 區分編輯和非編輯模式下的快捷鍵
 */
export function useKeyboardShortcuts(
  hasAudio,
  audioElement,
  isEditing,
  isEditingTitle,
  togglePlayPause,
  skipBackward,
  skipForward,
  toggleMute
) {
  /**
   * 鍵盤快捷鍵處理函數
   */
  function handleKeyboardShortcuts(event) {
    // 檢查是否有音訊
    if (!hasAudio.value || !audioElement.value) return

    // 檢查是否正在編輯文字
    const isEditingText = isEditing.value || isEditingTitle.value
    const targetIsInput = event.target.tagName === 'INPUT' ||
                          event.target.tagName === 'TEXTAREA' ||
                          event.target.isContentEditable

    // 如果正在編輯輸入框，不處理快捷鍵
    if (isEditingText && targetIsInput) return

    // Alt + 鍵組合（編輯和非編輯模式都可用）
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      switch(event.key) {
        case 'k':
        case 'K':
          event.preventDefault()
          togglePlayPause()
          break
        case 'j':
        case 'J':
        case 'ArrowLeft':
          event.preventDefault()
          skipBackward()
          break
        case 'l':
        case 'L':
        case 'ArrowRight':
          event.preventDefault()
          skipForward()
          break
        case 'm':
        case 'M':
          event.preventDefault()
          toggleMute()
          break
        case ',':
          event.preventDefault()
          // 快退 5 秒
          if (audioElement.value) {
            audioElement.value.currentTime = Math.max(0, audioElement.value.currentTime - 5)
          }
          break
        case '.':
          event.preventDefault()
          // 快進 5 秒
          if (audioElement.value) {
            audioElement.value.currentTime = Math.min(
              audioElement.value.duration || 0,
              audioElement.value.currentTime + 5
            )
          }
          break
      }
      return
    }

    // 非編輯模式下的快捷鍵（不需要 Alt）
    if (!isEditingText && !event.altKey && !event.ctrlKey && !event.metaKey) {
      switch(event.key) {
        case ' ':  // 空白鍵：播放/暫停
        case 'k':
        case 'K':
          event.preventDefault()
          togglePlayPause()
          break
        case 'j':  // J：後退 10 秒
        case 'J':
          event.preventDefault()
          skipBackward()
          break
        case 'l':  // L：前進 10 秒
        case 'L':
          event.preventDefault()
          skipForward()
          break
        case 'ArrowLeft':  // 左箭頭：後退 10 秒
          event.preventDefault()
          skipBackward()
          break
        case 'ArrowRight':  // 右箭頭：前進 10 秒
          event.preventDefault()
          skipForward()
          break
        case 'm':  // M：靜音切換
        case 'M':
          event.preventDefault()
          toggleMute()
          break
      }
    }
  }

  /**
   * 自動註冊鍵盤事件監聽器
   */
  onMounted(() => {
    window.addEventListener('keydown', handleKeyboardShortcuts)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyboardShortcuts)
  })

  return {
    handleKeyboardShortcuts
  }
}
