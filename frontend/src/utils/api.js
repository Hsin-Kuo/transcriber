/**
 * API 客戶端 - 支援 Token 自動刷新
 */
import axios from 'axios'

// 未設定 VITE_API_URL 時，自動沿用當前 hostname + port 8000
// 支援 localhost、Tailscale IP、任意裝置直接存取
function resolveApiBase() {
  const envUrl = import.meta.env.VITE_API_URL
  if (envUrl) return envUrl
  if (typeof window === 'undefined') return ''
  const { protocol, hostname } = window.location
  return `${protocol}//${hostname}:8000`
}

const API_BASE = resolveApiBase()

// 創建 axios 實例
// withCredentials: 讓瀏覽器自動帶 httpOnly refresh_token cookie 給 /auth/* 端點
const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,  // 5 分鐘（一般 API 請求）
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

// 響應攔截器: 處理 Token 過期與 Rate Limit
let isRefreshing = false
let refreshSubscribers = []
let rateLimitNotifyTimer = null

function subscribeTokenRefresh(resolve, reject) {
  refreshSubscribers.push({ resolve, reject })
}

function onRefreshed(token) {
  refreshSubscribers.forEach(({ resolve }) => resolve(token))
  refreshSubscribers = []
}

function onRefreshFailed(error) {
  refreshSubscribers.forEach(({ reject }) => reject(error))
  refreshSubscribers = []
}

// 強制跳轉到登入頁，避開 SPA router 在 in-flight navigation 中失效的問題。
// 用 location.replace 不留 history，避免按上一頁回到失效頁面。
let redirectingToLogin = false
function redirectToLogin(reason) {
  if (redirectingToLogin) return
  if (window.location.pathname === '/login') return
  redirectingToLogin = true
  console.info(`[auth] redirecting to /login: ${reason}`)
  const redirect = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.replace(`/login?redirect=${redirect}`)
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // 如果是 401 錯誤且不是刷新 Token 請求
    if (error.response?.status === 401 && !originalRequest?._retry) {
      if (isRefreshing) {
        // 如果正在刷新,將請求加入隊列
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh(
            (token) => {
              originalRequest.headers.Authorization = `Bearer ${token}`
              resolve(api(originalRequest))
            },
            (err) => reject(err)
          )
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
        if (refreshError.response?.status === 401 || refreshError.response?.status === 403) {
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

    return Promise.reject(error)
  }
)

export { API_BASE }
export default api
