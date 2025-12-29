import { ref, computed, nextTick } from 'vue'

/**
 * 逐字稿編輯管理 Composable
 *
 * 職責：
 * - 管理編輯狀態（編輯中、標題編輯）
 * - 處理取代功能
 * - 檢查未儲存的變更
 */
export function useTranscriptEditor(currentTranscript, originalContent, displayMode, groupedSegments, convertTableToPlainText, speakerNames = null) {
  // 編輯狀態
  const isEditing = ref(false)
  const isEditingTitle = ref(false)
  const editingTaskName = ref('')

  // 取代工具
  const findText = ref('')
  const replaceText = ref('')

  // 元素引用
  const titleInput = ref(null)

  /**
   * 檢查是否有未儲存的變更
   */
  const hasUnsavedChanges = computed(() => {
    if (!isEditing.value) return false

    if (displayMode.value === 'paragraph') {
      // 段落模式：比較 textarea 內容
      return currentTranscript.value.content !== originalContent.value
    } else if (displayMode.value === 'subtitle') {
      // 字幕模式：比較表格內容
      // 注意：這裡不傳 speakerNames，因為講者名稱變更不通過編輯儲存
      const currentContent = convertTableToPlainText(groupedSegments.value)
      return currentContent !== originalContent.value
    }

    return false
  })

  // ========== 標題編輯 ==========

  /**
   * 開始編輯標題
   */
  function startTitleEdit() {
    isEditingTitle.value = true
    editingTaskName.value = currentTranscript.value.custom_name || currentTranscript.value.filename || ''
    nextTick(() => {
      if (titleInput.value) {
        titleInput.value.focus()
        titleInput.value.select()
      }
    })
  }

  /**
   * 取消標題編輯
   */
  function cancelTitleEdit() {
    isEditingTitle.value = false
    editingTaskName.value = ''
  }

  // ========== 內容編輯 ==========

  /**
   * 開始編輯內容
   */
  function startEditing() {
    isEditing.value = true
  }

  /**
   * 取消編輯內容
   */
  function cancelEditing() {
    currentTranscript.value.content = originalContent.value
    isEditing.value = false
    findText.value = ''
    replaceText.value = ''
  }

  /**
   * 結束編輯（不儲存）
   */
  function finishEditing() {
    isEditing.value = false
    findText.value = ''
    replaceText.value = ''
  }

  // ========== 取代功能 ==========

  /**
   * 取代全部
   */
  function replaceAll() {
    if (!findText.value) return
    const regex = new RegExp(findText.value, 'g')
    currentTranscript.value.content = currentTranscript.value.content.replace(regex, replaceText.value)
  }

  // ========== 瀏覽器警告處理 ==========

  /**
   * 處理瀏覽器關閉/重新整理時的警告
   */
  const handleBeforeUnload = (e) => {
    if (hasUnsavedChanges.value) {
      e.preventDefault()
      e.returnValue = ''
      return ''
    }
  }

  return {
    // 狀態
    isEditing,
    isEditingTitle,
    editingTaskName,
    findText,
    replaceText,
    hasUnsavedChanges,

    // 元素引用
    titleInput,

    // 標題編輯
    startTitleEdit,
    cancelTitleEdit,

    // 內容編輯
    startEditing,
    cancelEditing,
    finishEditing,

    // 取代功能
    replaceAll,

    // 瀏覽器警告
    handleBeforeUnload
  }
}
