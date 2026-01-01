/**
 * API 端點管理
 * 統一管理所有 API 端點，方便遷移和維護
 */

/**
 * 新架構 API 端點
 */
export const NEW_ENDPOINTS = {
  // 轉錄相關
  transcriptions: {
    create: '/transcriptions',
    download: (taskId) => `/transcriptions/${taskId}/download`,
    audio: (taskId) => `/transcriptions/${taskId}/audio`,
    segments: (taskId) => `/transcriptions/${taskId}/segments`,
    updateContent: (taskId) => `/transcriptions/${taskId}/content`,
    updateMetadata: (taskId) => `/transcriptions/${taskId}/metadata`,
    updateSpeakerNames: (taskId) => `/transcriptions/${taskId}/speaker-names`,
  },

  // 任務管理
  tasks: {
    list: '/tasks',
    recent: '/tasks/recent',
    get: (taskId) => `/tasks/${taskId}`,
    cancel: (taskId) => `/tasks/${taskId}/cancel`,
    delete: (taskId) => `/tasks/${taskId}`,
    events: (taskId) => `/tasks/${taskId}/events`,
    updateTags: (taskId) => `/tasks/${taskId}/tags`,
    updateKeepAudio: (taskId) => `/tasks/${taskId}/keep-audio`,
    batchDelete: '/tasks/batch/delete',
    batchTagsAdd: '/tasks/batch/tags/add',
    batchTagsRemove: '/tasks/batch/tags/remove',
  },

  // 標籤管理
  tags: {
    list: '/tags',
    get: (tagId) => `/tags/${tagId}`,
    create: '/tags',
    update: (tagId) => `/tags/${tagId}`,
    delete: (tagId) => `/tags/${tagId}`,
    updateOrder: '/tags/order',
    statistics: '/tags/statistics',
  },
}

/**
 * 舊端點（向後兼容，逐步棄用）
 */
export const OLD_ENDPOINTS = {
  transcribe: '/transcribe',
  transcribeDownload: (taskId) => `/transcribe/${taskId}/download`,
  transcribeAudio: (taskId) => `/transcribe/${taskId}/audio`,
  transcribeSegments: (taskId) => `/transcribe/${taskId}/segments`,
  transcribeCancel: (taskId) => `/transcribe/${taskId}/cancel`,
  transcribeDelete: (taskId) => `/transcribe/${taskId}`,
  transcribeActiveList: '/transcribe/active/list',
  transcribeRecentPreview: '/transcribe/recent/preview',
  transcribeEvents: (taskId) => `/transcribe/${taskId}/events`,
  transcribeUpdateContent: (taskId) => `/transcribe/${taskId}/content`,
  transcribeUpdateMetadata: (taskId) => `/transcribe/${taskId}/metadata`,
  transcribeUpdateTags: (taskId) => `/transcribe/${taskId}/tags`,
  transcribeUpdateKeepAudio: (taskId) => `/transcribe/${taskId}/keep-audio`,
  transcribeBatchDelete: '/transcribe/batch/delete',
  transcribeBatchTagsAdd: '/transcribe/batch/tags/add',
  transcribeBatchTagsRemove: '/transcribe/batch/tags/remove',
}

/**
 * 獲取當前使用的端點配置
 * 可通過環境變數控制使用新端點或舊端點
 */
export function useNewEndpoints() {
  // 預設使用新端點，除非明確設定為 false
  return import.meta.env.VITE_USE_NEW_API !== 'false'
}

/**
 * 遷移輔助函數：優先使用新端點，失敗時回退到舊端點
 */
export function getEndpoint(newEndpoint, oldEndpoint) {
  return useNewEndpoints() ? newEndpoint : oldEndpoint
}
