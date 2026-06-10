/**
 * 分片上傳工具 — 解決 Cloudflare 100MB 上傳限制
 *
 * 檔案 < 95MB：不需要分片，走原本的單次上傳
 * 檔案 >= 95MB：自動切片（每片 90MB），逐片上傳後由後端組裝
 */

import api from './api.js'
import { NEW_ENDPOINTS } from '../api/endpoints.js'

const CHUNK_THRESHOLD = 95 * 1024 * 1024 // 95 MB
const CHUNK_SIZE = 90 * 1024 * 1024 // 90 MB
const MAX_RETRIES = 3
const RETRY_DELAY_MS = 2000
// 對齊後端 USER_CHUNK_CONCURRENCY（src/routers/uploads.py）。
// 超過此值 chunk 會排隊在 user semaphore 上等不到效益，反而吃 nginx 429 風險。
const PARALLEL_CHUNKS = 3

// 單檔上限：須與後端 MAX_UPLOAD_SIZE_MB 一致（預設 3 GB）
export const MAX_UPLOAD_SIZE_MB = 3072
const MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

/**
 * 判斷檔案是否需要分片上傳
 * @param {File} file
 * @returns {boolean}
 */
export function needsChunking(file) {
  return file.size >= CHUNK_THRESHOLD
}

/**
 * 判斷檔案是否超過單檔上限
 * @param {File} file
 * @returns {boolean}
 */
export function exceedsMaxSize(file) {
  return file.size > MAX_UPLOAD_SIZE
}

/**
 * 分片上傳檔案
 * @param {File} file - 要上傳的檔案
 * @param {object} options
 * @param {function} [options.onProgress] - 進度回調 (0-100)
 * @param {AbortSignal} [options.signal] - 取消信號；abort 後進行中的請求會中止、整體 throw
 * @returns {Promise<string>} upload_id
 */
export async function uploadChunked(file, { onProgress, signal } = {}) {
  // 1. 初始化上傳
  const initRes = await api.post(NEW_ENDPOINTS.uploads.init, null, {
    params: { filename: file.name, total_size: file.size },
    signal,
  })
  const { upload_id, total_chunks } = initRes.data

  // 2. Worker pool 並行上傳（PARALLEL_CHUNKS 個 worker 從共享 queue 各自取 index）
  const queue = Array.from({ length: total_chunks }, (_, i) => i)
  let completed = 0
  let aborted = false

  async function worker() {
    while (!aborted && queue.length > 0) {
      // 使用者取消：停止取新 chunk，讓 worker 收斂
      if (signal?.aborted) {
        aborted = true
        return
      }
      // JS single-thread，shift() 原子；多 worker 不會搶到同 index
      const i = queue.shift()
      if (i === undefined) return
      try {
        const start = i * CHUNK_SIZE
        const end = Math.min(start + CHUNK_SIZE, file.size)
        const blob = file.slice(start, end)
        await uploadChunkWithRetry(upload_id, i, blob, signal)
        completed++
        if (onProgress) {
          onProgress(Math.round((completed / total_chunks) * 100))
        }
      } catch (err) {
        // 任一 chunk 重試耗盡（或被取消）：通知其他 worker 停下、整體 fail-fast
        aborted = true
        throw err
      }
    }
  }

  const workerCount = Math.min(PARALLEL_CHUNKS, total_chunks)
  await Promise.all(Array.from({ length: workerCount }, () => worker()))

  // 3. 完成組裝
  const completeRes = await api.post(NEW_ENDPOINTS.uploads.complete(upload_id), null, { signal })
  return completeRes.data.upload_id
}

/**
 * 上傳單個 chunk，失敗自動重試
 * 只對 transient 錯誤（網路 / 5xx / 429）重試；4xx (400/403/404/409/413) 是永久錯誤直接 throw
 */
async function uploadChunkWithRetry(uploadId, chunkIndex, blob, signal) {
  let lastError
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const form = new FormData()
      form.append('file', blob)
      await api.post(
        NEW_ENDPOINTS.uploads.chunk(uploadId, chunkIndex),
        form,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 600000, // 10 分鐘（單片最大 90MB）
          signal,
        },
      )
      return
    } catch (err) {
      lastError = err
      // 使用者取消（axios CanceledError）：不重試，直接往上拋
      if (signal?.aborted || err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') {
        throw err
      }
      // 4xx 永久錯誤不重試（429 例外：rate limit 是 transient）
      const status = err?.response?.status
      if (status && status >= 400 && status < 500 && status !== 429) {
        throw err
      }
      if (attempt < MAX_RETRIES - 1) {
        console.warn(`Chunk ${chunkIndex} 上傳失敗 (第 ${attempt + 1} 次)，${RETRY_DELAY_MS}ms 後重試...`)
        await sleep(RETRY_DELAY_MS)
      }
    }
  }
  throw lastError
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
