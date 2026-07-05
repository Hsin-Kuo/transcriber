import { ref, watch, onMounted, onUnmounted } from 'vue'
import { formatTime } from '../../utils/formatTime'
import {
  buildCharIndexMap,
  charOffsetToRange,
  caretToCharOffset,
} from './useSegmentEditingOffsets'

/**
 * Alt+Click segment navigation composable.
 *
 * Manages: Alt key state, CSS Highlight API segment highlighting,
 * hover chip (shows timecode on hover), and click-to-seek.
 */
export function useSegmentNavigation({
  textareaRef,
  segOffsets,
  isEditing,
  displayMode,
  hasAudio,
  seekToTime,
  headerRef,
  isModifierPressed,
  // 導覽用：為 true 時強制顯示 segment 高亮（不需真的按 Alt），且不受滑鼠/鍵盤事件關閉。
  demoActive,
}) {
  const isAltPressed = ref(false)
  const hoverChipVisible = ref(false)
  const hoverChipTime = ref('')
  const hoverChipStyle = ref({ left: '0px', top: '0px' })

  let segmentHighlightRafId = null
  let hoverChipRafId = null
  let pendingMouseEvent = null
  let scrollHighlightTimer = null

  // --- CSS Highlight API segment highlighting ---

  function rebuildSegmentHighlight() {
    segmentHighlightRafId = null
    if (!window.CSS || !CSS.highlights) return
    if (!textareaRef.value) return

    // 編輯與非編輯模式共用同一套 segment 高亮（ranges 來源由 navSegOffsets facade 切換）
    // 導覽 demo 期間 demoActive 亦視為「已按 Alt」，讓真實橘色高亮直接畫在真文字上。
    const shouldShow =
      (isAltPressed.value || demoActive?.value) &&
      displayMode.value === 'paragraph' &&
      segOffsets.editSegmentRanges.value.length > 0
    if (!shouldShow) {
      CSS.highlights.delete('segment-highlight')
      return
    }

    const el = textareaRef.value
    const segs = segOffsets.editSegmentRanges.value
    const totalChars = segOffsets.snapshot.value.length || segs[segs.length - 1].charEnd
    let startChar = 0
    let endChar = totalChars
    if (el.scrollHeight > 0 && totalChars > 0) {
      const topRatio = el.scrollTop / el.scrollHeight
      const bottomRatio = (el.scrollTop + el.clientHeight) / el.scrollHeight
      const buffer = (bottomRatio - topRatio) * 1.5
      startChar = Math.floor(Math.max(0, topRatio - buffer) * totalChars)
      endChar = Math.ceil(Math.min(1, bottomRatio + buffer) * totalChars)
    }

    const map = buildCharIndexMap(el)
    const ranges = []
    for (const r of segs) {
      if (r.charEnd < startChar || r.charStart > endChar) continue
      const range = charOffsetToRange(map, r.charStart, r.charEnd)
      if (range) ranges.push(range)
    }

    if (ranges.length > 0) {
      CSS.highlights.set('segment-highlight', new Highlight(...ranges))
    } else {
      CSS.highlights.delete('segment-highlight')
    }
  }

  function scheduleSegmentHighlightRebuild() {
    if (segmentHighlightRafId !== null) return
    segmentHighlightRafId = requestAnimationFrame(rebuildSegmentHighlight)
  }

  function clearSegmentHighlight() {
    if (segmentHighlightRafId !== null) {
      cancelAnimationFrame(segmentHighlightRafId)
      segmentHighlightRafId = null
    }
    if (window.CSS && CSS.highlights) {
      const wasSet = CSS.highlights.has('segment-highlight')
      CSS.highlights.delete('segment-highlight')
      CSS.highlights.delete('segment-highlight-hover')
      if (wasSet) {
        const el = textareaRef.value
        if (el) {
          el.style.transform = 'translateZ(0)'
          requestAnimationFrame(() => { el.style.transform = '' })
        }
      }
    }
  }

  // --- Hit testing ---

  function hitTestSegmentAt(clientX, clientY) {
    if (!textareaRef.value) return null
    let caret = null
    if (document.caretPositionFromPoint) {
      caret = document.caretPositionFromPoint(clientX, clientY)
      if (caret) caret = { node: caret.offsetNode, offset: caret.offset }
    } else if (document.caretRangeFromPoint) {
      const range = document.caretRangeFromPoint(clientX, clientY)
      if (range) caret = { node: range.startContainer, offset: range.startOffset }
    }
    if (!caret || !caret.node) return null

    const map = buildCharIndexMap(textareaRef.value)
    const charOffset = caretToCharOffset(map, caret.node, caret.offset)
    if (charOffset == null) return null

    for (const r of segOffsets.editSegmentRanges.value) {
      if (charOffset >= r.charStart && charOffset < r.charEnd) return r
    }
    return null
  }

  // --- Hover chip ---

  function clearSegmentHoverHighlight() {
    if (window.CSS && CSS.highlights) {
      CSS.highlights.delete('segment-highlight-hover')
    }
  }

  function hideHoverChip() {
    hoverChipVisible.value = false
    clearSegmentHoverHighlight()
  }

  function updateHoverChipFromEvent(e) {
    hoverChipRafId = null
    if (!isAltPressed.value || displayMode.value !== 'paragraph') {
      hideHoverChip()
      return
    }
    const hit = hitTestSegmentAt(e.clientX, e.clientY)
    if (!hit) { hideHoverChip(); return }
    const wrapper = textareaRef.value?.parentElement
    if (!wrapper) { hideHoverChip(); return }
    const map = buildCharIndexMap(textareaRef.value)
    const segRange = charOffsetToRange(map, hit.charStart, hit.charEnd)
    if (!segRange) { hideHoverChip(); return }
    const rects = Array.from(segRange.getClientRects())
    if (rects.length === 0) { hideHoverChip(); return }
    const lineRect =
      rects.find((r) => e.clientY >= r.top && e.clientY <= r.bottom) || rects[0]
    const wrapperRect = wrapper.getBoundingClientRect()
    hoverChipTime.value = formatTime(hit.start)
    hoverChipStyle.value = {
      left: `${e.clientX - wrapperRect.left}px`,
      top: `${lineRect.top - wrapperRect.top}px`,
    }
    hoverChipVisible.value = true

    // 高亮目前 hover 到的 segment（疊在 segment-highlight 之上，priority 較高），
    // 讓編輯模式 hover 也有顏色變化，與閱讀模式的 :hover 變色一致
    if (window.CSS && CSS.highlights) {
      const hl = new Highlight(segRange)
      hl.priority = 1
      CSS.highlights.set('segment-highlight-hover', hl)
    }
  }

  // --- Editor event handlers (bound to contenteditable) ---

  function handleEditorMouseMove(e) {
    if (!isAltPressed.value) return
    pendingMouseEvent = { clientX: e.clientX, clientY: e.clientY }
    if (hoverChipRafId !== null) return
    hoverChipRafId = requestAnimationFrame(() => {
      if (pendingMouseEvent) updateHoverChipFromEvent(pendingMouseEvent)
    })
  }

  function handleEditorClickInEditing(e) {
    if (e.button !== 0 || !e.altKey || !hasAudio.value) return
    const hit = hitTestSegmentAt(e.clientX, e.clientY)
    if (!hit) return
    e.preventDefault()
    seekToTime(hit.start)
  }

  function handleEditorScroll() {
    hideHoverChip()
    if (!isAltPressed.value || displayMode.value !== 'paragraph') return
    if (scrollHighlightTimer) clearTimeout(scrollHighlightTimer)
    scrollHighlightTimer = setTimeout(() => {
      scrollHighlightTimer = null
      scheduleSegmentHighlightRebuild()
    }, 80)
  }

  // --- ▼ 時間標記點擊（overlay）---

  function handleMarkerClick(startTime) {
    if (hasAudio.value) {
      seekToTime(startTime)
    }
  }

  // ▼ 標記 hover：複用 Alt hover 的同一顆 chip（在 wrapper 內、不被 scroller 裁切），
  // 確保與 highlight tooltip 外觀/行為完全一致。傳入 marker 的視窗座標（頂端中心點）。
  function showHoverChipAt(startTime, clientX, clientY) {
    const wrapper = textareaRef.value?.parentElement
    if (!wrapper) return
    const wrapperRect = wrapper.getBoundingClientRect()
    hoverChipTime.value = formatTime(startTime)
    hoverChipStyle.value = {
      left: `${clientX - wrapperRect.left}px`,
      top: `${clientY - wrapperRect.top}px`,
    }
    hoverChipVisible.value = true
  }

  // --- Alt key state tracking (window-level) ---

  function handleKeyDown(e) {
    if (isModifierPressed(e) && e.key === 'f') {
      e.preventDefault()
      e.stopPropagation()
      if (headerRef.value) {
        headerRef.value.focusSearch()
      }
      return
    }

    if (e.altKey) {
      // 只設狀態驅動 Alt-highlight / hover chip；preventDefault 僅限播放器快捷鍵，
      // 否則會連 Option+Delete（deleteWordBackward）這類原生編輯行為一起擋掉。
      isAltPressed.value = true
      const shortcutKeys = ['m', 'M', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown']
      // 按住 Shift 時放行，讓原生的整字/整段擴選（Option+Shift+方向鍵）生效。
      if (shortcutKeys.includes(e.key) && !e.shiftKey) {
        e.preventDefault()
        e.stopPropagation()
      }
    }
  }

  function handleKeyUp(e) {
    if (e.key === 'Alt') {
      // Windows 上單獨放開 Alt 會把 focus 交給瀏覽器功能列（Firefox menu bar /
      // Chrome、Edge 三點選單），之後鍵盤輸入會落在瀏覽器 UI 上。本頁把 Alt 當
      // app modifier（hover chip、Alt+click seek），一律攔截；鍵盤使用者仍可用 F10 開選單。
      e.preventDefault()
    }
    if (!e.altKey || e.key === 'Alt') {
      isAltPressed.value = false
    }
  }

  function syncAltFromMouse(e) {
    if (isAltPressed.value && !e.altKey) {
      isAltPressed.value = false
    }
  }

  function handleBlur() {
    isAltPressed.value = false
  }

  // --- Watch for state changes ---

  watch(
    [
      isAltPressed,
      () => demoActive?.value,
      () => isEditing.value,
      () => displayMode.value,
      () => segOffsets.editSegmentRanges.value,
    ],
    () => {
      if ((isAltPressed.value || demoActive?.value) && displayMode.value === 'paragraph') {
        scheduleSegmentHighlightRebuild()
      } else {
        clearSegmentHighlight()
        hideHoverChip()
      }
    }
  )

  // 導覽 demo 用：量測某個 segment 在 wrapper 內的座標（第一行 rect），
  // 供假游標／時間標記定位在「真實句子」上。回傳 wrapper 相對座標或 null。
  function measureSegmentRect(segmentIndex) {
    const el = textareaRef.value
    const wrapper = el?.parentElement
    if (!el || !wrapper) return null
    const ranges = segOffsets.editSegmentRanges.value
    const r =
      ranges.find((x) => x.segmentIndex === segmentIndex) || ranges[0]
    if (!r) return null
    const map = buildCharIndexMap(el)
    const range = charOffsetToRange(map, r.charStart, r.charEnd)
    if (!range) return null
    const rects = Array.from(range.getClientRects())
    if (rects.length === 0) return null
    const first = rects[0]
    const wrapperRect = wrapper.getBoundingClientRect()
    return {
      top: first.top - wrapperRect.top,
      left: first.left - wrapperRect.left,
      width: first.width,
      height: first.height,
      start: r.start,
    }
  }

  // --- Lifecycle ---

  onMounted(() => {
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    window.addEventListener('mousemove', syncAltFromMouse)
    window.addEventListener('mousedown', syncAltFromMouse)
    window.addEventListener('blur', handleBlur)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown)
    window.removeEventListener('keyup', handleKeyUp)
    window.removeEventListener('mousemove', syncAltFromMouse)
    window.removeEventListener('mousedown', syncAltFromMouse)
    window.removeEventListener('blur', handleBlur)
    clearSegmentHighlight()
    if (hoverChipRafId !== null) cancelAnimationFrame(hoverChipRafId)
    if (scrollHighlightTimer) clearTimeout(scrollHighlightTimer)
  })

  return {
    isAltPressed,
    hoverChipVisible,
    hoverChipTime,
    hoverChipStyle,
    handleEditorMouseMove,
    handleEditorClickInEditing,
    handleEditorScroll,
    handleMarkerClick,
    showHoverChipAt,
    hideHoverChip,
    measureSegmentRect,
  }
}
