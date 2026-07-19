import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * logout() 的 session teardown 回歸測試。
 *
 * Bug：帳號 A 上傳任務後登出、改登入 B，A 的「轉錄完成」toast 仍跳出。
 * 根因是登出沒有拆除跨 session 的殘留狀態（TasksView 的 SSE 串流、App 層的
 * toast 佇列與上傳浮層），而 SSE 認證在連線建立當下凍結身分，既有串流會持續
 * 吐 A 的完成事件。修法是 logout() 同步廣播 'auth:logout'，各處監聽自行拆除。
 *
 * 這裡鎖住「logout 一定會 dispatch auth:logout」這個契約——各監聽端的拆除
 * 行為在各自元件測試，但這個訊號一旦漏發，整條拆除鏈就全斷。
 */

vi.mock('../i18n', () => ({
  default: { global: { t: (k) => k, locale: { value: 'zh-TW' } } },
}))

vi.mock('../utils/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  setAccessTokenExpiry: vi.fn(),
}))

import api from '../utils/api'
import { setAccessTokenExpiry } from '../utils/api'
import { useAuthStore } from './auth.js'

describe('authStore.logout()', () => {
  // 測試在 node 環境跑（無 jsdom）；stub 一個最小 window（EventTarget）讓
  // 生產碼的 window.dispatchEvent / addEventListener 可運作。Node 18+ 全域
  // 已有 EventTarget / CustomEvent。
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.stubGlobal('window', new EventTarget())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('dispatches auth:logout so listeners can tear down session state', async () => {
    api.post.mockResolvedValueOnce({})
    const onLogout = vi.fn()
    window.addEventListener('auth:logout', onLogout)

    const store = useAuthStore()
    store.user = { email: 'a@b.com', role: 'user' }
    await store.logout()

    expect(onLogout).toHaveBeenCalledTimes(1)
    expect(store.user).toBeNull()
    expect(setAccessTokenExpiry).toHaveBeenCalledWith(null)

    window.removeEventListener('auth:logout', onLogout)
  })

  it('still dispatches auth:logout even if the backend logout call fails', async () => {
    // 後端登出失敗不能讓前端狀態卡在「還登入著」——teardown 訊號仍必須發出，
    // 否則 SSE/toast 殘留會延續到下一位使用者。
    api.post.mockRejectedValueOnce(new Error('network blip'))
    const onLogout = vi.fn()
    window.addEventListener('auth:logout', onLogout)

    const store = useAuthStore()
    store.user = { email: 'a@b.com', role: 'user' }
    await store.logout()

    expect(onLogout).toHaveBeenCalledTimes(1)
    expect(store.user).toBeNull()

    window.removeEventListener('auth:logout', onLogout)
  })
})
