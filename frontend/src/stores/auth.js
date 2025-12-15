/**
 * 認證狀態管理 Store
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api, { TokenManager } from '../utils/api'

export const useAuthStore = defineStore('auth', () => {
  // State
  const user = ref(null)
  const loading = ref(false)
  const error = ref(null)

  // Getters
  const isAuthenticated = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const quota = computed(() => user.value?.quota || {})
  const usage = computed(() => user.value?.usage || {})

  // 計算配額使用百分比
  const quotaPercentage = computed(() => {
    if (!user.value) return { transcriptions: 0, duration: 0 }

    const transcriptionsUsed = usage.value.transcriptions || 0
    const transcriptionsLimit = quota.value.max_transcriptions || 1
    const durationUsed = usage.value.duration_minutes || 0
    const durationLimit = quota.value.max_duration_minutes || 1

    return {
      transcriptions: Math.min((transcriptionsUsed / transcriptionsLimit) * 100, 100),
      duration: Math.min((durationUsed / durationLimit) * 100, 100)
    }
  })

  // 剩餘配額
  const remainingQuota = computed(() => {
    if (!user.value) return { transcriptions: 0, duration: 0 }

    return {
      transcriptions: Math.max(0, (quota.value.max_transcriptions || 0) - (usage.value.transcriptions || 0)),
      duration: Math.max(0, (quota.value.max_duration_minutes || 0) - (usage.value.duration_minutes || 0))
    }
  })

  // Actions
  async function register(email, password) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/register', { email, password })
      const { access_token, refresh_token } = response.data

      TokenManager.setTokens(access_token, refresh_token)
      await fetchCurrentUser()

      return { success: true }
    } catch (err) {
      error.value = err.response?.data?.detail || '註冊失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function login(email, password) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/login', { email, password })
      const { access_token, refresh_token } = response.data

      TokenManager.setTokens(access_token, refresh_token)
      await fetchCurrentUser()

      return { success: true }
    } catch (err) {
      error.value = err.response?.data?.detail || '登入失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      const refreshToken = TokenManager.getRefreshToken()
      if (refreshToken) {
        await api.post('/auth/logout', { refresh_token: refreshToken })
      }
    } catch (err) {
      console.error('登出錯誤:', err)
    } finally {
      TokenManager.clearTokens()
      user.value = null
    }
  }

  async function fetchCurrentUser() {
    try {
      const response = await api.get('/auth/me')
      user.value = response.data
    } catch (err) {
      console.error('獲取用戶資訊失敗:', err)
      TokenManager.clearTokens()
      user.value = null
    }
  }

  // 初始化: 如果有 Token,嘗試獲取用戶資訊
  async function initialize() {
    if (TokenManager.getAccessToken()) {
      await fetchCurrentUser()
    }
  }

  return {
    // State
    user,
    loading,
    error,
    // Getters
    isAuthenticated,
    isAdmin,
    quota,
    usage,
    quotaPercentage,
    remainingQuota,
    // Actions
    register,
    login,
    logout,
    fetchCurrentUser,
    initialize
  }
})
