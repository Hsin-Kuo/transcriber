import { onMounted, onUnmounted } from 'vue'

export function useClickOutside(targetRef, handler) {
  function onPointerDown(event) {
    if (targetRef.value && !targetRef.value.contains(event.target)) {
      handler(event)
    }
  }

  onMounted(() => {
    document.addEventListener('pointerdown', onPointerDown, true)
  })

  onUnmounted(() => {
    document.removeEventListener('pointerdown', onPointerDown, true)
  })
}
