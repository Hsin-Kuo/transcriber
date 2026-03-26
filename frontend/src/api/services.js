/**
 * API 服務層
 * 封裝所有 API 調用，提供統一的介面
 */

import api from '../utils/api.js'
import { NEW_ENDPOINTS } from './endpoints.js'
import { needsChunking, uploadChunked } from '../utils/chunkedUpload.js'

/**
 * 轉錄服務
 */
export const transcriptionService = {
  /**
   * 建立轉錄任務
   * @param {FormData} formData - 包含音檔和參數的表單資料
   * @returns {Promise} API 響應
   */
  async create(formData, { onProgress } = {}) {
    // 單檔模式：檢查是否需要分片上傳
    const file = formData.get('file')
    if (file && needsChunking(file)) {
      const uploadId = await uploadChunked(file, { onProgress })
      formData.delete('file')
      formData.append('upload_id', uploadId)
    }

    // 合併模式：多個檔案可能總大小超過 Cloudflare 100MB 限制
    // 逐一分片上傳後，用 upload_ids 替代
    const mergeFiles = formData.getAll('files')
    if (mergeFiles.length > 0) {
      const totalSize = mergeFiles.reduce((sum, f) => sum + f.size, 0)
      if (totalSize >= 95 * 1024 * 1024) {
        const uploadIds = []
        let done = 0
        for (const f of mergeFiles) {
          const uploadId = await uploadChunked(f, {
            onProgress: onProgress
              ? (pct) => {
                  const overall = Math.round(((done + pct / 100) / mergeFiles.length) * 100)
                  onProgress(overall)
                }
              : undefined,
          })
          uploadIds.push(uploadId)
          done++
        }
        formData.delete('files')
        formData.append('merge_upload_ids', JSON.stringify(uploadIds))
        if (onProgress) onProgress(100)
      }
    }

    const response = await api.post(NEW_ENDPOINTS.transcriptions.create, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
    })
    return response.data
  },

  /**
   * 下載轉錄結果
   * @param {string} taskId - 任務 ID
   * @returns {Promise} Blob 響應
   */
  async download(taskId) {
    const response = await api.get(NEW_ENDPOINTS.transcriptions.download(taskId), {
      responseType: 'blob'
    })
    return response
  },

  /**
   * 獲取音檔 URL
   * @param {string} taskId - 任務 ID
   * @param {string} token - 認證 token
   * @returns {string} 音檔 URL
   */
  getAudioUrl(taskId, token) {
    const API_BASE = import.meta.env.VITE_API_URL ?? ''
    return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?token=${encodeURIComponent(token)}`
  },

  /**
   * 獲取時間軸片段
   * @param {string} taskId - 任務 ID
   * @returns {Promise} 時間軸片段資料
   */
  async getSegments(taskId) {
    const response = await api.get(NEW_ENDPOINTS.transcriptions.segments(taskId))
    return response.data
  },

  /**
   * 更新轉錄內容
   * @param {string} taskId - 任務 ID
   * @param {string} content - 新的轉錄內容
   * @returns {Promise} API 響應
   */
  async updateContent(taskId, content) {
    const response = await api.put(NEW_ENDPOINTS.transcriptions.updateContent(taskId), {
      content
    })
    return response.data
  },

  /**
   * 更新元數據
   * @param {string} taskId - 任務 ID
   * @param {object} metadata - 元數據（如 custom_name）
   * @returns {Promise} API 響應
   */
  async updateMetadata(taskId, metadata) {
    const response = await api.put(NEW_ENDPOINTS.transcriptions.updateMetadata(taskId), metadata)
    return response.data
  },

  /**
   * 批次建立轉錄任務
   * @param {FormData} formData - 包含多個音檔和配置的表單資料
   *   - files: 多個音檔
   *   - default_config: JSON 字串，包含 taskType, diarize, maxSpeakers, language, tags
   *   - overrides: JSON 字串，格式 {"0": {tags, customName}, ...}
   * @returns {Promise} 批次建立結果
   */
  async createBatch(formData, { onProgress, onFileProgress } = {}) {
    // 檢查是否有大檔案需要分片上傳
    const files = formData.getAll('files')
    const chunkedMap = {} // { 原始索引: upload_id }
    const smallFiles = [] // 小檔案保留直接上傳

    const totalFiles = files.length
    let chunkedDone = 0
    const chunkedTotal = files.filter((f) => needsChunking(f)).length

    for (let i = 0; i < files.length; i++) {
      if (needsChunking(files[i])) {
        if (onFileProgress) onFileProgress(chunkedDone + 1, totalFiles)
        const uploadId = await uploadChunked(files[i], {
          onProgress: onProgress
            ? (pct) => {
                // 整體進度 = (已完成檔數 + 當前進度%) / 總檔數
                const overall = Math.round(((chunkedDone + pct / 100) / totalFiles) * 100)
                onProgress(overall)
              }
            : undefined,
        })
        chunkedMap[String(i)] = uploadId
        chunkedDone++
        if (onProgress) onProgress(Math.round((chunkedDone / totalFiles) * 100))
      } else {
        smallFiles.push({ index: i, file: files[i] })
      }
    }

    // 重建 formData：只保留小檔案 + 加入 upload_ids
    formData.delete('files')
    for (const { file } of smallFiles) {
      formData.append('files', file)
    }
    if (Object.keys(chunkedMap).length > 0) {
      formData.append('upload_ids', JSON.stringify(chunkedMap))
    }

    // 提交建立任務（小檔案在這一步上傳）
    if (onFileProgress) onFileProgress(totalFiles, totalFiles)
    const response = await api.post(NEW_ENDPOINTS.transcriptions.createBatch, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
    })
    if (onProgress) onProgress(100)
    return response.data
  },
}

/**
 * 任務服務
 */
export const taskService = {
  /**
   * 獲取任務列表
   * @param {object} params - 查詢參數（如 status, limit, skip）
   * @returns {Promise} 任務列表
   */
  async list(params = {}) {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, { params })
    return response.data
  },

  /**
   * 獲取單個任務
   * @param {string} taskId - 任務 ID
   * @returns {Promise} 任務資料
   */
  async get(taskId) {
    const response = await api.get(NEW_ENDPOINTS.tasks.get(taskId))
    return response.data
  },

  /**
   * 獲取任務列表（所有狀態）
   * @returns {Promise} 任務列表（舊格式兼容）
   */
  async getActiveList() {
    const response = await api.get(NEW_ENDPOINTS.tasks.list)

    // 轉換為舊格式以保持兼容性
    const tasks = response.data.tasks || response.data || []
    return {
      all_tasks: tasks,
      total: response.data.total || tasks.length
    }
  },

  /**
   * 獲取最近任務預覽
   * @param {number} limit - 限制數量（預設 5）
   * @returns {Promise} 最近任務列表
   */
  async getRecentPreview(limit = 5) {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, {
      params: { limit }
    })
    return response.data
  },

  /**
   * 取消任務
   * @param {string} taskId - 任務 ID
   * @returns {Promise} API 響應
   */
  async cancel(taskId) {
    const response = await api.post(NEW_ENDPOINTS.tasks.cancel(taskId))
    return response.data
  },

  /**
   * 刪除任務
   * @param {string} taskId - 任務 ID
   * @returns {Promise} API 響應
   */
  async delete(taskId) {
    const response = await api.delete(NEW_ENDPOINTS.tasks.delete(taskId))
    return response.data
  },

  /**
   * 獲取 SSE 事件 URL
   * @param {string} taskId - 任務 ID
   * @param {string} token - 認證 token
   * @returns {string} SSE URL
   */
  getEventsUrl(taskId, token) {
    const API_BASE = import.meta.env.VITE_API_URL ?? ''
    return `${API_BASE}${NEW_ENDPOINTS.tasks.events(taskId)}?token=${token}`
  },

  /**
   * 獲取使用者所有標籤
   * @returns {Promise} 標籤列表
   */
  async getAllTags() {
    const response = await api.get(NEW_ENDPOINTS.tasks.tags)
    return response.data
  },
}


/**
 * AI 摘要服務
 */
export const summaryService = {
  /**
   * 生成 AI 摘要
   * @param {string} taskId - 任務 ID
   * @param {string} mode - 顯示模式 (paragraph/subtitle)
   * @returns {Promise} 生成結果
   */
  async generate(taskId, mode = 'paragraph') {
    const response = await api.post(NEW_ENDPOINTS.summaries.generate(taskId), null, {
      params: { mode }
    })
    return response.data
  },

  /**
   * 獲取摘要
   * @param {string} taskId - 任務 ID
   * @returns {Promise} 摘要資料
   */
  async get(taskId) {
    const response = await api.get(NEW_ENDPOINTS.summaries.get(taskId))
    return response.data
  },

  /**
   * 刪除摘要
   * @param {string} taskId - 任務 ID
   * @returns {Promise} API 響應
   */
  async delete(taskId) {
    const response = await api.delete(NEW_ENDPOINTS.summaries.delete(taskId))
    return response.data
  }
}

/**
 * 匯出所有服務
 */
export default {
  transcriptionService,
  taskService,
  summaryService,
}
