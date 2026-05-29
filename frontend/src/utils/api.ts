/**
 * API 客戶端 - 支援 Token 自動刷新
 */
/// <reference types="vite/client" />
import axios, { AxiosError } from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

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
// withCredentials: 讓瀏覽器自動帶 httpOnly refresh_token cookie 給 /auth/* 端點
const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 300000,  // 5 分鐘
  withCredentials: true,
})

// Token 管理：refresh_token 改由 httpOnly cookie 持有，JS 不再保存
export const TokenManager = {
  getAccessToken: (): string | null => localStorage.getItem('access_token'),
  setAccessToken: (accessToken: string): void => {
    localStorage.setItem('access_token', accessToken)
  },
  clearTokens: (): void => {
    localStorage.removeItem('access_token')
    // 舊版殘留：把以前存的 refresh_token 也清掉一次
    localStorage.removeItem('refresh_token')
  },
}

// 請求攔截器: 添加 Authorization header
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = TokenManager.getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error: unknown) => Promise.reject(error),
)

// 響應攔截器: 處理 Token 過期與 Rate Limit
type RefreshSubscriber = {
  resolve: (token: string) => void
  reject: (err: unknown) => void
}

let isRefreshing = false
let refreshSubscribers: RefreshSubscriber[] = []
let rateLimitNotifyTimer: ReturnType<typeof setTimeout> | null = null
let serverErrorNotifyTimer: ReturnType<typeof setTimeout> | null = null
let networkErrorNotifyTimer: ReturnType<typeof setTimeout> | null = null

function subscribeTokenRefresh(
  resolve: (token: string) => void,
  reject: (err: unknown) => void,
): void {
  refreshSubscribers.push({ resolve, reject })
}

function onRefreshed(token: string): void {
  refreshSubscribers.forEach(({ resolve }) => resolve(token))
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
      if (isRefreshing) {
        // 如果正在刷新，將請求加入隊列
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh(
            (token: string) => {
              originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(api(originalRequest))
            },
            (err: unknown) => reject(err),
          )
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        // 刷新 Token：refresh_token 由瀏覽器以 httpOnly cookie 自動帶出
        const response = await axios.post<{ access_token: string }>(
          `${API_BASE}/auth/refresh`,
          null,
          { withCredentials: true },
        )

        const { access_token } = response.data
        TokenManager.setAccessToken(access_token)

        // 更新原請求的 header
        originalRequest.headers.Authorization = `Bearer ${access_token}`

        // 通知所有等待的請求
        onRefreshed(access_token)
        isRefreshing = false

        // 重試原請求
        return api(originalRequest)
      } catch (refreshError) {
        isRefreshing = false
        onRefreshFailed(refreshError)
        // 只有 refresh 端點明確拒絕（401/403）才代表 token 真的失效
        // 網路錯誤或後端暫時不可用（5xx）不清 token，避免短暫故障造成登出
        const status = (refreshError as AxiosError)?.response?.status
        if (status === 401 || status === 403) {
          TokenManager.clearTokens()
          redirectToLogin('refresh token rejected by backend')
        }
        return Promise.reject(refreshError)
      }
    }

    // 429 Rate Limit：debounce 避免同時多個請求失敗時重複通知
    // _silentRateLimit 旗標讓背景 polling 類請求（verify-pending 等）不觸發全域 toast
    if (error.response?.status === 429) {
      if (!originalRequest?._silentRateLimit && !rateLimitNotifyTimer) {
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
