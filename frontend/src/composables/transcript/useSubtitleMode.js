import { ref, computed } from 'vue'

/**
 * 字幕模式處理 Composable
 *
 * 職責：
 * - 管理字幕顯示模式（時間格式、疏密度）
 * - 合併 segments 為顯示用的 groups
 * - 處理字幕編輯和更新
 * - 格式化時間戳
 */
export function useSubtitleMode(segments) {
  // 字幕控制狀態
  const timeFormat = ref('start')       // 'start' | 'range'
  const densityThreshold = ref(3.0)     // 強制分開的間隔（秒），範圍 0.0-120.0

  // 檢測是否有說話者資訊
  const hasSpeakerInfo = computed(() => {
    if (!segments.value || segments.value.length === 0) return false
    return segments.value.some(seg => seg.speaker !== undefined && seg.speaker !== null)
  })

  /**
   * 合併 segments 演算法
   * @param {Array} segmentList - segment 列表
   * @param {Number} thresholdSeconds - 疏密度閾值（秒）
   * @param {Boolean} hasSpeaker - 是否有講者資訊
   * @returns {Array} 合併後的 groups
   */
  function mergeSegmentsByDensity(segmentList, thresholdSeconds, hasSpeaker) {
    if (!segmentList || segmentList.length === 0) return []

    const sortedSegments = [...segmentList].sort((a, b) => a.start - b.start)
    const groups = []
    let currentGroup = null
    const gaps = []

    for (let i = 0; i < sortedSegments.length; i++) {
      const segment = sortedSegments[i]

      if (!currentGroup) {
        currentGroup = {
          id: `group_${i}_${segment.start}`,
          startTime: segment.start,
          endTime: segment.end,
          speaker: segment.speaker || null,
          segments: [segment],
          combinedText: segment.text.trim(),
          edited: false
        }
      } else {
        const speakerMatch = !hasSpeaker || (segment.speaker === currentGroup.speaker)

        // 計算如果加入這個 segment，group 的總時長
        const groupDuration = segment.end - currentGroup.startTime
        gaps.push(groupDuration)

        // 疏密度邏輯
        const shouldSplit = !speakerMatch || (thresholdSeconds === 0) || (groupDuration >= thresholdSeconds)

        if (shouldSplit) {
          groups.push(currentGroup)
          currentGroup = {
            id: `group_${i}_${segment.start}`,
            startTime: segment.start,
            endTime: segment.end,
            speaker: segment.speaker || null,
            segments: [segment],
            combinedText: segment.text.trim(),
            edited: false
          }
        } else {
          currentGroup.endTime = segment.end
          currentGroup.segments.push(segment)
          currentGroup.combinedText += ' ' + segment.text.trim()
        }
      }
    }

    // 統計間隔（僅在有間隔時）
    if (gaps.length > 0) {
      const avgGap = (gaps.reduce((a, b) => a + b, 0) / gaps.length).toFixed(2)
      const minGap = Math.min(...gaps).toFixed(2)
      const maxGap = Math.max(...gaps).toFixed(2)

      const gap0 = gaps.filter(g => g === 0).length
      const gapLess01 = gaps.filter(g => g > 0 && g < 0.1).length
      const gapLess1 = gaps.filter(g => g >= 0.1 && g < 1).length
      const gapLess5 = gaps.filter(g => g >= 1 && g < 5).length
      const gap5Plus = gaps.filter(g => g >= 5).length

      console.log(`  📊 間隔統計: 平均 ${avgGap}s, 最小 ${minGap}s, 最大 ${maxGap}s | 閾值: ${thresholdSeconds}s`)
      console.log(`  📊 間隔分布: =0 (${gap0}) | 0-0.1s (${gapLess01}) | 0.1-1s (${gapLess1}) | 1-5s (${gapLess5}) | ≥5s (${gap5Plus})`)
    }

    if (currentGroup) groups.push(currentGroup)
    return groups
  }

  /**
   * 合併後的 segments（自動響應疏密度變化）
   */
  const groupedSegments = computed(() => {
    console.log(`🎯 [groupedSegments] 觸發計算 - densityThreshold: ${densityThreshold.value}`)
    const groups = mergeSegmentsByDensity(
      segments.value,
      densityThreshold.value,
      hasSpeakerInfo.value
    )
    console.log(`🔧 疏密度: ${densityThreshold.value}s | Segments: ${segments.value?.length || 0} → Groups: ${groups.length}`)
    return groups
  })

  /**
   * 時間格式化函數
   * @param {Number} seconds - 秒數
   * @param {String} format - 格式 ('start' | 'range')
   * @param {Number} endSeconds - 結束時間（range 格式使用）
   * @returns {String} 格式化後的時間字串
   */
  function formatTimestamp(seconds, format, endSeconds) {
    const formatTime = (sec) => {
      const h = Math.floor(sec / 3600)
      const m = Math.floor((sec % 3600) / 60)
      const s = Math.floor(sec % 60)

      if (h > 0) {
        return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      }
      return `${m}:${String(s).padStart(2, '0')}`
    }

    if (format === 'start') {
      return formatTime(seconds)
    } else {
      return `${formatTime(seconds)} - ${formatTime(endSeconds)}`
    }
  }

  /**
   * 更新字幕表格列內容
   * @param {String} groupId - group ID
   * @param {Event} event - blur 事件
   */
  function updateRowContent(groupId, event) {
    const group = groupedSegments.value.find(g => g.id === groupId)
    if (!group) return

    const tdElement = event.target
    const spanElements = tdElement.querySelectorAll('.segment-span')

    let hasChanges = false

    // 遍歷每個 span，更新對應的 segment
    spanElements.forEach((span, index) => {
      if (index < group.segments.length) {
        const newText = span.textContent.trim()
        const originalText = group.segments[index].text.trim()

        if (newText !== originalText) {
          group.segments[index].text = newText
          hasChanges = true
          console.log(`✏️ Segment ${index} 已修改: "${originalText}" → "${newText}"`)
        }
      }
    })

    if (hasChanges) {
      group.edited = true
      group.combinedText = group.segments.map(s => s.text.trim()).join(' ')
      console.log(`✅ Group ${groupId} 已標記為已編輯`)
    }
  }

  /**
   * 將表格內容轉為純文字
   * @param {Array} groups - group 列表
   * @param {Object} speakerNames - 講者名稱對應（可選）
   * @returns {String} 純文字內容
   */
  function convertTableToPlainText(groups, speakerNames = {}) {
    return groups.map(group => {
      if (group.speaker) {
        const displayName = speakerNames[group.speaker] || group.speaker
        const speakerPrefix = `[${displayName}] `
        return `${speakerPrefix}${group.combinedText.trim()}`
      } else {
        return group.combinedText.trim()
      }
    }).join('\n\n')
  }

  /**
   * 將編輯後的 groups 重建回 segments
   * @param {Array} groups - group 列表
   * @returns {Array} 重建的 segments
   */
  function reconstructSegmentsFromGroups(groups) {
    const reconstructedSegments = []

    for (const group of groups) {
      reconstructedSegments.push(...group.segments)
    }

    console.log(`🔄 重建 segments: ${groups.length} groups → ${reconstructedSegments.length} segments`)
    return reconstructedSegments
  }

  /**
   * 生成字幕格式的文本（用於下載 TXT）
   * @param {Array} groups - group 列表
   * @param {String} format - 時間格式
   * @param {Object|null} speakerNames - 講者名稱對應（{} 使用自定義名稱，null 不顯示講者）
   * @returns {String} 字幕文本
   */
  function generateSubtitleText(groups, format, speakerNames = {}) {
    if (!groups || groups.length === 0) return ''

    const lines = []
    const showSpeaker = speakerNames !== null // null 表示不顯示講者資訊

    for (const group of groups) {
      const timestamp = formatTimestamp(group.startTime, format, group.endTime)

      // 如果要顯示講者資訊，使用自定義名稱（如果有）或原始代號
      let speakerLabel = ''
      if (showSpeaker && group.speaker) {
        const displayName = speakerNames[group.speaker] || group.speaker
        speakerLabel = `[${displayName}]`
      }

      const content = group.combinedText.trim()

      if (speakerLabel) {
        lines.push(`${timestamp} ${speakerLabel} ${content}`)
      } else {
        lines.push(`${timestamp} ${content}`)
      }
    }

    return lines.join('\n')
  }

  /**
   * 格式化時間為 SRT 格式 (HH:MM:SS,mmm)
   * @param {Number} seconds - 秒數
   * @returns {String} SRT 格式時間字串
   */
  function formatTimeSRT(seconds) {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)

    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`
  }

  /**
   * 格式化時間為 VTT 格式 (HH:MM:SS.mmm)
   * @param {Number} seconds - 秒數
   * @returns {String} VTT 格式時間字串
   */
  function formatTimeVTT(seconds) {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)

    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
  }

  /**
   * 生成 SRT 字幕格式文本
   * @param {Array} groups - group 列表
   * @param {Object|null} speakerNames - 講者名稱對應
   * @returns {String} SRT 格式文本
   */
  function generateSRTText(groups, speakerNames = {}) {
    if (!groups || groups.length === 0) return ''

    const lines = []
    const showSpeaker = speakerNames !== null

    groups.forEach((group, index) => {
      // 序號
      lines.push(String(index + 1))

      // 時間範圍
      const startTime = formatTimeSRT(group.startTime)
      const endTime = formatTimeSRT(group.endTime)
      lines.push(`${startTime} --> ${endTime}`)

      // 講者 + 內容
      let content = group.combinedText.trim()
      if (showSpeaker && group.speaker) {
        const displayName = speakerNames[group.speaker] || group.speaker
        content = `[${displayName}] ${content}`
      }
      lines.push(content)

      // 空行分隔
      lines.push('')
    })

    return lines.join('\n')
  }

  /**
   * 生成 VTT 字幕格式文本
   * @param {Array} groups - group 列表
   * @param {Object|null} speakerNames - 講者名稱對應
   * @returns {String} VTT 格式文本
   */
  function generateVTTText(groups, speakerNames = {}) {
    if (!groups || groups.length === 0) return 'WEBVTT\n\n'

    const lines = ['WEBVTT', '']
    const showSpeaker = speakerNames !== null

    groups.forEach((group) => {
      // 時間範圍
      const startTime = formatTimeVTT(group.startTime)
      const endTime = formatTimeVTT(group.endTime)
      lines.push(`${startTime} --> ${endTime}`)

      // 講者 + 內容
      let content = group.combinedText.trim()
      if (showSpeaker && group.speaker) {
        const displayName = speakerNames[group.speaker] || group.speaker
        content = `[${displayName}] ${content}`
      }
      lines.push(content)

      // 空行分隔
      lines.push('')
    })

    return lines.join('\n')
  }

  return {
    // 狀態
    timeFormat,
    densityThreshold,
    hasSpeakerInfo,
    groupedSegments,

    // 方法
    formatTimestamp,
    updateRowContent,
    convertTableToPlainText,
    reconstructSegmentsFromGroups,
    generateSubtitleText,
    generateSRTText,
    generateVTTText
  }
}
