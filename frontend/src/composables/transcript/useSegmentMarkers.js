import { ref } from 'vue'

// 多候選位置的搜尋上限，避免短重複字（中文常見「對對對」「然後」）退化成 O(N²)
const MAX_CANDIDATES = 16

// 「至少一個有意義內容字元」的判定，用來跳過純標點/純空白 segment（例如 "。"）
// \p{P} 含全形與半形標點、\p{S} 含符號、\s 含空白、\u200B 是 zero-width space
const CONTENT_CHAR_RE = /[^\s\p{P}\p{S}\u200B]/u

/**
 * 把 segments 對齊到 content text，回傳 marker 陣列（純函數，方便測試）。
 *
 * 策略：用 indexOf 從 lastSearchIndex 之後找候選位置，相對於原本的「貪婪首
 * 個匹配」做兩個改善：
 *   1. 失配的 segment **不**推進 lastSearchIndex —— 避免後續 segment 因
 *      lastSearchIndex 殘留在錯誤位置而對到錯字。
 *   2. 多候選時用 segment.start 時間軸線性換算的 ExpectedPosition 選最近
 *      者（假設 content 字元密度對時間軸近似線性，標點密度差異容忍 ±10%
 *      內）。對「短重複文字 + 中間 segment 失配」這類過往會錯位的情境，
 *      時間軸資訊足夠把後續 segment 鎖到對的重複出現位置。
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
    const expected =
      charPerSecond > 0 && Number.isFinite(seg.start) && seg.start >= 0
        ? seg.start * charPerSecond
        : null

    // 收集候選：從 lastSearchIndex 開始連續 indexOf，上限 MAX_CANDIDATES，
    // 一旦越過 expected 就停（之後只會更遠）
    const candidates = []
    let from = lastSearchIndex
    while (candidates.length < MAX_CANDIDATES) {
      const idx = contentLower.indexOf(textLower, from)
      if (idx === -1) break
      candidates.push(idx)
      if (expected !== null && idx > expected) break
      from = idx + 1
    }

    if (candidates.length === 0) continue // 失配 → 不推進 lastSearchIndex

    // 選擇：單候選或沒時間軸資訊 → 取首個；否則挑距 expected 最近
    let chosen
    if (candidates.length === 1 || expected === null) {
      chosen = candidates[0]
    } else {
      chosen = candidates[0]
      let bestDist = Math.abs(chosen - expected)
      for (let k = 1; k < candidates.length; k++) {
        const d = Math.abs(candidates[k] - expected)
        if (d < bestDist) {
          bestDist = d
          chosen = candidates[k]
        }
      }
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
