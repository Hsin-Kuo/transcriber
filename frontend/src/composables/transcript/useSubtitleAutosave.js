import { watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * 字幕模式自動儲存 Composable
 *
 * 職責：
 * - 講者名稱 debounced 自動儲存
 * - 疏密度 debounced 自動儲存
 * - segment 講者變更 + 即時存檔
 * - 打開講者設置面板
 */
export function useSubtitleAutosave({
  displayMode,
  segments,
  speakerNames,
  densityThreshold,
  groupedSegments,
  currentTranscript,
  headerRef,
  saveTranscript,
  updateSpeakerNames,
  updateSubtitleSettings,
  isMounted,
  isInitializing,
  isEditing,
  originalSegments,
  originalContent,
}) {
  const { t: $t } = useI18n()

  let speakerNamesSaveTimer = null
  let densityThresholdSaveTimer = null

  watch(speakerNames, (newValue) => {
    if (displayMode.value !== 'subtitle') return

    if (speakerNamesSaveTimer) {
      clearTimeout(speakerNamesSaveTimer)
    }

    speakerNamesSaveTimer = setTimeout(async () => {
      if (!isMounted()) return
      console.log('🔄 ' + $t('transcriptDetail.autoSavingSpeaker') + ':', newValue)
      await updateSpeakerNames(newValue)
    }, 1000)
  }, { deep: true })

  watch(densityThreshold, (newValue) => {
    if (displayMode.value !== 'subtitle') return
    if (isInitializing()) return

    if (densityThresholdSaveTimer) {
      clearTimeout(densityThresholdSaveTimer)
    }

    densityThresholdSaveTimer = setTimeout(async () => {
      if (!isMounted()) return
      console.log('🔄 自動儲存疏密度設定:', newValue)
      await updateSubtitleSettings({ density_threshold: newValue })
    }, 1000)
  })

  onUnmounted(() => {
    if (speakerNamesSaveTimer) {
      clearTimeout(speakerNamesSaveTimer)
      speakerNamesSaveTimer = null
    }
    if (densityThresholdSaveTimer) {
      clearTimeout(densityThresholdSaveTimer)
      densityThresholdSaveTimer = null
    }
  })

  function updateSegmentSpeaker({ groupId, newSpeaker }) {
    const group = groupedSegments.value.find(g => g.id === groupId)
    if (!group) return

    group.speaker = newSpeaker
    group.segments.forEach(segment => {
      segment.speaker = newSpeaker
    })

    segments.value = segments.value.map(seg => {
      const groupSegment = group.segments.find(gs =>
        gs.start === seg.start && gs.end === seg.end && gs.text === seg.text
      )
      if (groupSegment) {
        return { ...seg, speaker: newSpeaker }
      }
      return seg
    })

    // 編輯模式：講者與文字解耦。
    // 講者即時存後端，但只帶「編輯開始時的文字 baseline」（originalSegments），
    // 不挾帶尚未儲存的文字編輯；同時把講者變更同步進 originalSegments 快照，
    // 讓「取消」只還原文字、保留已存的講者（編輯中 segments 與快照同序同長度）。
    if (isEditing?.value && originalSegments?.value?.length === segments.value.length) {
      const baseline = originalSegments.value.map((seg, i) => ({
        ...seg,
        speaker: segments.value[i].speaker,
      }))
      originalSegments.value = baseline
      saveSegmentsToBackend(baseline, originalContent?.value)
    } else {
      saveSegmentsToBackend()
    }
  }

  function handleOpenSpeakerSettings(speakerCode) {
    if (headerRef.value) {
      headerRef.value.openSpeakerSettings(speakerCode)
    }
  }

  // segmentsOverride / contentOverride：編輯模式下傳 baseline，只存講者不挾帶未存文字
  async function saveSegmentsToBackend(segmentsOverride = null, contentOverride = null) {
    try {
      await saveTranscript(
        contentOverride != null ? contentOverride : currentTranscript.value.content,
        segmentsOverride || segments.value,
        'subtitle',
        // 講者變更走通用訊息，避免顯示「逐字稿和字幕已更新」誤導
        $t('transcriptData.changesSaved')
      )
      console.log('✅ ' + $t('transcriptDetail.segmentsAutoSaved'))
    } catch (error) {
      console.error('❌ ' + $t('transcriptDetail.errorSavingSegments') + ':', error)
    }
  }

  return {
    updateSegmentSpeaker,
    handleOpenSpeakerSettings,
    saveSegmentsToBackend,
  }
}
