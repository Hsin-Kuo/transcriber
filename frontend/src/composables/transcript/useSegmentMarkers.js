import { ref } from 'vue'

// 「至少一個有意義內容字元」的判定，用來跳過純標點/純空白 segment（例如 "。"）
// \p{P} 含全形與半形標點、\p{S} 含符號、\s 含空白、\u200B 是 zero-width space
const CONTENT_CHAR_RE = /[^\s\p{P}\p{S}\u200B]/u

// drift guard \u53C3\u6578\uFF1Achosen \u8DDD expected \u592A\u9060\u6642\uFF0C\u8996\u70BA\u300CLLM \u6539\u5BEB\u8A72\u6BB5\u5F8C indexOf
// \u4E00\u8DEF\u5F80\u5F8C\u6488\u5230\u7684\u5DE7\u5408\u540C\u5B57\u300D\uFF0C\u8DF3\u904E\u8A72\u6BB5\uFF08\u4E0D\u6C61\u67D3 anchor\uFF0C\u5F8C\u7E8C segments \u4ECD\u80FD\u5C0D\u9F4A\uFF09\u3002
// allowedDrift \u4F9D segment \u9577\u5EA6\u5206\u5169\u7D1A\uFF1A\u2264SHORT_TEXT_MAX_LEN \u5B57\u7684\u77ED\u6BB5\u6975\u6613\u5DE7\u5408
// \u91CD\u8907\uFF0C\u9580\u6ABB\u6536\u7DCA\uFF1B\u8F03\u9577\u7684\u6BB5\u4EE5\u300C\u7D04 1 \u5206\u9418\u5C0D\u8A71\u7684\u6587\u5B57\u91CF\u300D(cps \u00D7 SEARCH_WINDOW_
// SECONDS) \u4F5C\u70BA\u5411\u5F8C\u641C\u5C0B\u7684\u7BC4\u570D\u4E0A\u9650 \u2014\u2014 \u8D85\u51FA\u5373\u8996\u70BA\u627E\u4E0D\u5230\uFF0C\u800C\u975E\u7121\u9650\u641C\u5230\u6587\u672B\u3002
const SHORT_TEXT_MAX_LEN = 2 // \u300C\u77ED\u6BB5\u300D\u4E0A\u9650\uFF1A\u22642 \u5B57\u8996\u70BA\u4E0D\u53EF\u4FE1 anchor
const SHORT_DRIFT_MIN = 20 // drift \u4E0B\u9650\uFF08cps \u4F30\u7B97\u5FAE\u8AA4\u5DEE / tiny-cps \u515C\u5E95\uFF09
const SHORT_DRIFT_TIME_FACTOR = 1.5 // \u96A8 timeDelta \u653E\u5BEC\uFF1AtimeDelta \u00D7 cps \u00D7 1.5
const SEARCH_WINDOW_SECONDS = 60 // \u5411\u5F8C\u641C\u5C0B\u7BC4\u570D\u4E0A\u9650 \u2248 1 \u5206\u9418\u5C0D\u8A71\u7684\u6587\u5B57\u91CF

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
 * 快速路徑：若自上次成功匹配以來沒跳過任何「有內容」的 segment，這一段
 * 在文字上就緊接前一段，直接取 firstHit（[lastSearchIndex, ...) 內第一個
 * 匹配）。expected 只在「中間有內容段失配」時才需要。理由：相鄰兩段之間
 * 的時間差多半是純停頓（無對應文字），用 timeDelta × cps 換算會虛增出
 * 不存在的位移，把緊接的同字片語推到後面的重複位置（實測：「這個是」後
 * 緊接的「AI的課」被選到第二次出現的「AI的課」）。
 *
 * 中間有內容段失配時才用 lastIndexOf + indexOf 雙向各找一個最近候選：
 *   - backward = content.lastIndexOf(text, expected)   ← expected 前最靠近
 *   - forward  = content.indexOf(text, expected+1)     ← expected 後最靠近
 * 選兩者裡離 expected 比較近、且 >= lastSearchIndex 的。
 *
 * 失配 segment（content 沒這段文字）**不**推進 lastSearchIndex / lastSearchTime，
 * 避免污染後續錨點。
 *
 * 向後搜尋範圍上限：indexOf 預設會搜到文末，若某段被 LLM 改寫、其文字只在
 * 很後面巧合出現，會撈到那個遠處位置 → lastSearchIndex 跳過頭 → 後續全部
 * cascade 失配。因此 chosen 距 expected 超過 allowedDrift 時一律當失配
 * （≤2 字短段門檻收緊；3 字以上以 ≈1 分鐘對話的文字量為搜尋範圍上限）。
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
  // 自上次成功匹配以來，是否跳過了「有內容」的 segment（失配 / 短字 drift 拒絕）。
  // false 代表這一段在文字上緊接前一段 → 可直接取 firstHit，不需 expected 推估。
  // silence / 純標點段不算（它們本來就沒有對應的 content 文字）。
  let skippedContentSinceMatch = false

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const text = (seg?.text ?? '').trim()
    if (!text || !CONTENT_CHAR_RE.test(text)) {
      // 空白/純標點 segment 跳過，但仍推進時間錨點：
      // silence 等無文字段仍佔據真實音訊時間，若不更新 lastSearchTime，
      // 下一個 segment 的 timeDelta 會被虛增，導致 expected 過度向後偏移，
      // 在文字有重複出現時（如兩處「SSK」）選到錯誤的後者。
      if (Number.isFinite(seg?.end)) lastSearchTime = seg.end
      continue
    }

    const textLower = text.toLowerCase()
    const hasTime =
      charPerSecond > 0 && Number.isFinite(seg.start) && seg.start >= 0

    let chosen
    if (!hasTime) {
      // 沒時間軸資訊：退化到貪婪首匹配
      const idx = contentLower.indexOf(textLower, lastSearchIndex)
      if (idx === -1) {
        skippedContentSinceMatch = true
        continue
      }
      chosen = idx
    } else {
      // 局部錨定 expected：用上一段成功匹配的 end time/pos 推算當前段位置，
      // 而不是 seg.start × cps（後者誤差會隨整段時間軸累積放大，標點強化
      // 造成 cps 高估時會穩定 over-shoot，緊接的短字會被推到後面的同字）
      const timeDelta = Math.max(0, seg.start - lastSearchTime)
      const expected = lastSearchIndex + timeDelta * charPerSecond
      const expectedInt = Math.floor(expected)

      const firstHit = contentLower.indexOf(textLower, lastSearchIndex)
      if (firstHit === -1) {
        // 完全找不到 → 失配
        skippedContentSinceMatch = true
        continue
      }

      if (!skippedContentSinceMatch) {
        // 自上次成功匹配以來未跳過任何有內容的 segment → 這一段在文字上
        // 緊接前一段，直接取最近的 firstHit。避免相鄰兩段之間的純停頓
        // 時間被 cps 放大成 expected over-shoot，把緊接的同字片語推到
        // 後面的重複位置（實測：「這個是」後緊接的「AI的課」被選到後面
        // 第二次出現的「AI的課」）。短字 drift guard 仍會在下方把離 expected
        // 過遠的 firstHit 當失配，所以 LLM 改掉短字的 case 不受影響。
        chosen = firstHit
      } else {
        // 中間有內容段被跳過（失配），當前段位置不確定 → 用 expected 雙向定位。
        const backward = contentLower.lastIndexOf(textLower, expectedInt)
        const validBackward = backward >= lastSearchIndex ? backward : -1
        const forward = contentLower.indexOf(
          textLower,
          Math.max(lastSearchIndex, expectedInt + 1),
        )

        // 偵測 expected over-shoot：當 [lastSearchIndex, expected] 範圍內有
        // 多個候選且彼此相距遠（firstHit 跟 validBackward 距離 > 30 chars），
        // 代表 candidates 散落在 content 不同段落。「最靠 expected」的
        // validBackward 通常是錯的（後段同字 — cps 高估、silence/speaker tag
        // 導致 local 密度低於全域，expected 飄遠造成）。信時間軸 monotone 選
        // firstHit 較安全，避免 lastSearchIndex 跳過頭污染後續 cascade。
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
      }

      // spurious match 防護：chosen 距 expected 過遠 → 多半是 LLM 改寫該段
      // 後，indexOf 一路往後撈到的巧合同字。視為失配（不污染 anchor），避免
      // lastSearchIndex 跳到很後面、害後續 segments 全部 cascade 失配。
      // allowedDrift 依長度分兩級：
      //   - ≤2 字短段：極易巧合重複，門檻收緊（不吃 1 分鐘窗）。
      //   - 3 字以上：加入「1 分鐘對話的文字量」(cps × SEARCH_WINDOW_SECONDS)
      //     作為向後搜尋的範圍上限。
      // 兩級都對 timeDelta × cps 取 max：一長串失配後 expected 外推誤差變大，
      // 門檻同步放寬，真實位置被推遠的合法遠處匹配仍會被接受。
      const allowedDrift =
        text.length <= SHORT_TEXT_MAX_LEN
          ? Math.max(
              SHORT_DRIFT_MIN,
              timeDelta * charPerSecond * SHORT_DRIFT_TIME_FACTOR,
            )
          : Math.max(
              SHORT_DRIFT_MIN,
              charPerSecond * SEARCH_WINDOW_SECONDS,
              timeDelta * charPerSecond * SHORT_DRIFT_TIME_FACTOR,
            )
      if (Math.abs(chosen - expected) > allowedDrift) {
        skippedContentSinceMatch = true
        continue
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
    skippedContentSinceMatch = false
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
