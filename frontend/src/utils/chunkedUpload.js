/**
 * 分片上傳工具 — 解決 Cloudflare 100MB 上傳限制
 *
 * 檔案 < 95MB：不需要分片，走原本的單次上傳
 * 檔案 >= 95MB：自動切片後逐片上傳，由後端組裝。
 * 切片大小以後端 /uploads/init 回傳的 chunk_size 為準（單一真實來源，
 * 避免前後端 chunk size drift）；CHUNK_SIZE 僅作為舊後端未回傳時的 fallback。
 */

import api, { ensureFreshAccessToken } from './api.js'
import { NEW_ENDPOINTS } from '../api/endpoints.js'

const CHUNK_THRESHOLD = 95 * 1024 * 1024 // 95 MB
// fallback only：實際切片大小以後端回傳的 chunk_size 為準（見 uploadChunked）
const CHUNK_SIZE = 16 * 1024 * 1024 // 16 MB
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
  // 切片大小以後端為準，舊後端未回傳時 fallback 到本地常數
  const chunkSize = initRes.data.chunk_size || CHUNK_SIZE

  // 取得 upload_id 後，任何失敗 / 取消都即時通知後端清掉半成品（不做續傳，
  // 留著只是佔後端磁碟到 grace sweep）。abort 是 best-effort，不阻斷原錯誤。
  try {
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
          const start = i * chunkSize
          const end = Math.min(start + chunkSize, file.size)
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

    // 3. 完成組裝（送出前同樣確保 token 新鮮，避免最後一步被 401 卡住）
    await ensureFreshAccessToken()
    const completeRes = await api.post(NEW_ENDPOINTS.uploads.complete(upload_id), null, { signal })
    return completeRes.data.upload_id
  } catch (err) {
    await abortUploadSession(upload_id)
    throw err
  }
}

/**
 * 主動通知後端中止上傳工作階段，即時回收半成品 temp_dir。
 * best-effort：清不掉（網路/已被清）就交給後端 grace sweep，不影響使用者流程。
 * 刻意不帶上傳的 signal——取消情境下 signal 已 aborted，帶了會讓這支 DELETE 也被取消。
 */
async function abortUploadSession(uploadId) {
  try {
    await api.delete(NEW_ENDPOINTS.uploads.abort(uploadId))
  } catch {
    /* 忽略：後端 periodic sweep 會兜底 */
  }
}

/**
 * 上傳單個 chunk，失敗自動重試
 * 只對 transient 錯誤（網路 / 5xx / 429）重試；4xx (400/403/404/409/413) 是永久錯誤直接 throw
 */
async function uploadChunkWithRetry(uploadId, chunkIndex, blob, signal) {
  let lastError
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      // 送出前主動刷新：大檔上傳跨越 token 效期時，先換新 token 再傳，
      // 避免整片上傳完才被 401 打回、又得重傳整片
      await ensureFreshAccessToken()
      const form = new FormData()
      form.append('file', blob)
      await api.post(
        NEW_ENDPOINTS.uploads.chunk(uploadId, chunkIndex),
        form,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 600000, // 10 分鐘（給慢線路充足餘裕）
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
