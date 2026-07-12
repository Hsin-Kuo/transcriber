/**
 * API 客戶端 - access token 走 httpOnly cookie，瀏覽器自動夾帶
 *
 * access token 不再由 JS 保管（原本存 localStorage 的 TokenManager 已移除，
 * 這是 XSS audit TODO-8 方案 B 的核心修正）。401 時呼叫 /auth/refresh 讓
 * 後端種一顆新 cookie，重試原請求即可，不需要手動組 Authorization header。
 */
/// <reference types="vite/client" />
import axios, { AxiosError } from 'axios'
import type { AxiosInstance, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import router from '../router'

// 生產環境由 Nginx 代理，開發環境由 Vite proxy 處理
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) || ''

// 創建 axios 實例
const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 300000,  // 5 分鐘
  withCredentials: true,
})

type RefreshResult = { success: true } | { success: false; error: unknown }
type RefreshSubscriber = (result: RefreshResult) => void

let isRefreshing = false
let refreshSubscribers: RefreshSubscriber[] = []

function subscribeTokenRefresh(callback: RefreshSubscriber): void {
  refreshSubscribers.push(callback)
}

function onRefreshed(): void {
  refreshSubscribers.forEach((cb) => cb({ success: true }))
  refreshSubscribers = []
}

function onRefreshFailed(error: unknown): void {
  refreshSubscribers.forEach((cb) => cb({ success: false, error }))
  refreshSubscribers = []
}

interface RetryableRequest extends InternalAxiosRequestConfig {
  _retry?: boolean
}

// 這些端點的 401 不是 access token 過期——它們本來就不需要 token
// （登入/註冊/refresh 自身）。若不排除，登入密碼打錯會誤觸 refresh
// （沒有 refresh_token cookie，refresh 也 401），把「帳號或密碼錯誤」
// 覆寫成 refresh 失敗的錯訊，見 frontend/src/utils/api.ts 同款既有修法
// （commit a51bd1e）——那次只修了 frontend/，這裡補齊 admin-frontend。
const AUTH_ENDPOINTS_NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh']

function shouldSkipRefresh(url: string | undefined): boolean {
  if (!url) return false
  return AUTH_ENDPOINTS_NO_REFRESH.some((path) => url.includes(path))
}

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableRequest | undefined

    if (
      error.response?.status === 401
      && originalRequest
      && !originalRequest._retry
      && !shouldSkipRefresh(originalRequest.url)
    ) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh((result) => {
            if (result.success === true) {
              resolve(api(originalRequest))
            } else {
              reject(result.error)
            }
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        // 後端會在這次回應種一顆新的 access_token cookie；不需要讀 body
        await axios.post(`${API_BASE}/auth/refresh`, null, { withCredentials: true })

        onRefreshed()
        isRefreshing = false

        return api(originalRequest)
      } catch (refreshError) {
        onRefreshFailed(refreshError)
        isRefreshing = false

        router.push('/login')
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  },
)

export { API_BASE }
export default api
