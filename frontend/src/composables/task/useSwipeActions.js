// 手機任務卡「左滑露出動作鈕」— iOS 風格 swipe actions
// 只在 <=768px 啟用；桌機呼叫端不受影響（handlers 直接 return，offsetX 恆為 0）
import { ref, watch } from 'vue'

const MOBILE_QUERY = '(max-width: 768px)'
const EDGE_GUARD_PX = 24 // 起手點太靠左邊緣時放棄，避開 iOS 返回手勢
const DIRECTION_LOCK_PX = 10 // 前 10px 判斷手勢方向
const RUBBER_BAND_FACTOR = 0.3
const OPEN_RATIO_THRESHOLD = 0.4 // 位移 > 動作區寬度 40% 視為要開
const FAST_FLICK_VELOCITY = 0.5 // px/ms，收尾速度夠快也視為要開

// module-level 共享狀態：目前開啟的卡片 id（單一開啟協調）
const openCardId = ref(null)
let scrollListenerAttached = false

function ensureScrollListenerAttached() {
  if (scrollListenerAttached) return
  scrollListenerAttached = true
  window.addEventListener(
    'scroll',
    () => {
      openCardId.value = null
    },
    { passive: true, capture: true }
  )
}

function isMobileViewport() {
  return typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches
}

const LONG_PRESS_MS = 500 // 長按進入批次選取模式的門檻

/**
 * @param {string|number} cardId 卡片唯一 id（用於單一開啟協調）
 * @param {import('vue').Ref<number>} actionsWidthRef 動作區寬度（px）的 ref
 * @param {import('vue').Ref<boolean>} [disabledRef] 停用（如批次編輯模式）
 * @param {Function} [onLongPress] 長按 500ms（無位移）觸發；卡片開啟中不觸發
 */
export function useSwipeActions(cardId, actionsWidthRef, disabledRef, onLongPress) {
  ensureScrollListenerAttached()

  const offsetX = ref(0)
  const dragging = ref(false)
  const withTransition = ref(true)

  let active = false // 本次 pointer 手勢是否啟用（通過 media query / edge guard 檢查）
  let directionLocked = false // 是否已判斷過方向
  let horizontalGesture = false // 方向鎖判定結果：水平手勢
  let startX = 0
  let startY = 0
  let lastX = 0
  let lastT = 0
  let velocity = 0
  let startedOpen = false
  let suppressNextClick = false
  let longPressTimer = null

  function clearLongPress() {
    if (longPressTimer !== null) {
      clearTimeout(longPressTimer)
      longPressTimer = null
    }
  }

  const isOpen = ref(false)

  // 單一開啟協調：別的卡片開啟（或全域收合，openCardId 變成 null）時，收合自己
  watch(openCardId, (id) => {
    if (id !== cardId && isOpen.value) {
      offsetX.value = 0
      isOpen.value = false
      withTransition.value = true
    }
  })

  function actionsWidth() {
    return actionsWidthRef?.value || 0
  }

  function closeSwipe(withAnim = true) {
    withTransition.value = withAnim
    offsetX.value = 0
    isOpen.value = false
    if (openCardId.value === cardId) {
      openCardId.value = null
    }
  }

  function openSwipe() {
    withTransition.value = true
    offsetX.value = -actionsWidth()
    isOpen.value = true
    // 單一開啟協調：開新卡自動收舊卡
    openCardId.value = cardId
  }

  function onPointerDown(event) {
    active = false
    directionLocked = false
    horizontalGesture = false
    suppressNextClick = false
    // 每次手勢重新讀取當下開關狀態，避免早退路徑（disabled/桌機/邊緣保護）
    // 殘留上一次手勢的值，誤導 click 攔截判斷
    startedOpen = isOpen.value

    if (disabledRef?.value) return
    if (!isMobileViewport()) return
    if (event.clientX < EDGE_GUARD_PX) return // 邊緣保護，避開 iOS 返回手勢

    active = true
    startX = event.clientX
    startY = event.clientY
    lastX = startX
    lastT = event.timeStamp
    velocity = 0
    dragging.value = false

    // 長按（500ms 無位移）→ 批次選取；卡片開啟中不觸發（該輕點是收合）
    if (typeof onLongPress === 'function' && !startedOpen) {
      clearLongPress()
      longPressTimer = setTimeout(() => {
        longPressTimer = null
        active = false // 中止本次 swipe 手勢
        suppressNextClick = true // 放手後的 click 不得導頁
        onLongPress()
      }, LONG_PRESS_MS)
    }
  }

  function onPointerMove(event) {
    if (!active) return

    const dx = event.clientX - startX
    const dy = event.clientY - startY

    if (!directionLocked) {
      if (Math.abs(dx) < DIRECTION_LOCK_PX && Math.abs(dy) < DIRECTION_LOCK_PX) {
        return
      }
      directionLocked = true
      clearLongPress() // 有位移就不是長按
      horizontalGesture = Math.abs(dx) > Math.abs(dy)
      if (!horizontalGesture) {
        // 垂直手勢：放棄本次，讓瀏覽器捲動接手
        active = false
        return
      }
      dragging.value = true
      withTransition.value = false
    }

    // 追蹤速度（用於放手時判斷快速甩動）
    const dt = event.timeStamp - lastT
    if (dt > 0) {
      velocity = (event.clientX - lastX) / dt
    }
    lastX = event.clientX
    lastT = event.timeStamp

    const width = actionsWidth()
    // 基準位移：已開啟狀態下，起點視為已在 -width
    const base = startedOpen ? -width : 0
    let next = base + dx

    if (next < -width) {
      // 超出動作區寬度：rubber-band 阻尼
      const over = next + width
      next = -width + over * RUBBER_BAND_FACTOR
    } else if (next > 0) {
      // 只允許左滑；正向（右滑超過 0）同樣阻尼收斂在 0 附近
      next = next * RUBBER_BAND_FACTOR
    }

    offsetX.value = next

    if (Math.abs(dx) > DIRECTION_LOCK_PX) {
      suppressNextClick = true
    }
  }

  function finishGesture() {
    if (!active) {
      active = false
      return
    }
    active = false
    dragging.value = false
    withTransition.value = true

    if (!directionLocked || !horizontalGesture) {
      // 未曾判定為水平手勢（例如尚未移動或已判定垂直）：維持原狀
      if (startedOpen) {
        // 開啟狀態下的輕點：交由 click 攔截處理收合
      }
      return
    }

    const width = actionsWidth()
    if (width <= 0) {
      closeSwipe()
      return
    }

    const openedFar = Math.abs(offsetX.value) > width * OPEN_RATIO_THRESHOLD
    const fastFlickOpen = velocity < -FAST_FLICK_VELOCITY
    const fastFlickClose = velocity > FAST_FLICK_VELOCITY

    if (fastFlickClose) {
      closeSwipe()
    } else if (openedFar || fastFlickOpen) {
      openSwipe()
    } else {
      closeSwipe()
    }
  }

  function onPointerUp() {
    clearLongPress()
    finishGesture()
  }

  function onPointerCancel() {
    clearLongPress()
    active = false
    dragging.value = false
    withTransition.value = true
    // 手勢被系統取消：回復到手勢前的開/關狀態
    if (startedOpen) {
      openSwipe()
    } else {
      closeSwipe()
    }
  }

  // 點擊抑制（capture phase）：本次手勢有明顯水平位移，或卡片原本已開啟 → 攔截 click
  function onClickCapture(event) {
    if (startedOpen && !suppressNextClick) {
      // 開啟狀態下的輕點（非拖曳）：收合、不導頁
      event.stopPropagation()
      event.preventDefault()
      closeSwipe()
      suppressNextClick = false
      return
    }
    if (suppressNextClick) {
      event.stopPropagation()
      event.preventDefault()
      suppressNextClick = false
    }
  }

  const handlers = {
    onPointerdown: onPointerDown,
    onPointermove: onPointerMove,
    onPointerup: onPointerUp,
    onPointercancel: onPointerCancel,
    onClickCapture
  }

  return {
    offsetX,
    isOpen,
    dragging,
    withTransition,
    handlers,
    closeSwipe
  }
}
