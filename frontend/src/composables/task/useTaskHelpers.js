/**
 * Task Helpers Composable
 * 提供任務顯示和狀態判斷的輔助函數
 */
export function useTaskHelpers($t) {
  /**
   * 獲取狀態的顯示文字
   * @param {string} status - 任務狀態
   * @returns {string} 狀態顯示文字
   */
  function getStatusText(status) {
    const statusMap = {
      pending: $t ? $t('taskList.pending') : 'Pending',
      processing: $t ? $t('taskList.processing') : 'Processing',
      completed: $t ? $t('taskList.completed') : 'Completed',
      failed: $t ? $t('taskList.failed') : 'Failed',
      cancelled: $t ? $t('taskList.cancelled') : 'Cancelled',
      canceling: $t ? $t('taskList.canceling') : 'Canceling'
    }
    return statusMap[status] || status
  }

  /**
   * 格式化音訊時長
   * @param {Object} task - 任務對象
   * @returns {string|null} 格式化的時長（MM:SS）
   */
  function getAudioDuration(task) {
    // 優先使用新的 audio_duration_seconds 欄位（音檔實際時長）
    const duration = task.stats?.audio_duration_seconds || task.audio_duration_seconds
    if (!duration) {
      return null
    }

    const minutes = Math.floor(duration / 60)
    const seconds = Math.floor(duration % 60)

    if (minutes > 0) {
      return `${minutes}:${seconds.toString().padStart(2, '0')}`
    } else {
      return `0:${seconds.toString().padStart(2, '0')}`
    }
  }

  /**
   * 檢查任務是否已完成
   * @param {Object} task - 任務對象
   * @returns {boolean}
   */
  function isCompleted(task) {
    return task.status === 'completed'
  }

  /**
   * 檢查任務是否正在處理
   * @param {Object} task - 任務對象
   * @returns {boolean}
   */
  function isProcessing(task) {
    return task.status === 'processing'
  }

  /**
   * 檢查任務是否失敗
   * @param {Object} task - 任務對象
   * @returns {boolean}
   */
  function isFailed(task) {
    return task.status === 'failed'
  }

  /**
   * 檢查任務是否等待中
   * @param {Object} task - 任務對象
   * @returns {boolean}
   */
  function isPending(task) {
    return task.status === 'pending'
  }

  /**
   * 計算進度條寬度
   * @param {Object} task - 任務對象
   * @returns {string} 進度百分比（例如 "50%"）
   */
  function getProgressWidth(task) {
    if (isCompleted(task)) return '100%'
    if (isFailed(task)) return '100%'

    // 優先使用基於時間權重的進度百分比
    if (task.progress_percentage !== undefined && task.progress_percentage !== null) {
      const percentage = Math.min(Math.max(task.progress_percentage, 2), 99)
      return `${percentage}%`
    }

    // 後備：如果有 chunk 資訊，根據完成數量計算簡單進度
    if (isProcessing(task) && task.total_chunks && task.completed_chunks !== undefined) {
      const percentage = (task.completed_chunks / task.total_chunks) * 100
      return `${Math.min(Math.max(percentage, 5), 95)}%`
    }

    // 預設進度
    if (isProcessing(task)) return '30%'
    return '10%'
  }

  /**
   * 檢查任務是否應該展開（顯示進度）
   * @param {string} taskId - 任務 ID
   * @param {Array} tasks - 任務列表
   * @returns {boolean}
   */
  function isTaskExpanded(taskId, tasks) {
    const task = tasks.find(t => t.task_id === taskId)
    if (!task) return false
    // 只有 pending 和 processing 狀態的任務才展開
    return ['pending', 'processing'].includes(task.status)
  }

  /**
   * 格式化秒數為時間字符串
   * @param {number} seconds - 秒數
   * @returns {string} 格式化的時間（例如 "5分30秒"）
   */
  function formatTime(seconds) {
    if (!seconds || seconds < 0) return ''

    const minutes = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)

    if (minutes > 0) {
      return $t
        ? $t('taskList.timeFormat', { minutes, seconds: secs })
        : `${minutes}m ${secs}s`
    } else {
      return $t
        ? $t('taskList.secondsFormat', { seconds: secs })
        : `${secs}s`
    }
  }

  return {
    getStatusText,
    getAudioDuration,
    isCompleted,
    isProcessing,
    isFailed,
    isPending,
    getProgressWidth,
    isTaskExpanded,
    formatTime
  }
}
