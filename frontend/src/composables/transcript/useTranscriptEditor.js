import { ref, nextTick } from 'vue'

/**
 * 逐字稿編輯管理 Composable
 *
 * 職責：
 * - 管理編輯狀態（編輯中、標題編輯）
 *
 * 註：未儲存變更判斷與 beforeunload 警告不在此（見下方說明），故只需 currentTranscript /
 * originalContent 兩個依賴。
 */
export function useTranscriptEditor(currentTranscript, originalContent) {
  // 編輯狀態
  const isEditing = ref(false)
  const isEditingTitle = ref(false)
  const editingTaskName = ref('')

  // 元素引用
  const titleInput = ref(null)

  // 注意：未儲存變更的判斷（hasUnsavedChanges）與 beforeunload 警告改由
  // TranscriptDetailView + usePageLifecycle 負責——段落模式的編輯內容只存在於
  // contenteditable 的 DOM，本 composable 拿不到 textareaRef 無法準確比對，
  // 故不在此計算（避免段落模式關分頁不跳警告的 bug）。

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
  }

  /**
   * 結束編輯（不儲存）
   */
  function finishEditing() {
    isEditing.value = false
  }

  return {
    // 狀態
    isEditing,
    isEditingTitle,
    editingTaskName,

    // 元素引用
    titleInput,

    // 標題編輯
    startTitleEdit,
    cancelTitleEdit,

    // 內容編輯
    startEditing,
    cancelEditing,
    finishEditing,
  }
}
