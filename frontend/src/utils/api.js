/**
 * API 客戶端 - 支援 Token 自動刷新
 */
import axios from 'axios'
import router from '../router'

const API_BASE = import.meta.env.VITE_API_URL || 'http://192.168.0.59:8000'

// 創建 axios 實例
const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,  // 5 分鐘 (考慮轉錄時間長)
})

// Token 管理
export const TokenManager = {
  getAccessToken: () => localStorage.getItem('access_token'),
  getRefreshToken: () => localStorage.getItem('refresh_token'),
  setTokens: (accessToken, refreshToken) => {
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('refresh_token', refreshToken)
  },
  clearTokens: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }
}

// 請求攔截器: 添加 Authorization header
api.interceptors.request.use(
  (config) => {
    const token = TokenManager.getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 響應攔截器: 處理 Token 過期
let isRefreshing = false
let refreshSubscribers = []

function subscribeTokenRefresh(callback) {
  refreshSubscribers.push(callback)
}

function onRefreshed(token) {
  refreshSubscribers.forEach(callback => callback(token))
  refreshSubscribers = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // 如果是 401 錯誤且不是刷新 Token 請求
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // 如果正在刷新,將請求加入隊列
        return new Promise((resolve) => {
          subscribeTokenRefresh((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(api(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const refreshToken = TokenManager.getRefreshToken()
        if (!refreshToken) {
          throw new Error('No refresh token')
        }

        // 刷新 Token
        const response = await axios.post(`${API_BASE}/auth/refresh`, {
          refresh_token: refreshToken
        })

        const { access_token, refresh_token } = response.data
        TokenManager.setTokens(access_token, refresh_token)

        // 更新原請求的 header
        originalRequest.headers.Authorization = `Bearer ${access_token}`

        // 通知所有等待的請求
        onRefreshed(access_token)
        isRefreshing = false

        // 重試原請求
        return api(originalRequest)
      } catch (refreshError) {
        // 刷新失敗,清除 Token 並跳轉登入頁
        isRefreshing = false
        TokenManager.clearTokens()
        router.push('/login')
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

export { API_BASE }
export default api
