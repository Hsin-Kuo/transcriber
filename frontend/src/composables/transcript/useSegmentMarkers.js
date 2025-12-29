import { ref, watch } from 'vue'

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
    if (!segments || segments.length === 0 || !content) {
      segmentMarkers.value = []
      return
    }

    const markers = []
    let lastSearchIndex = 0 // 上一次成功搜尋到的位置
    let lastSuccessIndex = 0 // 上一次成功搜尋的索引

    segments.forEach((segment, index) => {
      const text = segment.text?.trim()

      // 跳過6個字以內的segment
      if (!text || text.length <= 6) {
        return
      }

      // 從上一次成功搜尋的位置之後開始搜尋
      const searchStartIndex = lastSearchIndex
      const foundIndex = content.indexOf(text, searchStartIndex)

      if (foundIndex !== -1) {
        // 找到匹配
        markers.push({
          segmentIndex: index,
          text: text,
          start: segment.start,
          end: segment.end,
          textStartIndex: foundIndex,
          textEndIndex: foundIndex + text.length
        })

        // 更新搜尋位置
        lastSearchIndex = foundIndex + text.length
        lastSuccessIndex = index
      } else {
        // 如果沒找到，下一個segment從上一次成功的位置重新開始搜尋
        lastSearchIndex = lastSearchIndex
      }
    })

    segmentMarkers.value = markers
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
    formatTime
  }
}
