/**
 * API 客戶端 - 支援 Token 自動刷新
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

export const TokenManager = {
  getAccessToken: (): string | null => localStorage.getItem('access_token'),
  setAccessToken: (accessToken: string): void => {
    localStorage.setItem('access_token', accessToken)
  },
  clearTokens: (): void => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  },
}

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

type RefreshResult = { success: true; token: string } | { success: false; error: unknown }
type RefreshSubscriber = (result: RefreshResult) => void

let isRefreshing = false
let refreshSubscribers: RefreshSubscriber[] = []

function subscribeTokenRefresh(callback: RefreshSubscriber): void {
  refreshSubscribers.push(callback)
}

function onRefreshed(token: string): void {
  refreshSubscribers.forEach((cb) => cb({ success: true, token }))
  refreshSubscribers = []
}

function onRefreshFailed(error: unknown): void {
  refreshSubscribers.forEach((cb) => cb({ success: false, error }))
  refreshSubscribers = []
}

interface RetryableRequest extends InternalAxiosRequestConfig {
  _retry?: boolean
}

api.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryableRequest | undefined

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh((result) => {
            if ('token' in result) {
              originalRequest.headers.Authorization = `Bearer ${result.token}`
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
        const response = await axios.post<{ access_token: string }>(
          `${API_BASE}/auth/refresh`,
          null,
          { withCredentials: true },
        )

        const { access_token } = response.data
        TokenManager.setAccessToken(access_token)

        originalRequest.headers.Authorization = `Bearer ${access_token}`
        onRefreshed(access_token)
        isRefreshing = false

        return api(originalRequest)
      } catch (refreshError) {
        onRefreshFailed(refreshError)
        isRefreshing = false

        TokenManager.clearTokens()
        router.push('/login')
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  },
)

export { API_BASE }
export default api
