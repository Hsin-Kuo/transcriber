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

    saveSegmentsToBackend()
  }

  function handleOpenSpeakerSettings(speakerCode) {
    if (headerRef.value) {
      headerRef.value.openSpeakerSettings(speakerCode)
    }
  }

  async function saveSegmentsToBackend() {
    try {
      await saveTranscript(
        currentTranscript.value.content,
        segments.value,
        'subtitle'
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
