import { ref, onMounted, onUnmounted } from 'vue'

export function usePullToRefresh(onRefresh, { threshold = 40, maxPull = 80 } = {}) {
  const pullDistance = ref(0)
  const isPulling = ref(false)
  const isRefreshing = ref(false)

  let startY = 0

  function onTouchStart(e) {
    if (window.scrollY > 0 || isRefreshing.value) return
    startY = e.touches[0].clientY
  }

  function onTouchMove(e) {
    if (!startY || window.scrollY > 0 || isRefreshing.value) return
    const delta = e.touches[0].clientY - startY
    if (delta <= 0) {
      pullDistance.value = 0
      isPulling.value = false
      return
    }
    isPulling.value = true
    pullDistance.value = Math.min(maxPull, delta * 0.45)
  }

  function onTouchEnd() {
    if (!isPulling.value) {
      startY = 0
      return
    }
    isPulling.value = false
    if (pullDistance.value >= threshold) {
      isRefreshing.value = true
      pullDistance.value = 0
      Promise.resolve(onRefresh()).finally(() => {
        isRefreshing.value = false
      })
    } else {
      pullDistance.value = 0
    }
    startY = 0
  }

  onMounted(() => {
    document.body.style.overscrollBehaviorY = 'none'
    document.addEventListener('touchstart', onTouchStart, { passive: true })
    document.addEventListener('touchmove', onTouchMove, { passive: true })
    document.addEventListener('touchend', onTouchEnd, { passive: true })
  })

  onUnmounted(() => {
    document.body.style.overscrollBehaviorY = ''
    document.removeEventListener('touchstart', onTouchStart)
    document.removeEventListener('touchmove', onTouchMove)
    document.removeEventListener('touchend', onTouchEnd)
  })

  return { pullDistance, isPulling, isRefreshing }
}
