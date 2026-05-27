import { ref, nextTick } from 'vue'

/**
 * 編輯生命週期管理 Composable
 *
 * 職責：
 * - 編輯啟動 / 取消 / 儲存 的完整流程
 * - 滾動位置保存與恢復
 * - segments 備份與恢復
 * - timecode markers 狀態暫存
 * - segment offset 追蹤的初始化與清理
 */
export function useEditingLifecycle({
  displayMode,
  textareaRef,
  segments,
  currentTranscript,
  originalContent,
  showTimecodeMarkers,
  savedTimecodeMarkersState,
  segmentMarkers,
  generateSegmentMarkers,
  segOffsets,
  startEditing,
  cancelEditing,
  finishEditing,
  clearHighlights,
  reSearch,
  reapplyHighlightsIfNeeded,
  saveTranscript,
  updateTaskName,
  editingTaskName,
  isEditingTitle,
  groupedSegments,
  reconstructSegmentsFromGroups,
  isMounted,
  scrollRestoreTimers,
}) {
  const originalSegments = ref([])

  function scheduleScrollRestore(scrollTop) {
    if (displayMode.value !== 'paragraph' || scrollTop <= 0) return
    const timerId = setTimeout(() => {
      if (!isMounted()) return
      if (textareaRef.value) {
        textareaRef.value.scrollTop = scrollTop
      }
    }, 100)
    scrollRestoreTimers().push(timerId)
  }

  function handleStartEditing() {
    let savedScrollTop = 0
    if (displayMode.value === 'paragraph' && textareaRef.value) {
      savedScrollTop = textareaRef.value.scrollTop
    }

    if (displayMode.value === 'paragraph') {
      savedTimecodeMarkersState.value = showTimecodeMarkers.value
      showTimecodeMarkers.value = false
    }

    if (segments.value.length > 0) {
      originalSegments.value = JSON.parse(JSON.stringify(segments.value))
    }

    startEditing()

    if (displayMode.value === 'paragraph') {
      nextTick(() => {
        if (textareaRef.value) {
          if (!segmentMarkers.value?.length && segments.value?.length) {
            const content = textareaRef.value.textContent || currentTranscript.value?.content || ''
            if (content) generateSegmentMarkers(segments.value, content)
          }
          segOffsets.initEditing(textareaRef.value, segmentMarkers.value)
        }
      })
    }

    scheduleScrollRestore(savedScrollTop)
    reapplyHighlightsIfNeeded()
  }

  function handleCancelEditing() {
    clearHighlights()

    let savedScrollTop = 0
    if (displayMode.value === 'paragraph' && textareaRef.value) {
      savedScrollTop = textareaRef.value.scrollTop
    }

    if (originalSegments.value.length > 0) {
      segments.value = JSON.parse(JSON.stringify(originalSegments.value))
      originalSegments.value = []
    }

    segOffsets.resetEditing()
    cancelEditing()

    if (displayMode.value === 'paragraph') {
      showTimecodeMarkers.value = savedTimecodeMarkersState.value
    }

    scheduleScrollRestore(savedScrollTop)
    reSearch()
  }

  async function saveEditing() {
    clearHighlights()

    let contentToSave = ''
    let segmentsToSave = null

    let savedScrollTop = 0
    if (displayMode.value === 'paragraph' && textareaRef.value) {
      savedScrollTop = textareaRef.value.scrollTop
    }

    if (displayMode.value === 'paragraph') {
      if (textareaRef.value) {
        const { fullText, updatedSegments, hasChanges: segOffsetsHasChanges } =
          segOffsets.extractForSave(textareaRef.value, segments.value)
        contentToSave = fullText
        currentTranscript.value.content = contentToSave

        let hasChanges = segOffsetsHasChanges
        if (
          !hasChanges &&
          originalSegments.value.length > 0 &&
          originalSegments.value.length === segments.value.length
        ) {
          for (let i = 0; i < segments.value.length; i++) {
            const a = (segments.value[i].text ?? '').trim()
            const b = (originalSegments.value[i]?.text ?? '').trim()
            if (a !== b) {
              hasChanges = true
              break
            }
          }
        }
        if (hasChanges) {
          segmentsToSave = updatedSegments
        }
      } else {
        contentToSave = currentTranscript.value.content
      }
    } else {
      contentToSave = originalContent.value
      segmentsToSave = reconstructSegmentsFromGroups(groupedSegments.value)
    }

    const success = await saveTranscript(contentToSave, segmentsToSave, displayMode.value)

    if (success) {
      finishEditing()

      if (segmentsToSave) {
        segments.value = segmentsToSave
      }

      originalSegments.value = []
      segOffsets.resetEditing()

      if (displayMode.value === 'paragraph') {
        showTimecodeMarkers.value = savedTimecodeMarkersState.value
      }

      scheduleScrollRestore(savedScrollTop)
      reSearch()
    }
  }

  async function saveTaskName() {
    await updateTaskName(editingTaskName.value)
    isEditingTitle.value = false
  }

  return {
    originalSegments,
    handleStartEditing,
    handleCancelEditing,
    saveEditing,
    saveTaskName,
  }
}
