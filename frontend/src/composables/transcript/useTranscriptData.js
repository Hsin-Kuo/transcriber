import { ref, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import { NEW_ENDPOINTS } from '../../api/endpoints'

/**
 * 逐字稿數據管理 Composable
 *
 * 職責：
 * - 載入逐字稿和 segments 數據
 * - 儲存逐字稿內容（支援段落和字幕模式）
 * - 更新任務名稱
 */
export function useTranscriptData() {
  // i18n
  const { t } = useI18n()

  // 注入全局通知函數
  const showNotification = inject('showNotification', null)

  // 數據狀態
  const currentTranscript = ref({})
  const segments = ref([])
  const speakerNames = ref({})
  const loadingTranscript = ref(false)
  const transcriptError = ref(null)
  const originalContent = ref('')

  /**
   * 載入逐字稿數據
   * @param {string} taskId - 任務 ID
   * @param {Function} getAudioUrl - 獲取音頻 URL 的函數
   * @param {Function} generateTimecodeMarkers - 生成時間碼標記的函數（可選）
   * @returns {Promise<Object>} 返回包含音頻 URL 和時間碼標記的對象
   */
  async function loadTranscript(taskId, getAudioUrl, generateTimecodeMarkers) {
    if (!taskId) {
      transcriptError.value = t('transcriptData.invalidTaskId')
      return null
    }

    loadingTranscript.value = true
    transcriptError.value = null

    try {
      // 獲取任務資訊
      const taskResponse = await api.get(NEW_ENDPOINTS.tasks.list)
      const task = taskResponse.data.tasks?.find(t => (t._id || t.task_id) === taskId)

      if (!task) {
        transcriptError.value = t('transcriptData.taskNotFound')
        return null
      }

      // 初始化當前逐字稿
      currentTranscript.value = {
        task_id: task.task_id,
        filename: task.file?.filename || task.filename,
        custom_name: task.custom_name,
        created_at: task.timestamps?.completed_at || task.timestamps?.created_at,
        text_length: task.result?.text_length || task.text_length,
        duration_text: task.duration_text,
        hasAudio: !!(task.result?.audio_file || task.audio_file),
        task_type: task.task_type || 'paragraph',
        content: ''
      }

      console.log('📋 任務類型:', currentTranscript.value.task_type)

      // 準備返回值
      const result = {
        audioUrl: null,
        timecodeMarkers: []
      }

      // 初始化音檔 URL
      if (currentTranscript.value.hasAudio && getAudioUrl) {
        result.audioUrl = getAudioUrl(task.task_id)
      }

      // 並行獲取逐字稿和 segments
      const [transcriptResponse, segmentsResponse] = await Promise.all([
        api.get(NEW_ENDPOINTS.transcriptions.download(taskId), {
          responseType: 'text'
        }),
        api.get(NEW_ENDPOINTS.transcriptions.segments(taskId)).catch(err => {
          console.log('無法獲取 segments:', err)
          return null
        })
      ])

      currentTranscript.value.content = transcriptResponse.data
      originalContent.value = transcriptResponse.data

      // 如果有 segments 數據，存儲並生成時間碼標記
      if (segmentsResponse && segmentsResponse.data.segments) {
        segments.value = segmentsResponse.data.segments

        // 載入講者名稱對應
        if (segmentsResponse.data.speaker_names) {
          speakerNames.value = segmentsResponse.data.speaker_names
          console.log('✅ 載入講者名稱:', speakerNames.value)
        }

        if (generateTimecodeMarkers) {
          result.timecodeMarkers = generateTimecodeMarkers(segments.value)
          console.log('✅ 生成時間碼標記:', result.timecodeMarkers.length, '個')
        }
      }

      loadingTranscript.value = false
      return result

    } catch (error) {
      console.error('載入逐字稿失敗:', error)
      transcriptError.value = t('transcriptData.loadTranscriptFailed')
      loadingTranscript.value = false
      return null
    }
  }

  /**
   * 儲存逐字稿內容
   * @param {string} content - 要儲存的文字內容
   * @param {Array} segments - 要儲存的 segments 數據（字幕模式使用）
   * @param {string} mode - 顯示模式 ('paragraph' | 'subtitle')
   * @returns {Promise<boolean>} 儲存是否成功
   */
  async function saveTranscript(content, segments = null, mode = 'paragraph') {
    // 檢查是否有變更
    if (content === originalContent.value && !segments) {
      return true
    }

    try {
      const payload = { text: content }

      // 如果是字幕模式，同時發送 segments
      if (segments) {
        payload.segments = segments
      }

      await api.put(
        NEW_ENDPOINTS.transcriptions.updateContent(currentTranscript.value.task_id),
        payload
      )

      // 更新原始內容和當前內容
      originalContent.value = content
      currentTranscript.value.content = content

      // 如果有更新 segments，也要更新本地的 segments 資料
      if (segments) {
        segments.value = segments
        console.log(`✅ 已更新本地 segments 資料`)
      }

      // 顯示成功通知
      if (showNotification) {
        showNotification({
          title: t('transcriptData.saveSuccess'),
          message: segments ? t('transcriptData.transcriptAndSubtitleUpdated') : t('transcriptData.transcriptUpdated'),
          type: 'success'
        })
      }

      return true

    } catch (error) {
      console.error('儲存失敗:', error)

      if (showNotification) {
        showNotification({
          title: t('transcriptData.saveFailed'),
          message: error.message || t('transcriptData.unknownError'),
          type: 'error'
        })
      }

      return false
    }
  }

  /**
   * 更新任務名稱
   * @param {string} newName - 新的任務名稱
   * @returns {Promise<boolean>} 更新是否成功
   */
  async function updateTaskName(newName) {
    const trimmedName = newName.trim()

    if (!trimmedName || trimmedName === currentTranscript.value.custom_name) {
      return false
    }

    try {
      await api.put(
        NEW_ENDPOINTS.transcriptions.updateMetadata(currentTranscript.value.task_id),
        { title: trimmedName }
      )

      currentTranscript.value.custom_name = trimmedName
      return true

    } catch (error) {
      console.error('更新任務名稱失敗:', error)

      if (showNotification) {
        showNotification({
          title: t('transcriptData.updateFailed'),
          message: t('transcriptData.cannotUpdateTaskName'),
          type: 'error'
        })
      }

      return false
    }
  }

  /**
   * 更新講者名稱對應
   * @param {Object} newSpeakerNames - 講者代碼與名稱的對應字典
   * @returns {Promise<boolean>} 更新是否成功
   */
  async function updateSpeakerNames(newSpeakerNames) {
    try {
      await api.put(
        NEW_ENDPOINTS.transcriptions.updateSpeakerNames(currentTranscript.value.task_id),
        newSpeakerNames
      )

      speakerNames.value = newSpeakerNames
      console.log('✅ 講者名稱已更新:', newSpeakerNames)
      return true

    } catch (error) {
      console.error('更新講者名稱失敗:', error)

      if (showNotification) {
        showNotification({
          title: t('transcriptData.updateFailed'),
          message: t('transcriptData.cannotUpdateSpeakerNames'),
          type: 'error'
        })
      }

      return false
    }
  }

  return {
    // 狀態
    currentTranscript,
    segments,
    speakerNames,
    loadingTranscript,
    transcriptError,
    originalContent,

    // 方法
    loadTranscript,
    saveTranscript,
    updateTaskName,
    updateSpeakerNames
  }
}
