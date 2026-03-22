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
    createBatch: '/transcriptions/batch',
    download: (taskId) => `/transcriptions/${taskId}/download`,
    audio: (taskId) => `/transcriptions/${taskId}/audio`,
    segments: (taskId) => `/transcriptions/${taskId}/segments`,
    updateContent: (taskId) => `/transcriptions/${taskId}/content`,
    updateMetadata: (taskId) => `/transcriptions/${taskId}/metadata`,
    updateSpeakerNames: (taskId) => `/transcriptions/${taskId}/speaker-names`,
    updateSubtitleSettings: (taskId) => `/transcriptions/${taskId}/subtitle-settings`,
  },

  // 任務管理
  tasks: {
    list: '/tasks',
    recent: '/tasks/recent',
    tags: '/tasks/tags',
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

  // 音檔合併（新增）
  audio: {
    merge: '/audio/merge',
    download: (filename) => `/audio/download/${filename}`,
  },

  // 分片上傳
  uploads: {
    init: '/uploads/init',
    chunk: (uploadId, chunkIndex) => `/uploads/${uploadId}/chunks/${chunkIndex}`,
    complete: (uploadId) => `/uploads/${uploadId}/complete`,
  },

  // 公開分享
  shared: {
    toggle: (taskId) => `/shared/${taskId}/toggle`,
    get: (token) => `/shared/${token}`,
    audio: (token) => `/shared/${token}/audio`,
  },

  // AI 摘要
  summaries: {
    generate: (taskId) => `/summaries/${taskId}`,
    get: (taskId) => `/summaries/${taskId}`,
    delete: (taskId) => `/summaries/${taskId}`,
  },
}

