/**
 * API 服務層（TypeScript）
 * 封裝所有 API 調用，提供型別安全的介面
 */

import api, { API_BASE } from '../utils/api'
import { NEW_ENDPOINTS } from './endpoints'
import { needsChunking, uploadChunked, CHUNK_THRESHOLD } from '../utils/chunkedUpload'

// ========== Response Types ==========

export interface TaskTimestamps {
  created_at?: string
  updated_at?: string
  completed_at?: string
}

export interface TaskFile {
  filename?: string
  size_mb?: number
}

export interface TaskResult {
  text_length?: number
  word_count?: number
  audio_file?: string | null
  audio_filename?: string | null
  transcription_file?: string
  transcription_filename?: string
  segments_file?: string
}

export interface Task {
  _id: string
  task_id?: string
  task_type?: 'paragraph' | 'subtitle'
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
  progress?: string
  progress_percentage?: number
  custom_name?: string
  tags?: string[]
  keep_audio?: boolean
  speaker_names?: Record<string, string>
  subtitle_settings?: Record<string, unknown>
  timestamps?: TaskTimestamps
  file?: TaskFile
  result?: TaskResult
  error?: string
  cancelling?: boolean
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
}

export interface ActiveListResponse {
  all_tasks: Task[]
  total: number
}

export interface Segment {
  start: number
  end: number
  text: string
  speaker?: string
}

export interface SegmentsResponse {
  segments: Segment[]
}

export interface TranscriptionCreateResponse {
  task_id: string
  status: string
}

export interface BatchCreateResponse {
  batch_id?: string
  total: number
  created?: number
  failed?: number
  tasks: Array<{
    task_id?: string
    filename: string
    status: string
    queue_position?: number
    // 失敗時的錯誤；額度不足為結構化物件 { code, message, quota }
    error?: string | { code?: string; message?: string; quota?: { type?: string } }
  }>
}

export interface SummaryContent {
  meta?: { type?: string; detected_topic?: string }
  summary?: string
  key_points?: Array<string | { text?: string; point?: string; content?: string }>
  highlights?: Array<string | { text?: string; point?: string; content?: string }>
  segments?: Array<{ topic: string; content: string; keywords?: string[] }>
  action_items?: Array<{ task: string; owner?: string; deadline?: string }>
}

export interface Summary {
  task_id: string
  status: string
  content?: SummaryContent
  created_at?: string
}

export interface ApiMessage {
  message: string
}

// ========== Service Options ==========

interface ProgressOptions {
  onProgress?: (percent: number) => void
  signal?: AbortSignal
}

interface BatchProgressOptions extends ProgressOptions {
  onFileProgress?: (current: number, total: number) => void
}

// ========== Transcription Service ==========

export const transcriptionService = {
  async create(formData: FormData, { onProgress, signal }: ProgressOptions = {}): Promise<TranscriptionCreateResponse> {
    const file = formData.get('file') as File | null
    if (file && needsChunking(file)) {
      const uploadId = await uploadChunked(file, { onProgress, signal })
      formData.delete('file')
      formData.append('upload_id', uploadId)
    }

    const mergeFiles = formData.getAll('files') as File[]
    if (mergeFiles.length > 0) {
      const totalSize = mergeFiles.reduce((sum, f) => sum + f.size, 0)
      if (totalSize >= CHUNK_THRESHOLD) {
        const uploadIds: string[] = []
        let done = 0
        for (const f of mergeFiles) {
          const uploadId = await uploadChunked(f, {
            signal,
            onProgress: onProgress
              ? (pct: number) => {
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
      signal,
    })
    return response.data
  },

  async download(taskId: string) {
    const response = await api.get(NEW_ENDPOINTS.transcriptions.download(taskId), {
      responseType: 'blob'
    })
    return response
  },

  getAudioUrl(taskId: string, token: string): string {
    return `${API_BASE}${NEW_ENDPOINTS.transcriptions.audio(taskId)}?token=${encodeURIComponent(token)}`
  },

  async getSegments(taskId: string): Promise<SegmentsResponse> {
    const response = await api.get(NEW_ENDPOINTS.transcriptions.segments(taskId))
    return response.data
  },

  async updateContent(taskId: string, content: string): Promise<ApiMessage> {
    const response = await api.put(NEW_ENDPOINTS.transcriptions.updateContent(taskId), {
      content
    })
    return response.data
  },

  async updateMetadata(taskId: string, metadata: Record<string, unknown>): Promise<ApiMessage> {
    const response = await api.put(NEW_ENDPOINTS.transcriptions.updateMetadata(taskId), metadata)
    return response.data
  },

  async createBatch(formData: FormData, { onProgress, onFileProgress, signal }: BatchProgressOptions = {}): Promise<BatchCreateResponse> {
    const files = formData.getAll('files') as File[]
    const chunkedMap: Record<string, string> = {}
    const smallFiles: Array<{ index: number; file: File }> = []

    // Cloudflare 限制整個 request body（~100MB）；分片與否必須看「全部檔案加總」而非
    // 逐檔判斷，否則兩個各自 <95MB 但相加破百的檔案會被塞進同一個 multipart，於後端
    // 之前就被 Cloudflare 擋下 413。對齊單檔 merge 路徑（create()）的加總邏輯：總和
    // 超過門檻時整批改走分片，讓 batch POST 的 body 只剩 metadata。
    const totalSize = files.reduce((sum, f) => sum + f.size, 0)
    const chunkAll = totalSize >= CHUNK_THRESHOLD

    const totalFiles = files.length
    let chunkedDone = 0

    for (let i = 0; i < files.length; i++) {
      if (chunkAll || needsChunking(files[i])) {
        if (onFileProgress) onFileProgress(chunkedDone + 1, totalFiles)
        const uploadId = await uploadChunked(files[i], {
          signal,
          onProgress: onProgress
            ? (pct: number) => {
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

    formData.delete('files')
    for (const { file } of smallFiles) {
      formData.append('files', file)
    }
    if (Object.keys(chunkedMap).length > 0) {
      formData.append('upload_ids', JSON.stringify(chunkedMap))
    }

    if (onFileProgress) onFileProgress(totalFiles, totalFiles)
    const response = await api.post(NEW_ENDPOINTS.transcriptions.createBatch, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 3600000,
      signal,
    })
    if (onProgress) onProgress(100)
    return response.data
  },
}

// ========== Task Service ==========

export const taskService = {
  async list(params: Record<string, unknown> = {}): Promise<TaskListResponse> {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, { params })
    return response.data
  },

  async get(taskId: string): Promise<Task> {
    const response = await api.get(NEW_ENDPOINTS.tasks.get(taskId))
    return response.data
  },

  async getActiveList(): Promise<ActiveListResponse> {
    const response = await api.get(NEW_ENDPOINTS.tasks.list)

    const tasks = response.data.tasks || response.data || []
    return {
      all_tasks: tasks,
      total: response.data.total || tasks.length
    }
  },

  async getRecentPreview(limit = 5): Promise<TaskListResponse> {
    const response = await api.get(NEW_ENDPOINTS.tasks.list, {
      params: { limit }
    })
    return response.data
  },

  async cancel(taskId: string): Promise<ApiMessage> {
    const response = await api.post(NEW_ENDPOINTS.tasks.cancel(taskId))
    return response.data
  },

  async delete(taskId: string): Promise<ApiMessage> {
    const response = await api.delete(NEW_ENDPOINTS.tasks.delete(taskId))
    return response.data
  },

  getEventsUrl(taskId: string, token: string): string {
    return `${API_BASE}${NEW_ENDPOINTS.tasks.events(taskId)}?token=${token}`
  },

  async getAllTags(): Promise<{ tags: Array<{ name: string; color?: string; order?: number }> }> {
    const response = await api.get(NEW_ENDPOINTS.tasks.tags)
    return response.data
  },
}

// ========== Summary Service ==========

export const summaryService = {
  async generate(taskId: string, mode: 'paragraph' | 'subtitle' = 'paragraph'): Promise<Summary> {
    const response = await api.post(NEW_ENDPOINTS.summaries.generate(taskId), null, {
      params: { mode }
    })
    return response.data
  },

  async get(taskId: string): Promise<Summary> {
    const response = await api.get(NEW_ENDPOINTS.summaries.get(taskId))
    return response.data
  },

  async delete(taskId: string): Promise<ApiMessage> {
    const response = await api.delete(NEW_ENDPOINTS.summaries.delete(taskId))
    return response.data
  },
}

export default {
  transcriptionService,
  taskService,
  summaryService,
}
