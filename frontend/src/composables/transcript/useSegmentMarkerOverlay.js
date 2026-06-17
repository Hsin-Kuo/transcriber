import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { buildCharIndexMap, charOffsetToRange } from './useSegmentEditingOffsets'

/**
 * 非編輯模式的時間標記（▼）overlay。
 *
 * 取代「一段一 span」的舊渲染：純文字單一 text node 之上疊一層 overlay，
 * 對每個 segment 起點用 charOffsetToRange→getClientRects 算出「內容相對座標」
 * （相對 scroller padding box 頂端，與 scrollTop 無關）。
 *
 * 因為 overlay 與 marker 都是 scroller(.transcript-display) 內的 absolute 子元素，
 * 會隨內容「原生捲動 + 原生裁切」——故捲動完全不需重算，只在
 * 內容 / 字級 / 寬度 變動時重建（已用 harness 驗證捲動對齊與 clip 行為）。
 *
 * @param {Ref<HTMLElement>} textareaRef  scroller 元素（.transcript-display）
 * @param {Ref<Array>} segmentRanges      [{ segmentIndex, charStart, charEnd, start, end }]
 * @param {Ref<boolean>} enabled          是否啟用（showTimecodeMarkers && !isEditing && paragraph）
 * @param {Ref<*>} rebuildKey             任一會改變排版的反應式值（字級/字重/字體/內容）變動即重建
 */
export function useSegmentMarkerOverlay({ textareaRef, segmentRanges, enabled, rebuildKey }) {
  // [{ segmentIndex, start, top, left }]，top/left 為內容相對座標（px）
  const markers = ref([])

  let rafId = null
  let resizeObserver = null

  function rebuild() {
    rafId = null
    const el = textareaRef.value
    if (!enabled.value || !el) {
      if (markers.value.length) markers.value = []
      return
    }
    const ranges = segmentRanges.value
    if (!ranges || ranges.length === 0) {
      if (markers.value.length) markers.value = []
      return
    }
    const map = buildCharIndexMap(el)
    if (map.length === 0) {
      if (markers.value.length) markers.value = []
      return
    }

    const containerRect = el.getBoundingClientRect()
    const scrollTop = el.scrollTop
    const scrollLeft = el.scrollLeft
    const out = []
    for (const r of ranges) {
      // 取 segment 第一個字的 rect 當起點（collapsed range 在部分瀏覽器拿不到 rect）
      const range = charOffsetToRange(map, r.charStart, Math.min(r.charStart + 1, r.charEnd))
      if (!range) continue
      const rects = range.getClientRects()
      const rect = rects && rects.length ? rects[0] : null
      if (!rect) continue
      out.push({
        segmentIndex: r.segmentIndex,
        start: r.start,
        top: rect.top - containerRect.top + scrollTop,
        left: rect.left - containerRect.left + scrollLeft,
      })
    }
    markers.value = out
  }

  function scheduleRebuild() {
    if (rafId !== null) return
    rafId = requestAnimationFrame(rebuild)
  }

  function attachObserver() {
    if (resizeObserver || !textareaRef.value || typeof ResizeObserver === 'undefined') return
    // 容器寬度變動（面板縮放 / 視窗 resize）→ 文字 rewrap → 重建
    resizeObserver = new ResizeObserver(() => scheduleRebuild())
    resizeObserver.observe(textareaRef.value)
  }

  function detachObserver() {
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
    }
  }

  // 啟用狀態 / ranges / 排版鍵變動 → 等 DOM 更新後重建
  watch(
    [enabled, segmentRanges, () => rebuildKey?.value],
    () => {
      if (enabled.value) {
        attachObserver()
        nextTick(scheduleRebuild)
      } else {
        detachObserver()
        if (markers.value.length) markers.value = []
      }
    },
    { immediate: true }
  )

  onMounted(() => {
    if (enabled.value) {
      attachObserver()
      nextTick(scheduleRebuild)
    }
  })

  onUnmounted(() => {
    if (rafId !== null) cancelAnimationFrame(rafId)
    detachObserver()
  })

  return { markers, scheduleRebuild }
}
