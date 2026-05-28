import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'

/**
 * 把任意 flex-wrap 容器限制成最多兩排，超出時以 max-height 截掉，
 * 並提供「顯示更多 / 收合」狀態切換。
 *
 * 用法：
 *   const { containerRef, contentStyle, overflowing, isCollapsed, toggle } =
 *     useCollapsibleRows({
 *       itemSelector: '.quick-tag-btn',
 *       watchSources: [() => availableQuickTags.value.length],
 *     })
 *
 *   <template>
 *     <div :ref="containerRef" :style="contentStyle">
 *       <button class="quick-tag-btn" v-for="...">...</button>
 *     </div>
 *     <button v-if="overflowing" @click="toggle">
 *       {{ isCollapsed ? '顯示更多' : '收合' }}
 *     </button>
 *   </template>
 *
 * 量測策略：
 *   1) 用 getBoundingClientRect 拿到每個 item 的 top/bottom（即使被
 *      overflow:hidden 視覺隱藏，layout 位置仍存在）
 *   2) Tolerance-based grouping：top 差距 > 8px 才算新 row，吸收 sub-pixel
 *      rendering 偏移，避免同 row items 被誤切成兩 row（曾踩過的 bug）
 *   3) twoRowsPx = 第 2 row 的 bottom（容器內 y 座標），即「顯示兩排所需高度」
 *
 * @param {object} opts
 * @param {string} opts.itemSelector
 *   容器內每個項目的 CSS selector（用來找出 row 邊界）
 * @param {() => boolean} [opts.forceExpand]
 *   回傳 true 時強制展開（例如編輯模式不該截斷）
 * @param {Array<() => any>} [opts.watchSources]
 *   reactive sources，變化時自動 remeasure（例如 tag 列表變更）
 */
export function useCollapsibleRows(opts) {
  const itemSelector = opts.itemSelector
  const forceExpand = opts.forceExpand || (() => false)
  const watchSources = opts.watchSources || []

  const containerRef = ref(null)
  const isCollapsed = ref(true)
  const overflowing = ref(false)
  const twoRowsPx = ref(80) // fallback；mount 後依實測動態更新
  let resizeObserver = null

  const shouldCollapse = computed(
    () => overflowing.value && isCollapsed.value && !forceExpand()
  )

  const contentStyle = computed(() =>
    shouldCollapse.value
      ? { maxHeight: `${twoRowsPx.value}px`, overflow: 'hidden' }
      : null
  )

  async function measure() {
    await nextTick()
    // 雙 RAF：等 CSS transition 與 DOM 全部 commit 後再測量
    await new Promise(resolve => requestAnimationFrame(resolve))
    await new Promise(resolve => requestAnimationFrame(resolve))

    if (!containerRef.value) return

    const items = containerRef.value.querySelectorAll(itemSelector)
    if (items.length === 0) {
      overflowing.value = false
      return
    }

    const containerTop = containerRef.value.getBoundingClientRect().top

    const itemRects = []
    items.forEach(item => {
      const rect = item.getBoundingClientRect()
      itemRects.push({
        top: rect.top - containerTop,
        bottom: rect.bottom - containerTop,
      })
    })
    itemRects.sort((a, b) => a.top - b.top)

    // Tolerance-based grouping：top 差距 > 8px 才算新 row。
    // 避免 sub-pixel rendering（0.0 / 0.3 / 0.5）把同一 row 誤切成多 row。
    // 8px << 最小 flex gap + row height，不會誤併兩 row。
    const ROW_TOLERANCE = 8
    const rowBottoms = []
    let lastRowTop = -Infinity
    for (const { top, bottom } of itemRects) {
      if (top - lastRowTop > ROW_TOLERANCE) {
        lastRowTop = top
        rowBottoms.push(bottom)
      } else {
        rowBottoms[rowBottoms.length - 1] = Math.max(
          rowBottoms[rowBottoms.length - 1],
          bottom
        )
      }
    }

    const rowCount = rowBottoms.length
    overflowing.value = rowCount > 2

    if (rowCount >= 2) {
      twoRowsPx.value = Math.ceil(rowBottoms[1])
    } else if (rowCount === 1) {
      twoRowsPx.value = Math.ceil(rowBottoms[0])
    }
  }

  function toggle() {
    isCollapsed.value = !isCollapsed.value
  }

  function attachObserver(el) {
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
    }
    if (el && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => measure())
      resizeObserver.observe(el)
    }
  }

  // 監聽 containerRef：consumer 元件若是 v-if mount，ref 會在掛載瞬間從
  // null → element，這時才掛 observer + 跑初次 measure；
  // v-if 解除後 ref 變回 null，順手把 observer 拆掉避免 leak。
  watch(
    containerRef,
    (el) => {
      attachObserver(el)
      if (el) measure()
    },
    { flush: 'post', immediate: true }
  )

  onBeforeUnmount(() => {
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
    }
  })

  // 外部反應性來源變化時 remeasure（如 item 列表變動、編輯模式切換）
  if (watchSources.length > 0) {
    watch(
      watchSources,
      () => measure(),
      { flush: 'post' }
    )
  }

  return {
    containerRef,
    contentStyle,
    overflowing,
    isCollapsed,
    shouldCollapse,
    toggle,
    remeasure: measure,
  }
}
