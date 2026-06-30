import { describe, it, expect, vi, beforeEach } from 'vitest'

// api.ts 的 ensureFreshAccessToken 在測試環境不該真的打 /auth/refresh
vi.mock('../../utils/api', () => ({
  ensureFreshAccessToken: vi.fn().mockResolvedValue(undefined),
}))

import { useAutosave } from './useAutosave.js'

// 等 debounce(=1ms) + 微任務排乾
const tick = () => new Promise((r) => setTimeout(r, 5))

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

// 重試延遲注入成立即 resolve，讓退避測試不必真的等
const noSleep = () => Promise.resolve()

describe('useAutosave', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('debounce 後才送出，且送的是最新一份內容', async () => {
    const saveFn = vi.fn().mockResolvedValue(true)
    const as = useAutosave({ saveFn, debounceMs: 1, sleep: noSleep })

    as.schedule(() => 'v1')
    as.schedule(() => 'v2')   // debounce 期間覆蓋
    expect(saveFn).not.toHaveBeenCalled()

    await tick()
    expect(saveFn).toHaveBeenCalledTimes(1)
    expect(saveFn).toHaveBeenCalledWith('v2')
    expect(as.status.value).toBe('saved')
    expect(as.isDirty.value).toBe(false)
  })

  it('single-flight：飛行中不併發，且 trailing 只送最新（中途的被合併吃掉）', async () => {
    const calls = []
    let inFlight = 0
    let maxConcurrent = 0
    const gate = deferred()
    let first = true

    const saveFn = vi.fn(async (payload) => {
      inFlight++
      maxConcurrent = Math.max(maxConcurrent, inFlight)
      calls.push(payload)
      if (first) {
        first = false
        await gate.promise   // 卡住第一筆，模擬慢請求
      }
      inFlight--
      return true
    })

    const as = useAutosave({ saveFn, debounceMs: 1, sleep: noSleep })

    as.schedule(() => 'A')
    await tick()                       // pump 啟動，saveFn('A') 卡在 gate
    expect(saveFn).toHaveBeenCalledTimes(1)

    as.schedule(() => 'B')             // 飛行中：記為 latest
    as.schedule(() => 'C')             // 再覆蓋：latest = C，B 被吃掉
    await tick()
    expect(saveFn).toHaveBeenCalledTimes(1)   // 仍未併發

    gate.resolve()                     // 放行第一筆
    await tick()

    expect(calls).toEqual(['A', 'C'])  // B 被合併，never sent
    expect(maxConcurrent).toBe(1)      // 全程單飛
    expect(as.status.value).toBe('saved')
  })

  it('退避重試：失敗兩次後成功，status 收斂為 saved', async () => {
    const saveFn = vi.fn()
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce(true)
    const sleep = vi.fn(noSleep)

    const as = useAutosave({ saveFn, debounceMs: 1, maxRetries: 3, sleep })

    as.schedule(() => 'x')
    await tick()

    expect(saveFn).toHaveBeenCalledTimes(3)
    expect(sleep).toHaveBeenCalledTimes(2)   // 兩次失敗 → 兩次退避
    expect(as.status.value).toBe('saved')
    expect(as.isDirty.value).toBe(false)
  })

  it('重試耗盡：status=error 且保持 dirty，flush 回傳 false', async () => {
    const saveFn = vi.fn().mockResolvedValue(false)
    const as = useAutosave({ saveFn, debounceMs: 1, maxRetries: 2, sleep: noSleep })

    as.schedule(() => 'x')
    await tick()

    expect(saveFn).toHaveBeenCalledTimes(3)   // 1 + 2 retries
    expect(as.status.value).toBe('error')
    expect(as.isDirty.value).toBe(true)

    const ok = await as.flush()
    expect(ok).toBe(false)
  })

  it('saveFn 拋例外也計入重試，最終耗盡標 error 並保存 lastError', async () => {
    const boom = new Error('network down')
    const saveFn = vi.fn().mockRejectedValue(boom)
    const as = useAutosave({ saveFn, debounceMs: 1, maxRetries: 1, sleep: noSleep })

    as.schedule(() => 'x')
    await tick()

    expect(saveFn).toHaveBeenCalledTimes(2)
    expect(as.status.value).toBe('error')
    expect(as.lastError.value).toBe(boom)
  })

  it('flush 取消等待中的 debounce、立即送出並等落地', async () => {
    const saveFn = vi.fn().mockResolvedValue(true)
    const as = useAutosave({ saveFn, debounceMs: 10000, sleep: noSleep })

    as.schedule(() => 'final')
    expect(saveFn).not.toHaveBeenCalled()   // debounce 還沒到

    const ok = await as.flush()
    expect(saveFn).toHaveBeenCalledTimes(1)
    expect(saveFn).toHaveBeenCalledWith('final')
    expect(ok).toBe(true)
    expect(as.isDirty.value).toBe(false)
  })

  it('沒有待存內容時 flush 直接回 true（idempotent）', async () => {
    const saveFn = vi.fn().mockResolvedValue(true)
    const as = useAutosave({ saveFn, debounceMs: 1, sleep: noSleep })

    const ok = await as.flush()
    expect(ok).toBe(true)
    expect(saveFn).not.toHaveBeenCalled()
  })

  it('cancel 丟棄待存的 debounce，不送出', async () => {
    const saveFn = vi.fn().mockResolvedValue(true)
    const as = useAutosave({ saveFn, debounceMs: 1, sleep: noSleep })

    as.schedule(() => 'discard')
    as.cancel()
    await tick()

    expect(saveFn).not.toHaveBeenCalled()
  })
})
