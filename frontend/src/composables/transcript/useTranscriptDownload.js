import { ref } from 'vue'

/**
 * 逐字稿下載管理 Composable
 *
 * 職責：
 * - 管理下載對話框狀態
 * - 處理段落模式和字幕模式的下載
 * - 生成下載檔案
 */
export function useTranscriptDownload() {
  // 下載對話框狀態
  const showDownloadDialog = ref(false)
  const selectedDownloadFormat = ref('txt')
  const includeSpeaker = ref(true) // 預設包含講者資訊

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

  return {
    // 狀態
    showDownloadDialog,
    selectedDownloadFormat,
    includeSpeaker,

    // 方法
    downloadParagraphMode,
    performSubtitleDownload,
    openDownloadDialog,
    closeDownloadDialog
  }
}
