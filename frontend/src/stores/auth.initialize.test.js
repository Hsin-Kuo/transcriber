import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * initialize() 的 race + 永久卡死回歸測試（code review 抓到的兩個問題）。
 *
 * access_token 是 httpOnly cookie，JS 讀不到「可能登入過」這個線索，
 * initialize() 只能靠實際打一次 /auth/me 才知道。用「記住進行中的 promise」
 * 去重（而非布林旗標)，理由：
 * 1. 兩個導覽的 router guard 幾乎同時觸發時，必須真的等同一次 fetch，
 *    不能讓後到的呼叫在 user 還沒準備好時就搶先放行。
 * 2. 第一次呼叫失敗（暫時性網路問題）不該讓之後所有導覽永遠不重試。
 */

vi.mock('../i18n', () => ({
  default: { global: { t: (k) => k, locale: { value: 'zh-TW' } } },
}))

vi.mock('../utils/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  setAccessTokenExpiry: vi.fn(),
}))

import api from '../utils/api'
import { useAuthStore } from './auth.js'

describe('authStore.initialize()', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('concurrent calls dedupe to a single /auth/me request', async () => {
    let resolveFetch
    api.get.mockReturnValueOnce(
      new Promise((resolve) => { resolveFetch = resolve })
    )

    const store = useAuthStore()

    const first = store.initialize()
    const second = store.initialize() // fired before the first resolves

    expect(api.get).toHaveBeenCalledTimes(1) // deduped, not two independent fetches

    resolveFetch({ data: { email: 'a@b.com', role: 'user' } })
    await Promise.all([first, second])

    expect(store.user).toEqual({ email: 'a@b.com', role: 'user' })
  })

  it('retries on the next call after a failed attempt (not permanently stuck)', async () => {
    api.get.mockRejectedValueOnce(new Error('network blip'))
    const store = useAuthStore()

    await store.initialize()
    expect(store.user).toBeNull()

    api.get.mockResolvedValueOnce({ data: { email: 'a@b.com', role: 'user' } })
    await store.initialize() // must actually retry, not silently no-op

    expect(api.get).toHaveBeenCalledTimes(2)
    expect(store.user).toEqual({ email: 'a@b.com', role: 'user' })
  })
})
