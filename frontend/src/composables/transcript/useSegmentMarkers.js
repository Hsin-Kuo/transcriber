import { ref } from 'vue'

// 「至少一個有意義內容字元」的判定，用來跳過純標點/純空白 segment（例如 "。"）
// \p{P} 含全形與半形標點、\p{S} 含符號、\s 含空白、\u200B 是 zero-width space
const CONTENT_CHAR_RE = /[^\s\p{P}\p{S}\u200B]/u

// \u77ED\u6587\u5B57 segment\uFF08\u22642 \u5B57\uFF09\u8996\u70BA\u300C\u4E0D\u53EF\u4FE1 anchor\u300D\u7684 drift \u9580\u6ABB\u3002LLM \u5F37\u5316\u904E\u7A0B
// \u5076\u723E\u6703\u6084\u6084\u6539\u6389\u77ED\u5B57\uFF08\u4F8B\u5982\u300C\u90A3\u300D\u6D88\u5931\uFF09\uFF0C\u73FE\u6709 bidirectional \u6703\u88AB\u8FEB\u6311\u5F8C\u9762\u7684
// \u540C\u5B57 \u2192 lastSearchIndex \u8DF3\u904E\u982D \u2192 \u4E4B\u5F8C segments \u5168\u90E8\u5931\u914D cascade\u3002
// \u4FEE\u6CD5\uFF1A\u82E5\u77ED\u5B57 chosen \u8DDD local expected \u592A\u9060\uFF08> allowedDrift\uFF09\uFF0C\u8996\u70BA LLM
// \u6539\u5B57\u5F8C\u7684 spurious match\uFF0C\u8DF3\u904E\u8A72\u6BB5\uFF08\u4E0D\u6C61\u67D3 anchor\uFF0C\u4FDD\u7559\u9577\u5B57 anchor \u7D66\u5F8C\u7E8C\uFF09\u3002
const SHORT_TEXT_MAX_LEN = 2
const SHORT_DRIFT_MIN = 20 // \u81F3\u5C11\u5BB9\u5FCD 20 chars\uFF08cps \u4F30\u7B97\u5076\u6709\u5FAE\u8AA4\u5DEE\uFF09
const SHORT_DRIFT_TIME_FACTOR = 1.5 // \u984D\u5916\u5BB9\u5FCD timeDelta \u00D7 cps \u00D7 1.5

/**
 * 把 segments 對齊到 content text，回傳 marker 陣列（純函數，方便測試）。
 *
 * 策略：對每個 segment 在 [lastSearchIndex, ...) 範圍內找最靠近 ExpectedPosition
 * 的位置。ExpectedPosition 用**局部錨定**估算（而非全域累積）：
 *
 *   expected = lastSearchIndex + (seg.start - lastSearchTime) × charPerSecond
 *
 * 而不是 `seg.start × charPerSecond`。理由：中文逐字稿經標點強化後 content
 * 字元密度通常比真實 audio rate 高 10-15%，用 absolute seg.start × cps 算出
 * 的 expected 會穩定 over-shoot，造成緊接前段尾部的短重複字（例如使用者
 * 實測「？有，因為」中那個「有」）被推到更後面的同字位置。
 *
 * 改用 lastSearchIndex + 時間差 × cps：誤差只乘上「相鄰兩段的時間差」
 * （通常 < 1s），不再隨整段時間軸累積放大。
 *
 * 用 lastIndexOf + indexOf 雙向各找一個最近候選（而非枚舉所有候選）：
 *   - backward = content.lastIndexOf(text, expected)   ← expected 前最靠近
 *   - forward  = content.indexOf(text, expected+1)     ← expected 後最靠近
 * 選兩者裡離 expected 比較近、且 >= lastSearchIndex 的。
 *
 * 失配 segment（content 沒這段文字）**不**推進 lastSearchIndex / lastSearchTime，
 * 避免污染後續錨點。
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
  let lastSearchTime = 0 // 上一個成功匹配 segment 的 end time，當 local 錨點

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
      // 局部錨定 expected：用上一段成功匹配的 end time/pos 推算當前段位置，
      // 而不是 seg.start × cps（後者誤差會隨整段時間軸累積放大，標點強化
      // 造成 cps 高估時會穩定 over-shoot，緊接的短字會被推到後面的同字）
      const timeDelta = Math.max(0, seg.start - lastSearchTime)
      const expected = lastSearchIndex + timeDelta * charPerSecond
      const expectedInt = Math.floor(expected)

      const firstHit = contentLower.indexOf(textLower, lastSearchIndex)
      const backward = contentLower.lastIndexOf(textLower, expectedInt)
      const validBackward = backward >= lastSearchIndex ? backward : -1
      const forward = contentLower.indexOf(
        textLower,
        Math.max(lastSearchIndex, expectedInt + 1),
      )

      if (firstHit === -1) continue // 完全找不到 → 失配

      // 偵測 expected over-shoot：當 [lastSearchIndex, expected] 範圍內有
      // 多個候選且彼此相距遠（firstHit 跟 validBackward 距離 > 30 chars），
      // 代表 candidates 散落在 content 不同段落。「最靠 expected」的
      // validBackward 通常是錯的（後段同字 — cps 高估、silence/speaker tag
      // 導致 local 密度低於全域，expected 飄遠造成）。信時間軸 monotone 選
      // firstHit 較安全，避免 lastSearchIndex 跳過頭污染後續 cascade。
      // 經典 case：seg 2 silence (text="") 後的 seg 3，其 text 在 line 2
      // 和 line 3 各出現一次，bidirectional 會挑後者 → 之後 segments 全失配。
      const SPREAD_FOR_EARLIEST = 30
      if (
        validBackward !== -1 &&
        validBackward - firstHit > SPREAD_FOR_EARLIEST
      ) {
        chosen = firstHit
      } else if (validBackward === -1) {
        chosen = forward
      } else if (forward === -1) {
        chosen = validBackward
      } else {
        chosen =
          Math.abs(validBackward - expected) <= Math.abs(forward - expected)
            ? validBackward
            : forward
      }

      // 短字 spurious match 防護：當 ≤2 字段唯一找到的位置距 expected 過遠，
      // 多半是 LLM 把該段原本的位置改掉（或改字）後，演算法被迫挑到很遠的
      // 同字。直接視為失配以避免污染 anchor → 後續 segments 仍能用上次成功
      // 匹配的長字 anchor 繼續對齊。
      if (text.length <= SHORT_TEXT_MAX_LEN) {
        const allowedDrift = Math.max(
          SHORT_DRIFT_MIN,
          timeDelta * charPerSecond * SHORT_DRIFT_TIME_FACTOR,
        )
        if (Math.abs(chosen - expected) > allowedDrift) continue
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
    if (Number.isFinite(seg.end)) lastSearchTime = seg.end
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
