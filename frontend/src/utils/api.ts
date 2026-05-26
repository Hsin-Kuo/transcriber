/**
 * API 客戶端 - 支援 Token 自動刷新
 */
/// <reference types="vite/client" />
import axios, { AxiosError } from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

// 未設定 VITE_API_URL 時，自動沿用當前 hostname + port 8000
function resolveApiBase(): string {
  const envUrl = import.meta.env.VITE_API_URL as string | undefined
  if (envUrl) return envUrl
  if (typeof window === 'undefined') return ''
  const { protocol, hostname } = window.location
  return `${protocol}//${hostname}:8000`
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
interface RetryableRequest extends InternalAxiosRequestConfig {
  _retry?: boolean
}

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableRequest | undefined

    // 如果是 401 錯誤且不是刷新 Token 請求
    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
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
    if (error.response?.status === 429) {
      if (!rateLimitNotifyTimer) {
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

    // 網路錯誤（無 response = 斷線 / timeout；排除用戶主動取消）
    if (!error.response && error.code !== 'ERR_CANCELED') {
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
