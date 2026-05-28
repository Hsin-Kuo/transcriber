/**
 * API 端點管理
 * 統一管理所有 API 端點。Endpoint 函式 typed 後 caller 傳錯參數型別會立刻 IDE warning。
 */

export const NEW_ENDPOINTS = {
  // 轉錄相關
  transcriptions: {
    create: '/transcriptions',
    createBatch: '/transcriptions/batch',
    download: (taskId: string) => `/transcriptions/${taskId}/download`,
    audio: (taskId: string) => `/transcriptions/${taskId}/audio`,
    segments: (taskId: string) => `/transcriptions/${taskId}/segments`,
    updateContent: (taskId: string) => `/transcriptions/${taskId}/content`,
    updateMetadata: (taskId: string) => `/transcriptions/${taskId}/metadata`,
    updateSpeakerNames: (taskId: string) => `/transcriptions/${taskId}/speaker-names`,
    updateSubtitleSettings: (taskId: string) => `/transcriptions/${taskId}/subtitle-settings`,
    exportPdf: (taskId: string) => `/transcriptions/${taskId}/export/pdf`,
  },

  // 任務管理
  tasks: {
    list: '/tasks',
    recent: '/tasks/recent',
    tags: '/tasks/tags',
    get: (taskId: string) => `/tasks/${taskId}`,
    cancel: (taskId: string) => `/tasks/${taskId}/cancel`,
    delete: (taskId: string) => `/tasks/${taskId}`,
    events: (taskId: string) => `/tasks/${taskId}/events`,
    updateTags: (taskId: string) => `/tasks/${taskId}/tags`,
    updateKeepAudio: (taskId: string) => `/tasks/${taskId}/keep-audio`,
    batchDelete: '/tasks/batch/delete',
    batchTagsAdd: '/tasks/batch/tags/add',
    batchTagsRemove: '/tasks/batch/tags/remove',
  },

  // 標籤管理
  tags: {
    list: '/tags',
    get: (tagId: string) => `/tags/${tagId}`,
    create: '/tags',
    update: (tagId: string) => `/tags/${tagId}`,
    delete: (tagId: string) => `/tags/${tagId}`,
    updateOrder: '/tags/order',
    statistics: '/tags/statistics',
  },

  // 音檔合併
  audio: {
    merge: '/audio/merge',
    download: (filename: string) => `/audio/download/${filename}`,
  },

  // 分片上傳
  uploads: {
    init: '/uploads/init',
    chunk: (uploadId: string, chunkIndex: number) => `/uploads/${uploadId}/chunks/${chunkIndex}`,
    complete: (uploadId: string) => `/uploads/${uploadId}/complete`,
  },

  // 公開分享
  shared: {
    toggle: (taskId: string) => `/shared/${taskId}/toggle`,
    expiry: (taskId: string) => `/shared/${taskId}/expiry`,
    get: (token: string) => `/shared/${token}`,
    audio: (token: string) => `/shared/${token}/audio`,
  },

  // AI 摘要
  summaries: {
    generate: (taskId: string) => `/summaries/${taskId}`,
    get: (taskId: string) => `/summaries/${taskId}`,
    delete: (taskId: string) => `/summaries/${taskId}`,
  },

  // 訂閱管理
  subscriptions: {
    checkout: '/subscriptions/checkout',
    status: '/subscriptions/status',
    cancel: '/subscriptions/cancel',
    reactivate: '/subscriptions/reactivate',
    change: '/subscriptions/change',
    purchaseExtra: '/subscriptions/purchase-extra',
    packages: '/subscriptions/packages',
    orders: '/subscriptions/orders',
  },
} as const
