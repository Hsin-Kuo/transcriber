import { watch, onUnmounted, nextTick } from 'vue'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

/**
 * @param {import('vue').Ref<HTMLElement|null>} containerRef - ref to the dialog/modal container element
 * @param {import('vue').Ref<boolean>} isOpen - reactive boolean controlling open state
 */
export function useFocusTrap(containerRef, isOpen) {
  let previouslyFocused = null

  function getFocusableElements() {
    if (!containerRef.value) return []
    return [...containerRef.value.querySelectorAll(FOCUSABLE_SELECTOR)]
      .filter(el => el.offsetParent !== null)
  }

  function handleKeyDown(e) {
    if (e.key === 'Escape') {
      return
    }
    if (e.key !== 'Tab') return

    const focusable = getFocusableElements()
    if (focusable.length === 0) return

    const first = focusable[0]
    const last = focusable[focusable.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  function activate() {
    previouslyFocused = document.activeElement
    document.addEventListener('keydown', handleKeyDown)
    nextTick(() => {
      const focusable = getFocusableElements()
      if (focusable.length > 0) {
        focusable[0].focus()
      }
    })
  }

  function deactivate() {
    document.removeEventListener('keydown', handleKeyDown)
    if (previouslyFocused && previouslyFocused.focus) {
      previouslyFocused.focus()
      previouslyFocused = null
    }
  }

  watch(isOpen, (val) => {
    if (val) {
      nextTick(activate)
    } else {
      deactivate()
    }
  })

  onUnmounted(deactivate)
}
