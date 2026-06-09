/**
 * 認證狀態管理 Store
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api, { TokenManager } from '../utils/api'
import i18n from '../i18n'

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
  const authProviders = computed(() => user.value?.auth_providers || [])
  const hasPassword = computed(() => authProviders.value.includes('password'))
  const hasGoogle = computed(() => authProviders.value.includes('google'))
  const preferences = computed(() => user.value?.preferences || {})
  const subscription = computed(() => user.value?.subscription || {})
  const hasActiveSubscription = computed(() =>
    subscription.value?.status === 'active'
  )

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
    if (!user.value) return { transcriptions: 0, duration: 0, aiSummaries: 0 }

    // duration / aiSummaries 須加上 extra_quota，與後端 reserve 檢查（plan + extra）一致
    return {
      transcriptions: Math.max(0, (quota.value.max_transcriptions || 0) - (usage.value.transcriptions || 0)),
      duration: Math.max(0, (quota.value.max_duration_minutes || 0) - (usage.value.duration_minutes || 0)) + (user.value?.extra_quota?.duration_minutes || 0),
      aiSummaries: Math.max(0, (quota.value.max_ai_summaries || 0) - (usage.value.ai_summaries || 0)) + (user.value?.extra_quota?.ai_summaries || 0)
    }
  })

  // Actions
  async function register(email, password) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/register', { email, password })
      // 註冊成功（包含寄信失敗的情況，user 已被保留）
      // API 返回 { message, email, email_sent }
      return {
        success: true,
        message: response.data.message,
        email: response.data.email,
        emailSent: response.data.email_sent !== false,
      }
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
      const { access_token } = response.data
      // refresh_token 由後端寫進 httpOnly cookie，前端不再保管
      TokenManager.setAccessToken(access_token)
      await fetchCurrentUser()

      return { success: true }
    } catch (err) {
      error.value = err.response?.data?.detail || '帳號或密碼錯誤'
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
      // 後端會清 cookie + 撤銷 refresh token；瀏覽器自動帶 cookie 出去
      await api.post('/auth/logout')
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
      // 從後端偏好同步到 localStorage 和 DOM（跨裝置同步）
      applyPreferences(response.data.preferences)
    } catch (err) {
      console.error('獲取用戶資訊失敗:', err)
      user.value = null
    }
  }

  function applyPreferences(prefs) {
    if (!prefs) return
    if (prefs.theme) {
      localStorage.setItem('theme', prefs.theme)
      if (prefs.theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark')
      } else {
        document.documentElement.removeAttribute('data-theme')
      }
    }
    if (prefs.language) {
      localStorage.setItem('locale', prefs.language)
      i18n.global.locale.value = prefs.language
    }
    if (prefs.timezone) {
      localStorage.setItem('timezone', prefs.timezone)
    }
    if (prefs.summaryExpandMode) {
      localStorage.setItem('summaryExpandMode', prefs.summaryExpandMode)
    }
  }

  // 初始化: 如果有 Token,嘗試獲取用戶資訊
  async function initialize() {
    if (TokenManager.getAccessToken()) {
      await fetchCurrentUser()
    }
  }

  async function forgotPassword(email) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/forgot-password', { email })
      return {
        success: true,
        message: response.data.message
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '發送重設郵件失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function resetPassword(token, newPassword) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/reset-password', {
        token,
        new_password: newPassword
      })
      return {
        success: true,
        message: response.data.message
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '重設密碼失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function googleLogin(credential) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/google', { credential })
      const { access_token } = response.data
      TokenManager.setAccessToken(access_token)
      await fetchCurrentUser()

      return { success: true }
    } catch (err) {
      error.value = err.response?.data?.detail || 'Google 登入失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function bindGoogle(credential) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/google/bind', { credential })
      await fetchCurrentUser() // 重新獲取用戶資訊以更新 auth_providers
      return {
        success: true,
        message: response.data.message
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '綁定 Google 失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function unbindGoogle() {
    loading.value = true
    error.value = null

    try {
      const response = await api.delete('/auth/google/unbind')
      await fetchCurrentUser() // 重新獲取用戶資訊以更新 auth_providers
      return {
        success: true,
        message: response.data.message
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '解除綁定失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function updatePreferences(prefs) {
    try {
      const response = await api.patch('/auth/preferences', prefs)
      if (user.value) {
        user.value = {
          ...user.value,
          preferences: response.data.preferences
        }
      }
      return { success: true }
    } catch (err) {
      return {
        success: false,
        error: err.response?.data?.detail || '更新偏好設定失敗'
      }
    }
  }

  // ===== 訂閱相關 =====

  // extra_quota（分開顯示）
  const extraQuota = computed(() => user.value?.extra_quota || { duration_minutes: 0, ai_summaries: 0 })

  async function createCheckoutSession(tier, billing, invoiceData = {}) {
    const response = await api.post('/subscriptions/checkout', { tier, billing, ...invoiceData })
    return response.data  // { form, order_no }
  }

  async function cancelSubscription() {
    const response = await api.post('/subscriptions/cancel')
    await fetchCurrentUser()
    return response.data
  }

  async function reactivateSubscription() {
    const response = await api.post('/subscriptions/reactivate')
    return response.data  // may return form if re-payment needed
  }

  async function changePlan(tier, billing, invoiceData = {}) {
    const response = await api.post('/subscriptions/change', { tier, billing, ...invoiceData })
    return response.data  // { form, order_no, action, ... }
  }

  async function purchaseExtraQuota(packageId, quantity = 1, invoiceData = {}) {
    const response = await api.post('/subscriptions/purchase-extra', { package_id: packageId, quantity, ...invoiceData })
    return response.data  // { form, order_no }
  }

  async function getPackages() {
    const response = await api.get('/subscriptions/packages')
    return response.data.packages
  }

  async function getOrders(skip = 0, limit = 6) {
    const response = await api.get('/subscriptions/orders', { params: { skip, limit } })
    return response.data  // { orders, has_more }
  }

  function submitNewebpayForm(formData) {
    const form = document.createElement('form')
    form.method = 'POST'
    form.action = formData.gateway_url
    Object.entries(formData).forEach(([key, value]) => {
      if (key === 'gateway_url') return
      const input = document.createElement('input')
      input.type = 'hidden'
      input.name = key
      input.value = value
      form.appendChild(input)
    })
    document.body.appendChild(form)
    form.submit()
  }

  async function deleteAccount(password, confirmation) {
    loading.value = true
    error.value = null

    try {
      await api.delete('/auth/account', {
        data: { password, confirmation }
      })
      TokenManager.clearTokens()
      user.value = null
      return { success: true }
    } catch (err) {
      error.value = err.response?.data?.detail || '刪除帳號失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
    }
  }

  async function setPassword(newPassword) {
    loading.value = true
    error.value = null

    try {
      const response = await api.post('/auth/set-password', {
        new_password: newPassword
      })
      await fetchCurrentUser() // 重新獲取用戶資訊以更新 auth_providers
      return {
        success: true,
        message: response.data.message
      }
    } catch (err) {
      error.value = err.response?.data?.detail || '設定密碼失敗'
      return {
        success: false,
        error: error.value
      }
    } finally {
      loading.value = false
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
    authProviders,
    hasPassword,
    hasGoogle,
    preferences,
    subscription,
    hasActiveSubscription,
    extraQuota,
    // Actions
    register,
    login,
    logout,
    fetchCurrentUser,
    initialize,
    forgotPassword,
    resetPassword,
    googleLogin,
    bindGoogle,
    unbindGoogle,
    deleteAccount,
    setPassword,
    updatePreferences,
    createCheckoutSession,
    cancelSubscription,
    reactivateSubscription,
    changePlan,
    purchaseExtraQuota,
    getPackages,
    getOrders,
    submitNewebpayForm,
  }
})
