import { ref } from 'vue'

/**
 * 時間碼標記管理 Composable
 *
 * 職責：
 * - 生成時間碼標記（用於段落模式的滾動同步）
 * - 追蹤當前激活的時間碼
 * - 同步滾動位置與時間碼
 */
export function useTimecodeMarkers() {
  // 時間碼標記
  const timecodeMarkers = ref([])
  const activeTimecodeIndex = ref(-1)

  // 元素引用
  const textarea = ref(null)

  /**
   * 格式化時間碼顯示
   * @param {Number} seconds - 秒數
   * @returns {String} 格式化後的時間碼
   */
  function formatTimecode(seconds) {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const secs = Math.floor(seconds % 60)
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  /**
   * 生成時間碼標記
   * @param {Array} segmentList - segment 列表
   * @param {String} transcriptContent - 逐字稿內容
   * @returns {Array} 時間碼標記列表
   */
  function generateTimecodeMarkers(segmentList, transcriptContent) {
    if (!segmentList || segmentList.length === 0) return []

    const markers = []
    const INTERVAL = 15 // 每 15 秒一個標記
    const sortedSegments = [...segmentList].sort((a, b) => a.start - b.start)
    const segmentPositions = []
    let cumulativeChars = 0

    // 找出每個 segment 在文本中的位置
    for (const segment of sortedSegments) {
      const segmentText = segment.text.trim().replace(/\s+/g, ' ')
      let charStart = transcriptContent.indexOf(segment.text.trim(), cumulativeChars)
      if (charStart === -1) {
        charStart = transcriptContent.indexOf(segmentText, cumulativeChars)
      }
      if (charStart !== -1) {
        segmentPositions.push({
          start: segment.start,
          end: segment.end,
          charStart: charStart,
          charEnd: charStart + segmentText.length,
          text: segmentText
        })
        cumulativeChars = charStart + segmentText.length
      }
    }

    const totalChars = transcriptContent.length
    const maxTime = sortedSegments[sortedSegments.length - 1].end
    const usedSegments = new Set()
    const targetTimes = []

    // 生成目標時間點
    for (let t = 0; t <= maxTime; t += INTERVAL) {
      targetTimes.push(t)
    }

    // 為每個目標時間點找到最近的 segment
    for (const targetTime of targetTimes) {
      let closestSegment = null
      let minDistance = Infinity
      for (const seg of segmentPositions) {
        if (usedSegments.has(seg)) continue
        const distance = Math.abs(seg.start - targetTime)
        if (distance < minDistance && distance < INTERVAL * 2) {
          minDistance = distance
          closestSegment = seg
        }
      }
      if (closestSegment) {
        usedSegments.add(closestSegment)
        markers.push({
          time: closestSegment.start,
          label: formatTimecode(closestSegment.start),
          charPosition: closestSegment.charStart
        })
      }
    }

    // 排序並計算位置百分比
    markers.sort((a, b) => a.time - b.time)
    for (let i = 0; i < markers.length; i++) {
      markers[i].positionPercent = totalChars > 0 ? (markers[i].charPosition / totalChars) * 100 : 0
    }

    return markers
  }

  /**
   * 同步滾動位置與時間碼
   */
  function syncScroll() {
    if (!textarea.value || timecodeMarkers.value.length === 0) return

    const scrollTop = textarea.value.scrollTop
    const scrollHeight = textarea.value.scrollHeight
    const clientHeight = textarea.value.clientHeight

    if (scrollHeight <= clientHeight) {
      activeTimecodeIndex.value = 0
      return
    }

    const scrollPercent = scrollTop / (scrollHeight - clientHeight)
    const contentLength = textarea.value.value.length
    const estimatedCharPos = Math.floor(scrollPercent * contentLength)

    let closestIndex = 0
    let minDistance = Infinity

    for (let i = 0; i < timecodeMarkers.value.length; i++) {
      const distance = Math.abs(timecodeMarkers.value[i].charPosition - estimatedCharPos)
      if (distance < minDistance) {
        minDistance = distance
        closestIndex = i
      }
    }

    if (closestIndex !== activeTimecodeIndex.value) {
      activeTimecodeIndex.value = closestIndex
      console.log('🕐 時間碼更新:',
        timecodeMarkers.value[closestIndex].label,
        `(${closestIndex + 1}/${timecodeMarkers.value.length})`,
        `字元位置: ${estimatedCharPos}/${contentLength}`
      )
    }
  }

  return {
    // 狀態
    timecodeMarkers,
    activeTimecodeIndex,

    // 元素引用
    textarea,

    // 方法
    formatTimecode,
    generateTimecodeMarkers,
    syncScroll
  }
}
