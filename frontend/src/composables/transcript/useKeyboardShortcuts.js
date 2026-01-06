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
  toggleMute,
  setPlaybackRate,
  playbackRate
) {
  /**
   * 鍵盤快捷鍵處理函數
   */
  function handleKeyboardShortcuts(event) {
    // 檢查是否有音訊
    if (!hasAudio.value || !audioElement.value) return

    // 檢查焦點是否在輸入框內
    const targetIsInput = event.target.tagName === 'INPUT' ||
                          event.target.tagName === 'TEXTAREA' ||
                          event.target.isContentEditable

    // Alt + 鍵組合（編輯和非編輯模式都可用，即使焦點在輸入框內也可用）
    // 因為 Alt 組合鍵不太會與正常打字衝突
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      switch(event.key) {
        case ' ':  // Alt + 空白鍵：播放/暫停
          event.preventDefault()
          togglePlayPause()
          break
        case 'ArrowLeft':
          event.preventDefault()
          skipBackward()
          break
        case 'ArrowRight':
          event.preventDefault()
          skipForward()
          break
        case 'ArrowUp':  // Alt + 上鍵：加速播放（+0.25x）
          event.preventDefault()
          if (setPlaybackRate && playbackRate) {
            const newRate = Math.min(2, playbackRate.value + 0.25)
            setPlaybackRate(newRate)
          }
          break
        case 'ArrowDown':  // Alt + 下鍵：減速播放（-0.25x）
          event.preventDefault()
          if (setPlaybackRate && playbackRate) {
            const newRate = Math.max(0.25, playbackRate.value - 0.25)
            setPlaybackRate(newRate)
          }
          break
        case 'm':
        case 'M':
          event.preventDefault()
          toggleMute()
          break
        case ',':
          event.preventDefault()
          skipBackward(5)
          break
        case '.':
          event.preventDefault()
          skipForward(5)
          break
      }
      return
    }

    // 非編輯模式下的單鍵快捷鍵（不需要 Alt）
    // 如果焦點在輸入框內，不處理這些快捷鍵，避免干擾打字
    const isEditingText = isEditing.value || isEditingTitle.value
    if (!isEditingText && !targetIsInput && !event.altKey && !event.ctrlKey && !event.metaKey) {
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
