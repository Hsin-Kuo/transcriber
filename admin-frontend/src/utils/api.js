/**
 * API 客戶端 - 支援 Token 自動刷新
 */
import axios from 'axios'
import router from '../router'

// 生產環境由 Nginx 代理，開發環境由 Vite proxy 處理
const API_BASE = import.meta.env.VITE_API_URL || ''

// 創建 axios 實例
// withCredentials: 讓瀏覽器自動帶 httpOnly refresh_token cookie 給 /auth/* 端點
const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,  // 5 分鐘 (考慮轉錄時間長)
  withCredentials: true,
})

// Token 管理：refresh_token 改由 httpOnly cookie 持有，JS 不再保存
export const TokenManager = {
  getAccessToken: () => localStorage.getItem('access_token'),
  setAccessToken: (accessToken) => {
    localStorage.setItem('access_token', accessToken)
  },
  clearTokens: () => {
    localStorage.removeItem('access_token')
    // 舊版殘留：把以前存的 refresh_token 也清掉一次
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
  refreshSubscribers.forEach(callback => callback({ success: true, token }))
  refreshSubscribers = []
}

function onRefreshFailed(error) {
  refreshSubscribers.forEach(callback => callback({ success: false, error }))
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
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh((result) => {
            if (result.success) {
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
        // 刷新 Token：refresh_token 由瀏覽器以 httpOnly cookie 自動帶出
        const response = await axios.post(`${API_BASE}/auth/refresh`, null, {
          withCredentials: true,
        })

        const { access_token } = response.data
        TokenManager.setAccessToken(access_token)

        // 更新原請求的 header
        originalRequest.headers.Authorization = `Bearer ${access_token}`

        // 通知所有等待的請求成功
        onRefreshed(access_token)
        isRefreshing = false

        // 重試原請求
        return api(originalRequest)
      } catch (refreshError) {
        // 刷新失敗,通知所有等待的請求
        onRefreshFailed(refreshError)
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
