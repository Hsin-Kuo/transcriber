/**
 * API 客戶端 - 支援 Token 自動刷新
 */
/// <reference types="vite/client" />
import axios, { AxiosError } from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { quotaErrorFromResponse } from './quotaError'

// 未設定 VITE_API_URL 時：開發環境（含 vitest）走 hostname:8000，
// 生產 build same-origin 由 nginx 反代。
// 用 import.meta.env.DEV 而非 port heuristic，避免 test/preview 環境誤判。
function resolveApiBase(): string {
  const envUrl = import.meta.env.VITE_API_URL as string | undefined
  if (envUrl) return envUrl
  if (typeof window === 'undefined') return ''
  if (import.meta.env.DEV) {
    const { protocol, hostname } = window.location
    return `${protocol}//${hostname}:8000`
  }
  return ''
}

const API_BASE = resolveApiBase()

// 創建 axios 實例
// withCredentials: 讓瀏覽器自動帶 httpOnly access_token/refresh_token cookie
// 給對應端點——兩個 token 都不再由 JS 保管（原本 access_token 存
// localStorage 的 TokenManager 已移除，這是 XSS audit TODO-8 方案 B 的
// 核心修正）。
const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 300000,  // 5 分鐘
  withCredentials: true,
})

// access token 的絕對過期時間（UTC epoch 毫秒），供 ensureFreshAccessToken
// 判斷是否該提前 refresh。取代原本解析 JWT payload 的 exp claim 的做法——
// httpOnly cookie 下 JS 讀不到 token 內容，這個值由後端在 login/refresh
// 回應內容直接給，不是機密。只是這支模組內部排程用的狀態，不放進 Pinia
// store（沒有任何 UI 需要它）。
let accessTokenExpiresAtMs: number | null = null

export function setAccessTokenExpiry(expiresAtMs: number | null | undefined): void {
  accessTokenExpiresAtMs = expiresAtMs ?? null
}

// 響應攔截器: 處理 Token 過期與 Rate Limit
type RefreshSubscriber = {
  resolve: () => void
  reject: (err: unknown) => void
}

let isRefreshing = false
let refreshSubscribers: RefreshSubscriber[] = []
let rateLimitNotifyTimer: ReturnType<typeof setTimeout> | null = null
let serverErrorNotifyTimer: ReturnType<typeof setTimeout> | null = null
let networkErrorNotifyTimer: ReturnType<typeof setTimeout> | null = null

function subscribeTokenRefresh(
  resolve: () => void,
  reject: (err: unknown) => void,
): void {
  refreshSubscribers.push({ resolve, reject })
}

function onRefreshed(): void {
  refreshSubscribers.forEach(({ resolve }) => resolve())
  refreshSubscribers = []
}

function onRefreshFailed(error: unknown): void {
  refreshSubscribers.forEach(({ reject }) => reject(error))
  refreshSubscribers = []
}

// 強制跳轉到登入頁，避開 SPA router 在 in-flight navigation 中失效的問題。
// 用 location.replace 不留 history，避免按上一頁回到失效頁面。
let redirectingToLogin = false
function redirectToLogin(reason: string): void {
  if (redirectingToLogin) return
  if (window.location.pathname === '/login') return
  redirectingToLogin = true
  console.info(`[auth] redirecting to /login: ${reason}`)
  const redirect = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.replace(`/login?redirect=${redirect}`)
}

// 擴充 axios config 加 _retry 標記（避免無限 refresh 迴圈）
// 與 _silentRateLimit 讓 polling 類請求不觸發全域 toast
interface RetryableRequest extends InternalAxiosRequestConfig {
  _retry?: boolean
  _silentRateLimit?: boolean
}

// 這些端點的 401 不是 access token 過期 — 它們本來就不需要 token
// （登入/註冊/Google OAuth/refresh 自身）。若不排除，登入失敗會誤觸 refresh，
// 把「帳密錯誤」覆寫成「缺少 refresh token cookie」之類的錯訊。
const AUTH_ENDPOINTS_NO_REFRESH = [
  '/auth/login',
  '/auth/register',
  '/auth/refresh',
  '/auth/google',
  '/auth/forgot-password',
  '/auth/reset-password',
  // 未認證的 polling / 自助流程 — 拿到 401 應顯示對應錯誤而非觸發 refresh
  '/auth/registration-status',
  '/auth/abandon-registration',
]

function shouldSkipRefresh(url: string | undefined): boolean {
  if (!url) return false
  return AUTH_ENDPOINTS_NO_REFRESH.some((path) => url.includes(path))
}

// 共用的 token 刷新：並行呼叫會合流到同一次 /auth/refresh（沿用 isRefreshing 鎖 +
// subscriber 隊列）。被動 401 攔截器與主動刷新都走這支，確保只有單一刷新實作。
// 新的 access_token 由後端種進 httpOnly cookie，這裡不需要（也讀不到）拿到
// token 字串本身，只需要知道成功與否、順便更新 accessTokenExpiresAtMs。
function refreshAccessToken(): Promise<void> {
  if (isRefreshing) {
    return new Promise<void>((resolve, reject) => {
      subscribeTokenRefresh(resolve, reject)
    })
  }
  isRefreshing = true
  return axios
    .post<{ expires_at?: number }>(`${API_BASE}/auth/refresh`, null, { withCredentials: true })
    .then(({ data }) => {
      setAccessTokenExpiry(data.expires_at)
      onRefreshed()
      isRefreshing = false
    })
    .catch((refreshError) => {
      isRefreshing = false
      onRefreshFailed(refreshError)
      // 只有 refresh 端點明確拒絕（401/403）才代表 token 真的失效；
      // 網路錯誤 / 後端暫時 5xx 不清狀態，避免短暫故障造成登出
      const status = (refreshError as AxiosError)?.response?.status
      if (status === 401 || status === 403) {
        setAccessTokenExpiry(null)
        redirectToLogin('refresh token rejected by backend')
      }
      throw refreshError
    })
}

// 主動刷新：access token 剩餘效期 < minRemainingSeconds 就先刷新。
// 供長時間操作（大檔分片上傳）每片送出前呼叫，讓 chunk 不會撞 token 過期 401、
// 避免整片重傳浪費頻寬。失敗不拋，後續請求自然 fallback 到被動 401 攔截器。
//
// accessTokenExpiresAtMs 為 null 時（例如頁面重整後、還沒真的打過一次
// login/refresh）無法判斷剩餘時間——寧可多刷新一次（成本低）也不要漏掉
// 真正快過期的情況（漏掉的代價是分片上傳中途 401），所以未知一律視為
// 「該刷新」。
export async function ensureFreshAccessToken(minRemainingSeconds = 120): Promise<void> {
  if (accessTokenExpiresAtMs !== null && accessTokenExpiresAtMs - Date.now() > minRemainingSeconds * 1000) {
    return
  }
  try {
    await refreshAccessToken()
  } catch {
    /* 主動刷新失敗：交給被動攔截器 */
  }
}

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableRequest | undefined

    // 如果是 401 錯誤且不是刷新 Token 請求，且不是「本來就不該帶 token」的 auth 端點
    if (
      error.response?.status === 401
      && originalRequest
      && !originalRequest._retry
      && !shouldSkipRefresh(originalRequest.url)
    ) {
      originalRequest._retry = true
      try {
        // refreshAccessToken 內部處理「已在刷新中就掛隊列」的合流；新
        // access_token 已由後端種進 httpOnly cookie，重試請求會自動帶上，
        // 不需要手動加 header
        await refreshAccessToken()
        return api(originalRequest)
      } catch (refreshError) {
        return Promise.reject(refreshError)
      }
    }

    // 429 Rate Limit：debounce 避免同時多個請求失敗時重複通知
    // _silentRateLimit 旗標讓背景 polling 類請求（verify-pending 等）不觸發全域 toast
    if (error.response?.status === 429) {
      // 額度不足（QUOTA_EXCEEDED）雖也是 429，但由頁面層的額度對話框處理，
      // 不觸發全域「請求太頻繁」toast，避免訊息互相干擾。
      const isQuota = !!quotaErrorFromResponse(error)
      if (!isQuota && !originalRequest?._silentRateLimit && !rateLimitNotifyTimer) {
        window.dispatchEvent(new CustomEvent('api:rate-limited'))
        rateLimitNotifyTimer = setTimeout(() => { rateLimitNotifyTimer = null }, 3000)
      }
      return Promise.reject(error)
    }

    // 5xx 伺服器錯誤
    if (error.response && error.response.status >= 500) {
      if (!serverErrorNotifyTimer) {
        window.dispatchEvent(new CustomEvent('api:server-error'))
        serverErrorNotifyTimer = setTimeout(() => { serverErrorNotifyTimer = null }, 5000)
      }
      return Promise.reject(error)
    }

    // 網路錯誤（無 response = 斷線 / timeout）。排除這些 expected case：
    // - ERR_CANCELED: 用戶 / 程式主動 cancel
    // - ECONNABORTED: axios timeout（大檔上傳碰到 5 分鐘上限會觸發，
    //                  非真斷網，跳「網路錯誤」會誤導使用者）
    const benignCodes = new Set(['ERR_CANCELED', 'ECONNABORTED'])
    if (!error.response && !benignCodes.has(error.code ?? '')) {
      if (!networkErrorNotifyTimer) {
        window.dispatchEvent(new CustomEvent('api:network-error'))
        networkErrorNotifyTimer = setTimeout(() => { networkErrorNotifyTimer = null }, 5000)
      }
      return Promise.reject(error)
    }

    return Promise.reject(error)
  },
)

export { API_BASE }
export default api
