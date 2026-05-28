import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import { NEW_ENDPOINTS } from '../../api/endpoints'

// Feature flag：切換 backend / frontend PDF 生成路徑。
// 預設 backend（同源呼叫 ReportLab，支援 TC/SC/JP/KR 多語言；frontend pdfmake
// 只支援 TC 且 bundle 大 6MB）。如果 backend 出問題，臨時設成 false 可立刻
// fallback 到 frontend 路徑。1-2 週觀察穩定後 frontend 路徑會整塊移除。
const USE_BACKEND_PDF = import.meta.env.VITE_BACKEND_PDF_ENABLED !== 'false'

/**
 * 逐字稿下載管理 Composable
 *
 * 職責：
 * - 管理下載對話框狀態
 * - 載入 AI 摘要（for download）
 * - 處理段落模式和字幕模式的下載
 * - 生成下載檔案（TXT、SRT、VTT、PDF）
 */
export function useTranscriptDownload(deps = {}) {
  const {
    currentTranscript,
    displayMode,
    groupedSegments,
    speakerNames,
    timeFormat,
    generateSubtitleText,
    generateSRTText,
    generateVTTText,
    summaryService,
  } = deps

  const { t: $t, locale } = useI18n()

  // 下載對話框狀態
  const showDownloadDialog = ref(false)
  const selectedDownloadFormat = ref('txt')
  const includeSpeaker = ref(true)
  const includeSummary = ref(true)
  const includeTranscript = ref(true)
  const isGeneratingPdf = ref(false)

  // AI 摘要數據（用於下載）
  const summaryData = ref(null)

  const hasSummaryData = computed(() => {
    return currentTranscript?.value?.summary_status === 'completed'
  })

  async function loadSummaryForDownload() {
    if (!hasSummaryData.value || summaryData.value) return

    try {
      summaryData.value = await summaryService.get(currentTranscript.value.task_id)
    } catch (error) {
      console.error('載入摘要失敗:', error)
      summaryData.value = null
    }
  }

  // ========== 下載觸發 ==========

  function openDownloadDialog() {
    showDownloadDialog.value = true
  }

  function closeDownloadDialog() {
    showDownloadDialog.value = false
  }

  function downloadTranscript() {
    showDownloadDialog.value = true
  }

  // ========== 執行下載 ==========

  async function performDownload() {
    const speakerNamesToUse = includeSpeaker.value ? speakerNames.value : null
    const filename = currentTranscript.value.custom_name || currentTranscript.value.filename || 'transcript'
    const format = selectedDownloadFormat.value
    const isParagraphMode = displayMode.value === 'paragraph'

    const getTranscriptText = () => {
      if (isParagraphMode) {
        return currentTranscript.value.content || ''
      } else {
        return generateSubtitleText(groupedSegments.value, timeFormat.value, speakerNamesToUse)
      }
    }

    // PDF 格式處理
    if (format === 'pdf') {
      if (includeSummary.value && hasSummaryData.value && !summaryData.value) {
        await loadSummaryForDownload()
      }

      let transcriptText = ''
      if (includeTranscript.value) {
        transcriptText = getTranscriptText()
      }

      await downloadAsPdf({
        filename,
        title: currentTranscript.value.custom_name || currentTranscript.value.filename,
        summary: includeSummary.value ? summaryData.value : null,
        transcriptText,
        includeSummary: includeSummary.value,
        includeTranscript: includeTranscript.value,
        t: $t
      })
      return
    }

    // TXT 格式處理（支援內容選擇）
    if (format === 'txt') {
      let content = ''

      if (includeSummary.value && hasSummaryData.value) {
        if (!summaryData.value) {
          await loadSummaryForDownload()
        }
        if (summaryData.value) {
          content += formatSummaryAsText(summaryData.value)
          if (includeTranscript.value) {
            content += '\n\n' + '='.repeat(50) + '\n\n'
          }
        }
      }

      if (includeTranscript.value) {
        content += getTranscriptText()
      }

      performSubtitleDownload(content, filename, format)
      return
    }

    // SRT/VTT 格式（僅逐字稿，僅字幕模式可用）
    let content = ''
    if (format === 'srt') {
      content = generateSRTText(groupedSegments.value, speakerNamesToUse)
    } else if (format === 'vtt') {
      content = generateVTTText(groupedSegments.value, speakerNamesToUse)
    }

    performSubtitleDownload(content, filename, format)
  }

  // ========== 摘要格式化 ==========

  function formatSummaryAsText(summary) {
    if (!summary?.content) return ''

    const content = summary.content
    const lines = []

    lines.push('【AI 摘要】')
    lines.push('')

    if (content.meta?.detected_topic) {
      lines.push(content.meta.detected_topic)
      lines.push('')
    }

    if (content.summary) {
      lines.push(`【${$t('aiSummary.executiveSummary')}】`)
      lines.push(content.summary)
      lines.push('')
    }

    const points = content.key_points || content.highlights || []
    if (points.length > 0) {
      lines.push(`【${$t('aiSummary.keyPoints')}】`)
      points.forEach(point => {
        const text = typeof point === 'string' ? point : (point.text || point.point || point.content || JSON.stringify(point))
        lines.push(`• ${text}`)
      })
      lines.push('')
    }

    if (content.segments && content.segments.length > 0) {
      lines.push(`【${$t('aiSummary.contentSegments')}】`)
      content.segments.forEach(segment => {
        lines.push(`▎${segment.topic}`)
        lines.push(segment.content)
        if (segment.keywords && segment.keywords.length > 0) {
          lines.push(`關鍵詞: ${segment.keywords.join(', ')}`)
        }
        lines.push('')
      })
    }

    if (content.action_items && content.action_items.length > 0) {
      lines.push(`【${$t('aiSummary.actionItems')}】`)
      content.action_items.forEach(item => {
        let line = `☐ ${item.task}`
        const meta = []
        if (item.owner) meta.push(item.owner)
        if (item.deadline) meta.push(item.deadline)
        if (meta.length > 0) line += ` (${meta.join(' / ')})`
        lines.push(line)
      })
      lines.push('')
    }

    return lines.join('\n').trim()
  }

  // ========== 檔案下載工具 ==========

  function downloadParagraphMode(content, filename) {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${filename}.txt`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  function performSubtitleDownload(content, filename, format = 'txt') {
    let extension = 'txt'
    let mimeType = 'text/plain; charset=utf-8'

    if (format === 'srt') {
      extension = 'srt'
      mimeType = 'application/x-subrip; charset=utf-8'
    } else if (format === 'vtt') {
      extension = 'vtt'
      mimeType = 'text/vtt; charset=utf-8'
    } else {
      extension = 'txt'
      mimeType = 'text/plain; charset=utf-8'
    }

    const blob = new Blob([content], { type: mimeType })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${filename}.${extension}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)

    showDownloadDialog.value = false
  }

  // ========== PDF 生成 ==========

  let pdfMakeInstance = null
  let chineseFontLoaded = false

  // Self-hosted Noto Sans TC：放 src/assets，由 Vite 加 content hash
  // → 1y immutable cache 安全（換版自動換 filename，舊使用者不會被 cache 卡死）。
  // 同源 fetch → 不受 CSP connect-src 限制，也不依賴第三方 CDN。
  const CHINESE_FONT_URL = new URL('../../assets/fonts/NotoSansTC-Regular.otf', import.meta.url).href

  function arrayBufferToBase64(buffer) {
    let binary = ''
    const bytes = new Uint8Array(buffer)
    const len = bytes.byteLength
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    return window.btoa(binary)
  }

  async function loadPdfMake() {
    if (pdfMakeInstance) {
      return {
        pdfMake: pdfMakeInstance,
        vfs: pdfMakeInstance.vfs,
        fonts: pdfMakeInstance.fonts,
        hasChineseFont: chineseFontLoaded
      }
    }

    const pdfMakeModule = await import('pdfmake/build/pdfmake')
    const pdfFontsModule = await import('pdfmake/build/vfs_fonts')

    const pdfMake = pdfMakeModule.default || pdfMakeModule

    const defaultVfs = pdfFontsModule.default || pdfFontsModule

    const vfs = {}
    for (const key in defaultVfs) {
      if (key !== 'default' && typeof defaultVfs[key] === 'string') {
        vfs[key] = defaultVfs[key]
      }
    }

    pdfMake.vfs = vfs

    pdfMake.fonts = {
      Roboto: {
        normal: 'Roboto-Regular.ttf',
        bold: 'Roboto-Medium.ttf',
        italics: 'Roboto-Italic.ttf',
        bolditalics: 'Roboto-MediumItalic.ttf'
      }
    }

    try {
      const fontResponse = await fetch(CHINESE_FONT_URL)
      if (fontResponse.ok) {
        const fontBuffer = await fontResponse.arrayBuffer()
        const fontBase64 = arrayBufferToBase64(fontBuffer)

        pdfMake.vfs['NotoSansTC-Regular.otf'] = fontBase64

        pdfMake.fonts.NotoSansTC = {
          normal: 'NotoSansTC-Regular.otf',
          bold: 'NotoSansTC-Regular.otf',
          italics: 'NotoSansTC-Regular.otf',
          bolditalics: 'NotoSansTC-Regular.otf'
        }

        chineseFontLoaded = true
      } else {
        console.error(`中文字體載入失敗 (HTTP ${fontResponse.status})，PDF 中文將顯示為 □`)
      }
    } catch (error) {
      console.error('中文字體載入失敗，PDF 中文將顯示為 □：', error)
    }

    pdfMakeInstance = pdfMake

    return { pdfMake, vfs: pdfMake.vfs, fonts: pdfMake.fonts, hasChineseFont: chineseFontLoaded }
  }

  function formatSummaryForPdf(summary, t) {
    const content = []

    if (!summary?.content) return content

    const summaryContent = summary.content

    content.push({
      text: t('aiSummary.title'),
      style: 'sectionHeader',
      margin: [0, 0, 0, 12]
    })

    if (summaryContent.meta) {
      const metaText = []
      if (summaryContent.meta.type) {
        metaText.push(`${t('aiSummary.type')}: ${summaryContent.meta.type}`)
      }
      if (metaText.length > 0) {
        content.push({
          text: metaText.join('  |  '),
          style: 'meta',
          margin: [0, 0, 0, 8]
        })
      }

      if (summaryContent.meta.detected_topic) {
        content.push({
          text: summaryContent.meta.detected_topic,
          style: 'topicTitle',
          margin: [0, 0, 0, 12]
        })
      }
    }

    if (summaryContent.summary) {
      content.push({
        text: t('aiSummary.executiveSummary'),
        style: 'subHeader',
        margin: [0, 8, 0, 6]
      })
      content.push({
        text: summaryContent.summary,
        style: 'body',
        margin: [0, 0, 0, 12]
      })
    }

    const keyPoints = (summaryContent.key_points || summaryContent.highlights || []).map(p =>
      typeof p === 'string' ? p : (p.text || p.point || p.content || JSON.stringify(p))
    )
    if (keyPoints.length > 0) {
      content.push({
        text: t('aiSummary.keyPoints'),
        style: 'subHeader',
        margin: [0, 8, 0, 6]
      })
      content.push({
        ul: keyPoints,
        style: 'body',
        margin: [0, 0, 0, 12]
      })
    }

    if (summaryContent.segments && summaryContent.segments.length > 0) {
      content.push({
        text: t('aiSummary.contentSegments'),
        style: 'subHeader',
        margin: [0, 8, 0, 6]
      })

      summaryContent.segments.forEach(segment => {
        content.push({
          text: segment.topic,
          style: 'segmentTitle',
          margin: [0, 6, 0, 4]
        })
        content.push({
          text: segment.content,
          style: 'body',
          margin: [0, 0, 0, 4]
        })
        if (segment.keywords && segment.keywords.length > 0) {
          content.push({
            text: `${t('aiSummary.keywords')}: ${segment.keywords.join(', ')}`,
            style: 'keywords',
            margin: [0, 0, 0, 8]
          })
        }
      })
    }

    if (summaryContent.action_items && summaryContent.action_items.length > 0) {
      content.push({
        text: t('aiSummary.actionItems'),
        style: 'subHeader',
        margin: [0, 12, 0, 6]
      })

      const actionList = summaryContent.action_items.map(item => {
        let text = item.task
        const meta = []
        if (item.owner) meta.push(item.owner)
        if (item.deadline) meta.push(item.deadline)
        if (meta.length > 0) text += ` (${meta.join(' / ')})`
        return text
      })

      content.push({
        ul: actionList,
        style: 'body',
        margin: [0, 0, 0, 12]
      })
    }

    content.push({
      canvas: [{ type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, lineColor: '#cccccc' }],
      margin: [0, 12, 0, 12]
    })

    return content
  }

  function formatTranscriptForPdf(transcriptText, t) {
    const content = []

    if (!transcriptText) return content

    content.push({
      text: t('downloadDialog.transcriptSection'),
      style: 'sectionHeader',
      margin: [0, 0, 0, 12]
    })

    const lines = transcriptText.split('\n')
    lines.forEach(line => {
      if (line.trim()) {
        content.push({
          text: line,
          style: 'body',
          margin: [0, 0, 0, 4]
        })
      } else {
        content.push({ text: '', margin: [0, 4, 0, 4] })
      }
    })

    return content
  }

  // Backend PDF 路徑：POST /transcriptions/:id/export/pdf 拿 PDF blob 觸發下載。
  // Summary 由 backend 自己從 DB 抓，不重送；transcript_text 由 frontend 預先
  // 格式化（已處理 paragraph / subtitle mode + speaker names + density）。
  async function downloadAsPdfBackend(options) {
    const { filename, title, transcriptText, includeSummary: incSummary, includeTranscript: incTranscript } = options
    const taskId = currentTranscript.value?.task_id
    if (!taskId) {
      throw new Error('downloadAsPdfBackend: missing task_id')
    }

    try {
      isGeneratingPdf.value = true

      // 後端目前只 hardcode zh-TW / en 兩個 locale。中文相關語言（zh-CN / zh-Hans
      // 等）都映射到 zh-TW（section title 是「AI 摘要」「逐字稿」等共通字），
      // 其他語言（ja / ko / 等）fallback 成 en。
      const backendLocale = locale.value.startsWith('zh') ? 'zh-TW' : 'en'

      const response = await api.post(
        NEW_ENDPOINTS.transcriptions.exportPdf(taskId),
        {
          title: title || filename,
          transcript_text: incTranscript ? transcriptText : null,
          include_summary: incSummary,
          include_transcript: incTranscript,
          locale: backendLocale,
        },
        { responseType: 'blob' }
      )

      const blob = new Blob([response.data], { type: 'application/pdf' })
      const url = window.URL.createObjectURL(blob)
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = `${filename}.pdf`
        document.body.appendChild(link)
        try {
          link.click()
        } finally {
          link.remove()
        }
      } finally {
        // 不管 click / appendChild / remove 是否拋例外，都確保 URL 被釋放
        // 避免 createObjectURL 在異常路徑洩漏 blob memory
        window.URL.revokeObjectURL(url)
      }

      showDownloadDialog.value = false
    } finally {
      isGeneratingPdf.value = false
    }
  }

  async function downloadAsPdf(options) {
    // 預設走 backend；fallback 到 frontend pdfmake 只在 flag 顯式關掉時觸發
    if (USE_BACKEND_PDF) {
      return downloadAsPdfBackend(options)
    }

    const { filename, title, summary, transcriptText, includeSummary: incSummary, includeTranscript: incTranscript, t } = options

    try {
      isGeneratingPdf.value = true

      const { pdfMake, vfs, fonts, hasChineseFont } = await loadPdfMake()

      const docContent = []

      docContent.push({
        text: title || filename,
        style: 'title',
        margin: [0, 0, 0, 20]
      })

      if (incSummary && summary) {
        docContent.push(...formatSummaryForPdf(summary, t))
      }

      if (incTranscript && transcriptText) {
        docContent.push(...formatTranscriptForPdf(transcriptText, t))
      }

      const defaultFont = hasChineseFont ? 'NotoSansTC' : 'Roboto'

      const styles = hasChineseFont ? {
        title: {
          fontSize: 20,
          color: '#333333'
        },
        sectionHeader: {
          fontSize: 16,
          color: '#444444'
        },
        subHeader: {
          fontSize: 13,
          color: '#555555'
        },
        topicTitle: {
          fontSize: 14,
          color: '#333333'
        },
        segmentTitle: {
          fontSize: 12,
          color: '#666666'
        },
        body: {
          fontSize: 11,
          color: '#333333',
          lineHeight: 1.4
        },
        meta: {
          fontSize: 10,
          color: '#888888'
        },
        keywords: {
          fontSize: 10,
          color: '#666666'
        }
      } : {
        title: {
          fontSize: 20,
          bold: true,
          color: '#333333'
        },
        sectionHeader: {
          fontSize: 16,
          bold: true,
          color: '#444444'
        },
        subHeader: {
          fontSize: 13,
          bold: true,
          color: '#555555'
        },
        topicTitle: {
          fontSize: 14,
          bold: true,
          color: '#333333'
        },
        segmentTitle: {
          fontSize: 12,
          bold: true,
          color: '#666666'
        },
        body: {
          fontSize: 11,
          color: '#333333',
          lineHeight: 1.4
        },
        meta: {
          fontSize: 10,
          color: '#888888'
        },
        keywords: {
          fontSize: 10,
          color: '#666666',
          italics: true
        }
      }

      const docDefinition = {
        content: docContent,
        defaultStyle: {
          font: defaultFont
        },
        styles,
        pageMargins: [40, 40, 40, 40]
      }

      pdfMake.fonts = fonts

      if (hasChineseFont && pdfMake.virtualfs && typeof pdfMake.virtualfs.writeFileSync === 'function') {
        const fontBase64 = vfs['NotoSansTC-Regular.otf']
        if (fontBase64) {
          const binaryString = atob(fontBase64)
          const bytes = new Uint8Array(binaryString.length)
          for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i)
          }
          pdfMake.virtualfs.writeFileSync('NotoSansTC-Regular.otf', bytes)
        }
      }

      pdfMake.createPdf(docDefinition).download(`${filename}.pdf`)

      showDownloadDialog.value = false
    } catch (error) {
      console.error('PDF 生成失敗:', error)
      throw error
    } finally {
      isGeneratingPdf.value = false
    }
  }

  return {
    // 狀態
    showDownloadDialog,
    selectedDownloadFormat,
    includeSpeaker,
    includeSummary,
    includeTranscript,
    isGeneratingPdf,
    hasSummaryData,

    // 方法
    downloadParagraphMode,
    performSubtitleDownload,
    openDownloadDialog,
    closeDownloadDialog,
    downloadTranscript,
    performDownload,
    downloadAsPdf
  }
}
