import { onMounted, onUnmounted } from 'vue'

export function useKeyboardShortcuts(audioPlayerRef, { isEditing, isEditingTitle }) {
  function handleKeyboardShortcuts(event) {
    const player = audioPlayerRef.value
    if (!player) return

    const targetIsInput = event.target.tagName === 'INPUT' ||
                          event.target.tagName === 'TEXTAREA' ||
                          event.target.isContentEditable

    // Ctrl+Alt: play/pause
    if (event.altKey && event.ctrlKey) {
      if (event.key === 'Alt' || event.key === 'Control') {
        event.preventDefault()
        player.togglePlayPause()
      }
      return
    }

    // Alt + key combos (work in both editing and non-editing mode)
    // 按住 Shift 時放行，讓原生的整字/整段擴選（Option+Shift+方向鍵）在編輯區生效。
    if (event.altKey && !event.shiftKey) {
      switch(event.key) {
        case 'ArrowLeft':
          event.preventDefault()
          player.skipBackward()
          break
        case 'ArrowRight':
          event.preventDefault()
          player.skipForward()
          break
        case 'ArrowUp':
          event.preventDefault()
          player.setPlaybackRate(Math.min(2, (player.playbackRate?.value || 1) + 0.25))
          break
        case 'ArrowDown':
          event.preventDefault()
          player.setPlaybackRate(Math.max(0.25, (player.playbackRate?.value || 1) - 0.25))
          break
        case 'm':
        case 'M':
          event.preventDefault()
          player.toggleMute()
          break
      }
      return
    }

    // Single-key shortcuts in non-editing mode
    const isEditingText = isEditing.value || isEditingTitle.value
    if (!isEditingText && !targetIsInput && !event.altKey && !event.ctrlKey && !event.metaKey) {
      switch(event.key) {
        case ' ':
        case 'k':
        case 'K':
          event.preventDefault()
          player.togglePlayPause()
          break
        case 'j':
        case 'J':
          event.preventDefault()
          player.skipBackward()
          break
        case 'l':
        case 'L':
          event.preventDefault()
          player.skipForward()
          break
        case 'ArrowLeft':
          event.preventDefault()
          player.skipBackward()
          break
        case 'ArrowRight':
          event.preventDefault()
          player.skipForward()
          break
        case 'm':
        case 'M':
          event.preventDefault()
          player.toggleMute()
          break
      }
    }
  }

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
