import { ref } from 'vue'
import { ensureFreshAccessToken } from '../../utils/api'

/**
 * 自動儲存閘門 Composable（single-flight + trailing）
 *
 * 設計定案見 memory/project_autosave_task_detail.md：
 * - 所有寫 PUT /content 的動作（段落文字、字幕文字、字幕改說話者）都過這道閘，
 *   否則 single-flight 是假的、會回到亂序覆蓋。
 * - 同時只允許一筆 in-flight；飛行中有新變動只記「最新一份」，等回來再補送（trailing）。
 * - 失敗退避重試；401 由 api.ts 攔截器被動刷新重送，這裡再用 ensureFreshAccessToken 主動避開。
 * - 三態 status 供 header 指示器顯示；isDirty 供 beforeunload / 離開路由判斷。
 *
 * @param {Object}   opts
 * @param {Function} opts.saveFn      async (payload) => boolean，包住 saveTranscript
 * @param {number}   [opts.debounceMs=2000]
 * @param {number}   [opts.maxRetries=3]
 * @param {number[]} [opts.retryDelays=[1000,3000,6000]]
 * @param {number}   [opts.savedDisplayMs=2000] 「已儲存」狀態顯示多久後回 idle
 * @param {Function} [opts.sleep] 注入點（測試用）
 */
export function useAutosave({
  saveFn,
  debounceMs = 2000,
  maxRetries = 3,
  retryDelays = [1000, 3000, 6000],
  savedDisplayMs = 2000,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
} = {}) {
  // 'idle' | 'saving' | 'saved' | 'error'
  const status = ref('idle')
  // 還有未落地的變更（debounce 未 flush，或最後一次存檔失敗）
  const isDirty = ref(false)
  const lastError = ref(null)

  let debounceTimer = null
  let savedResetTimer = null
  let latestProvider = null   // trailing：最新一份待存 payload provider
  let running = false         // single-flight 鎖
  let settleResolvers = []    // flush() 等待用

  function notifySettled() {
    const resolvers = settleResolvers
    settleResolvers = []
    resolvers.forEach((resolve) => resolve())
  }

  function clearSavedReset() {
    if (savedResetTimer) {
      clearTimeout(savedResetTimer)
      savedResetTimer = null
    }
  }

  function scheduleSavedReset() {
    clearSavedReset()
    savedResetTimer = setTimeout(() => {
      savedResetTimer = null
      if (status.value === 'saved') status.value = 'idle'
    }, savedDisplayMs)
  }

  /**
   * 排程一次自動儲存（debounce）。
   * @param {Function} provider 回傳 payload 的函式，於實際送出當下才呼叫，
   *                            確保送出的是「當下最新」內容而非排程當時的快照。
   */
  function schedule(provider) {
    latestProvider = provider
    isDirty.value = true
    clearSavedReset()
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      void pump()
    }, debounceMs)
  }

  async function attemptSave(payload) {
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        // 主動刷新：避開 access token 即將過期造成的 401 往返
        // （api.ts 被動攔截器仍是最後防線）
        await ensureFreshAccessToken()
        const ok = await saveFn(payload)
        if (ok) {
          lastError.value = null
          return true
        }
      } catch (err) {
        lastError.value = err
      }
      if (attempt < maxRetries) {
        await sleep(retryDelays[Math.min(attempt, retryDelays.length - 1)])
      }
    }
    return false
  }

  // single-flight pump：把 latestProvider 排乾。飛行中新進的變動會在 while 迴圈被接走（trailing）。
  async function pump() {
    if (running) return
    if (!latestProvider) {
      notifySettled()
      return
    }
    running = true
    status.value = 'saving'

    while (latestProvider) {
      const provider = latestProvider
      latestProvider = null
      const ok = await attemptSave(provider())
      if (!ok) {
        // 重試耗盡：保留這份 payload 等下次 schedule/flush 再試；維持 dirty + error
        if (!latestProvider) latestProvider = provider
        status.value = 'error'
        running = false
        notifySettled()
        return
      }
    }

    running = false
    isDirty.value = false
    status.value = 'saved'
    scheduleSavedReset()
    notifySettled()
  }

  /**
   * 立即 flush（blur / 退出編輯 / 離開路由用）。取消 debounce、把待存的排乾、等落地。
   * @returns {Promise<boolean>} 全部成功落地回 true；仍有失敗回 false。
   */
  async function flush() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    if (!latestProvider && !running) {
      return status.value !== 'error'
    }
    const settled = new Promise((resolve) => settleResolvers.push(resolve))
    void pump()
    await settled
    return status.value !== 'error' && !isDirty.value
  }

  function cancel() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    clearSavedReset()
    latestProvider = null
  }

  return {
    status,
    isDirty,
    lastError,
    schedule,
    flush,
    cancel,
  }
}
