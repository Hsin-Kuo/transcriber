/**
 * API 服務層
 * 封裝所有 API 調用，提供統一的介面
 */

import api from '../utils/api.js'
import { NEW_ENDPOINTS } from './endpoints.js'

/**
 * 轉錄服務
 */
export const transcriptionService = {
  /**
   * 建立轉錄任務
   * @param {FormData} formData - 包含音檔和參數的表單資料
   * @returns {Promise} API 響應
   */
  async create(formData) {
    const response = await api.post(NEW_ENDPOINTS.transcriptions.create, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
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
    const API_BASE = import.meta.env.VITE_API_URL || 'http://192.168.0.59:8000'
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
    const API_BASE = import.meta.env.VITE_API_URL || 'http://192.168.0.59:8000'
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
 * 標籤服務
 */
export const tagService = {
  /**
   * 獲取所有標籤
   * @returns {Promise} 標籤列表
   */
  async list() {
    const response = await api.get(NEW_ENDPOINTS.tags.list)
    return response.data
  },

  /**
   * 獲取單個標籤
   * @param {string} tagId - 標籤 ID
   * @returns {Promise} 標籤資料
   */
  async get(tagId) {
    const response = await api.get(NEW_ENDPOINTS.tags.get(tagId))
    return response.data
  },

  /**
   * 建立標籤
   * @param {object} tagData - 標籤資料（name, color, description）
   * @returns {Promise} 建立的標籤
   */
  async create(tagData) {
    const response = await api.post(NEW_ENDPOINTS.tags.create, tagData)
    return response.data
  },

  /**
   * 更新標籤
   * @param {string} tagId - 標籤 ID
   * @param {object} tagData - 標籤資料
   * @returns {Promise} 更新後的標籤
   */
  async update(tagId, tagData) {
    const response = await api.put(NEW_ENDPOINTS.tags.update(tagId), tagData)
    return response.data
  },

  /**
   * 刪除標籤
   * @param {string} tagId - 標籤 ID
   * @returns {Promise} API 響應
   */
  async delete(tagId) {
    const response = await api.delete(NEW_ENDPOINTS.tags.delete(tagId))
    return response.data
  },

  /**
   * 更新標籤順序
   * @param {string[]} tagIds - 標籤 ID 陣列（按順序）
   * @returns {Promise} API 響應
   */
  async updateOrder(tagIds) {
    const response = await api.put(NEW_ENDPOINTS.tags.updateOrder, {
      tag_ids: tagIds
    })
    return response.data
  },

  /**
   * 獲取標籤統計
   * @returns {Promise} 標籤統計資料
   */
  async getStatistics() {
    const response = await api.get(NEW_ENDPOINTS.tags.statistics)
    return response.data
  },
}

/**
 * 舊 API 服務（向後兼容）
 * 這些方法仍然使用舊端點，用於未遷移的功能
 */
export const legacyService = {
  /**
   * 更新任務標籤
   */
  async updateTaskTags(taskId, tags) {
    const response = await api.put(NEW_ENDPOINTS.tasks.updateTags(taskId), { tags })
    return response.data
  },

  /**
   * 更新音檔保留狀態
   */
  async updateKeepAudio(taskId, keepAudio) {
    const response = await api.put(NEW_ENDPOINTS.tasks.updateKeepAudio(taskId), {
      keep_audio: keepAudio
    })
    return response.data
  },

  /**
   * 批次刪除任務
   */
  async batchDelete(taskIds) {
    const response = await api.post(NEW_ENDPOINTS.tasks.batchDelete, {
      task_ids: taskIds
    })
    return response.data
  },

  /**
   * 批次添加標籤
   */
  async batchAddTags(taskIds, tags) {
    const response = await api.post(NEW_ENDPOINTS.tasks.batchTagsAdd, {
      task_ids: taskIds,
      tags: tags
    })
    return response.data
  },

  /**
   * 批次移除標籤
   */
  async batchRemoveTags(taskIds, tags) {
    const response = await api.post(NEW_ENDPOINTS.tasks.batchTagsRemove, {
      task_ids: taskIds,
      tags: tags
    })
    return response.data
  },
}

/**
 * 音檔服務（新增）
 */
export const audioService = {
  /**
   * 合併多個音檔（僅用於下載功能）
   * 固定輸出格式：MP3 (16kHz, mono, 192kbps)
   * @param {File[]} files - 音檔陣列
   * @returns {Promise} 合併結果
   */
  async merge(files) {
    const formData = new FormData()

    files.forEach((file) => {
      formData.append('files', file)
    })

    const response = await api.post(NEW_ENDPOINTS.audio.merge, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    return response.data
  },

  /**
   * 下載合併後的音檔
   * @param {string} filename - 檔案名稱
   * @returns {Promise} Blob 響應
   */
  async download(filename) {
    const response = await api.get(NEW_ENDPOINTS.audio.download(filename), {
      responseType: 'blob'
    })
    return response.data
  }
}

/**
 * 匯出所有服務
 */
export default {
  transcriptionService,
  taskService,
  tagService,
  legacyService,
  audioService,
}
