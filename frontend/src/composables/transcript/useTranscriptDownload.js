import { ref } from 'vue'

/**
 * 逐字稿下載管理 Composable
 *
 * 職責：
 * - 管理下載對話框狀態
 * - 處理段落模式和字幕模式的下載
 * - 生成下載檔案（TXT、SRT、VTT、PDF）
 */
export function useTranscriptDownload() {
  // 下載對話框狀態
  const showDownloadDialog = ref(false)
  const selectedDownloadFormat = ref('txt')
  const includeSpeaker = ref(true) // 預設包含講者資訊
  const includeSummary = ref(true) // 預設包含 AI 摘要
  const includeTranscript = ref(true) // 預設包含逐字稿
  const isGeneratingPdf = ref(false) // PDF 生成中狀態

  /**
   * 下載段落模式的逐字稿
   * @param {String} content - 逐字稿內容
   * @param {String} filename - 檔案名稱
   */
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

  /**
   * 執行下載（字幕模式）
   * @param {String} content - 字幕內容
   * @param {String} filename - 檔案名稱
   * @param {String} format - 下載格式 ('txt' | 'srt' | 'vtt')
   */
  function performSubtitleDownload(content, filename, format = 'txt') {
    let extension = 'txt'
    let mimeType = 'text/plain; charset=utf-8'

    // 根據格式設定副檔名和 MIME 類型
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

    // 關閉對話框
    showDownloadDialog.value = false
  }

  /**
   * 開啟下載對話框（字幕模式使用）
   */
  function openDownloadDialog() {
    showDownloadDialog.value = true
  }

  /**
   * 關閉下載對話框
   */
  function closeDownloadDialog() {
    showDownloadDialog.value = false
  }

  // 快取已載入的資源
  let pdfMakeInstance = null
  let chineseFontLoaded = false

  // 中文字體 CDN URL（使用 Google Noto Sans TC 子集版，約 5.6MB）
  const CHINESE_FONT_CDN = 'https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Sans/SubsetOTF/TC/NotoSansTC-Regular.otf'

  /**
   * 將 ArrayBuffer 轉換為 Base64
   */
  function arrayBufferToBase64(buffer) {
    let binary = ''
    const bytes = new Uint8Array(buffer)
    const len = bytes.byteLength
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    return window.btoa(binary)
  }

  /**
   * 載入 pdfmake 和中文字體（lazy loading）
   */
  async function loadPdfMake() {
    // 如果已載入過，直接返回快取
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

    // pdfFontsModule 本身就是 vfs（字體直接在根層級）
    const defaultVfs = pdfFontsModule.default || pdfFontsModule

    // 過濾掉 'default' 屬性，只保留字體檔案
    const vfs = {}
    for (const key in defaultVfs) {
      if (key !== 'default' && typeof defaultVfs[key] === 'string') {
        vfs[key] = defaultVfs[key]
      }
    }

    // 設置 vfs
    pdfMake.vfs = vfs

    // 設置預設字體定義
    pdfMake.fonts = {
      Roboto: {
        normal: 'Roboto-Regular.ttf',
        bold: 'Roboto-Medium.ttf',
        italics: 'Roboto-Italic.ttf',
        bolditalics: 'Roboto-MediumItalic.ttf'
      }
    }

    // 從 CDN 載入中文字體
    try {
      const fontResponse = await fetch(CHINESE_FONT_CDN)
      if (fontResponse.ok) {
        const fontBuffer = await fontResponse.arrayBuffer()
        const fontBase64 = arrayBufferToBase64(fontBuffer)

        // 添加中文字體到 vfs
        pdfMake.vfs['NotoSansTC-Regular.otf'] = fontBase64

        // 添加中文字體定義
        pdfMake.fonts.NotoSansTC = {
          normal: 'NotoSansTC-Regular.otf',
          bold: 'NotoSansTC-Regular.otf',
          italics: 'NotoSansTC-Regular.otf',
          bolditalics: 'NotoSansTC-Regular.otf'
        }

        chineseFontLoaded = true
      } else {
        console.warn('CDN 回應錯誤，使用預設字體')
      }
    } catch (error) {
      console.warn('無法從 CDN 載入中文字體，將使用預設字體:', error)
    }

    // 快取 pdfMake 實例和 vfs
    pdfMakeInstance = pdfMake

    return { pdfMake, vfs: pdfMake.vfs, fonts: pdfMake.fonts, hasChineseFont: chineseFontLoaded }
  }

  /**
   * 格式化 AI 摘要為 PDF 內容
   * @param {Object} summary - AI 摘要物件
   * @param {Function} t - i18n 翻譯函數
   * @returns {Array} pdfmake 內容陣列
   */
  function formatSummaryForPdf(summary, t) {
    const content = []

    if (!summary?.content) return content

    const summaryContent = summary.content

    // 標題
    content.push({
      text: t('aiSummary.title'),
      style: 'sectionHeader',
      margin: [0, 0, 0, 12]
    })

    // Meta 資訊（類型、語氣）
    if (summaryContent.meta) {
      const metaText = []
      if (summaryContent.meta.type) {
        metaText.push(`${t('aiSummary.type')}: ${summaryContent.meta.type}`)
      }
      if (summaryContent.meta.sentiment) {
        metaText.push(`${t('aiSummary.sentiment')}: ${summaryContent.meta.sentiment}`)
      }
      if (metaText.length > 0) {
        content.push({
          text: metaText.join('  |  '),
          style: 'meta',
          margin: [0, 0, 0, 8]
        })
      }

      // 偵測主題
      if (summaryContent.meta.detected_topic) {
        content.push({
          text: summaryContent.meta.detected_topic,
          style: 'topicTitle',
          margin: [0, 0, 0, 12]
        })
      }
    }

    // 執行摘要
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

    // 重點列表
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

    // 內容段落
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

    // 待辦事項
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

    // 分隔線
    content.push({
      canvas: [{ type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, lineColor: '#cccccc' }],
      margin: [0, 12, 0, 12]
    })

    return content
  }

  /**
   * 格式化逐字稿為 PDF 內容
   * @param {String} transcriptText - 逐字稿文字內容
   * @param {Function} t - i18n 翻譯函數
   * @returns {Array} pdfmake 內容陣列
   */
  function formatTranscriptForPdf(transcriptText, t) {
    const content = []

    if (!transcriptText) return content

    content.push({
      text: t('downloadDialog.transcriptSection'),
      style: 'sectionHeader',
      margin: [0, 0, 0, 12]
    })

    // 將逐字稿按行分割並格式化
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

  /**
   * 生成並下載 PDF
   * @param {Object} options - 下載選項
   * @param {String} options.filename - 檔案名稱
   * @param {String} options.title - 文件標題
   * @param {Object} options.summary - AI 摘要（可選）
   * @param {String} options.transcriptText - 逐字稿文字
   * @param {Boolean} options.includeSummary - 是否包含摘要
   * @param {Boolean} options.includeTranscript - 是否包含逐字稿
   * @param {Function} options.t - i18n 翻譯函數
   */
  async function downloadAsPdf(options) {
    const { filename, title, summary, transcriptText, includeSummary: incSummary, includeTranscript: incTranscript, t } = options

    try {
      isGeneratingPdf.value = true

      const { pdfMake, vfs, fonts, hasChineseFont } = await loadPdfMake()

      const docContent = []

      // 文件標題
      docContent.push({
        text: title || filename,
        style: 'title',
        margin: [0, 0, 0, 20]
      })

      // AI 摘要
      if (incSummary && summary) {
        docContent.push(...formatSummaryForPdf(summary, t))
      }

      // 逐字稿
      if (incTranscript && transcriptText) {
        docContent.push(...formatTranscriptForPdf(transcriptText, t))
      }

      // 根據字體載入狀態選擇字體
      const defaultFont = hasChineseFont ? 'NotoSansTC' : 'Roboto'

      // 如果使用中文字體，不使用 bold（因為只有一個字重）
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

      // 設置 fonts
      pdfMake.fonts = fonts

      // 將中文字體寫入 pdfMake 的 virtualfs（需要轉換為 Uint8Array）
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

      // 關閉對話框
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

    // 方法
    downloadParagraphMode,
    performSubtitleDownload,
    openDownloadDialog,
    closeDownloadDialog,
    downloadAsPdf
  }
}
