import { ref } from 'vue'

// 「至少一個有意義內容字元」的判定，用來跳過純標點/純空白 segment（例如 "。"）
// \p{P} 含全形與半形標點、\p{S} 含符號、\s 含空白、\u200B 是 zero-width space
const CONTENT_CHAR_RE = /[^\s\p{P}\p{S}\u200B]/u

/**
 * 把 segments 對齊到 content text，回傳 marker 陣列（純函數，方便測試）。
 *
 * 策略：對每個 segment 在 [lastSearchIndex, ...) 範圍內找最靠近 ExpectedPosition
 * 的位置。ExpectedPosition 由 segment.start × charPerSecond 線性換算
 * （charPerSecond = content.length / totalDuration），假設內容字元密度對
 * 時間軸近似線性 —— 中文逐字稿即使有標點強化造成 ±10% 偏差仍夠用。
 *
 * 用 lastIndexOf + indexOf 雙向各找一個最近候選（而非枚舉所有候選）：
 *   - backward = content.lastIndexOf(text, expected)   ← expected 前最靠近
 *   - forward  = content.indexOf(text, expected+1)     ← expected 後最靠近
 * 選兩者裡離 expected 比較近、且 >= lastSearchIndex 的。這保證在 constraint
 * window 內拿到**最佳**位置，不會被上限式 candidate 收集（之前 MAX_CANDIDATES=16）
 * 拖累。
 *
 * 對「短重複文字」（如「有」「對」在整篇 transcript 出現上百次）的 segment：
 * 舊版收集前 16 個 candidate 全都在 lastSearchIndex 附近、離真實 expected 很遠，
 * 被迫選錯位置，緩慢推進 lastSearchIndex，最終越過該 segment 真實位置 → 之後
 * 的 segments 全部 indexOf 回 -1 失配 → cascade 失敗。雙向搜尋一步到位、無上限。
 *
 * 失配 segment（content 沒這段文字）**不**推進 lastSearchIndex，避免污染後續。
 *
 * 同時拿掉舊版「跳過 ≤6 字 segment」的限制 —— 中文逐字稿大量短句
 * （「對」「好的」「是」），原本完全無法 Alt-click 跳轉，是功能缺口。
 * 純標點 segment 仍跳過（無意義 anchor）。
 *
 * @param {Array} segments  - [{ text, start, end, ... }]
 * @param {string} content
 * @returns {Array}         - [{ segmentIndex, text, start, end, textStartIndex, textEndIndex }]
 */
export function alignSegmentsToContent(segments, content) {
  if (!segments?.length || !content) return []

  const contentLower = content.toLowerCase()

  // 從末段往前找第一個有效 end 作為總時長（一般 segments 按時間遞增，但兜底）
  let totalDuration = 0
  for (let i = segments.length - 1; i >= 0; i--) {
    const e = segments[i]?.end
    if (Number.isFinite(e) && e > 0) {
      totalDuration = e
      break
    }
  }
  const charPerSecond = totalDuration > 0 ? content.length / totalDuration : 0

  const markers = []
  let lastSearchIndex = 0

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const text = (seg?.text ?? '').trim()
    if (!text) continue
    if (!CONTENT_CHAR_RE.test(text)) continue // 全標點/空白 segment 跳過

    const textLower = text.toLowerCase()
    const hasTime =
      charPerSecond > 0 && Number.isFinite(seg.start) && seg.start >= 0

    let chosen
    if (!hasTime) {
      // 沒時間軸資訊：退化到貪婪首匹配
      const idx = contentLower.indexOf(textLower, lastSearchIndex)
      if (idx === -1) continue
      chosen = idx
    } else {
      // 雙向搜尋 expected 兩側最近候選，constraint 為 >= lastSearchIndex
      const expected = seg.start * charPerSecond
      const expectedInt = Math.floor(expected)

      const backward = contentLower.lastIndexOf(textLower, expectedInt)
      const validBackward = backward >= lastSearchIndex ? backward : -1
      const forward = contentLower.indexOf(
        textLower,
        Math.max(lastSearchIndex, expectedInt + 1),
      )

      if (validBackward === -1 && forward === -1) continue // 失配
      if (validBackward === -1) chosen = forward
      else if (forward === -1) chosen = validBackward
      else
        chosen =
          Math.abs(validBackward - expected) <= Math.abs(forward - expected)
            ? validBackward
            : forward
    }

    markers.push({
      segmentIndex: i,
      text,
      start: seg.start,
      end: seg.end,
      textStartIndex: chosen,
      textEndIndex: chosen + text.length,
    })

    lastSearchIndex = chosen + text.length
  }

  return markers
}

/**
 * 用於在段落模式中標記segments位置的composable
 */
export function useSegmentMarkers() {
  // 存儲匹配到的標記位置
  const segmentMarkers = ref([])

  // textarea元素引用
  const textareaRef = ref(null)

  /**
   * 在文字中搜尋segment並生成標記
   * @param {Array} segments - segment數組
   * @param {string} content - 逐字稿內容
   */
  function generateSegmentMarkers(segments, content) {
    segmentMarkers.value = alignSegmentsToContent(segments, content)
  }

  /**
   * 計算標記在textarea中的視覺位置
   * @param {number} textIndex - 文字索引位置
   * @returns {Object} { top, left } 像素位置
   */
  function calculateMarkerPosition(textIndex) {
    if (!textareaRef.value) {
      return { top: 0, left: 0 }
    }

    const textarea = textareaRef.value
    const content = textarea.value

    // 創建一個臨時的測量元素
    const measureDiv = document.createElement('div')
    measureDiv.style.cssText = `
      position: absolute;
      visibility: hidden;
      white-space: pre-wrap;
      word-wrap: break-word;
      font-family: ${window.getComputedStyle(textarea).fontFamily};
      font-size: ${window.getComputedStyle(textarea).fontSize};
      line-height: ${window.getComputedStyle(textarea).lineHeight};
      padding: ${window.getComputedStyle(textarea).padding};
      width: ${textarea.clientWidth}px;
    `

    // 插入到該位置之前的文字
    measureDiv.textContent = content.substring(0, textIndex)
    document.body.appendChild(measureDiv)

    // 獲取高度（即top位置）
    const top = measureDiv.offsetHeight

    // 獲取最後一行的寬度
    const lines = measureDiv.textContent.split('\n')
    const lastLine = lines[lines.length - 1] || ''
    measureDiv.textContent = lastLine
    const left = measureDiv.offsetWidth

    document.body.removeChild(measureDiv)

    return { top, left }
  }

  /**
   * 格式化時間戳
   * @param {number} seconds - 秒數
   * @returns {string} 格式化的時間字串
   */
  function formatTime(seconds) {
    const minutes = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  return {
    segmentMarkers,
    textareaRef,
    generateSegmentMarkers,
    calculateMarkerPosition,
    formatTime,
  }
}
