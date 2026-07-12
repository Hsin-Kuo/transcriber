/**
 * 認證狀態管理 Store
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api, { setAccessTokenExpiry } from '../utils/api'
import i18n from '../i18n'
import { errorI18n } from '../utils/apiError'

/**
 * 把後端錯誤解析成「可顯示字串」：
 *   1. 有對應 i18n key（coded 錯誤如 AUTH_INVALID_CREDENTIALS）→ 翻譯
 *   2. 否則用後端回傳的 message（舊式字串 detail / 尚未對映的 code）
 *   3. 再否則用呼叫端的 fallback key
 *
 * 為什麼需要這層：後端 detail 現在是 `{ code, message }` 物件，直接
 * `err.response?.data?.detail || ...` 會把整個物件塞進 error.value，
 * 模板 `{{ error }}` 便 JSON.stringify 把 `{"code":...,"message":...}` 印給使用者。
 */
function resolveAuthError(err, fallbackKey) {
  const { key, params, fallback } = errorI18n(err)
  if (key) return i18n.global.t(key, params)
  return fallback || i18n.global.t(fallbackKey)
}

export const useAuthStore = defineStore('auth', () => {
  // State
  const user = ref(null)
  const loading = ref(false)
  const error = ref(null)
  // 這個 session 是否已經嘗試過 initialize()——access_token 是 httpOnly
  // cookie，JS 讀不到「可能有登入過」這個線索了，用這個旗標避免 router
  // guard 在每次導覽都重打一次 /auth/me（只在真正沒 user 時試「一次」）。
  const initialized = ref(false)

  // Getters
  const isAuthenticated = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const quota = computed(() => user.value?.quota || {})
  // 手動保留音檔額度（方案決定）；缺欄位時退回 0，與後端 tier_config.get("max_keep_audio", 0) 一致
  const maxKeepAudio = computed(() => quota.value.max_keep_audio ?? 0)
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
      error.value = resolveAuthError(err, 'auth.registerFailed')
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
      // access_token / refresh_token 都由後端寫進 httpOnly cookie，前端不再保管
      const response = await api.post('/auth/login', { email, password })
      setAccessTokenExpiry(response.data.expires_at)
      await fetchCurrentUser()

      return { success: true }
    } catch (err) {
      error.value = resolveAuthError(err, 'auth.wrongCredentials')
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
      // 後端會清 access_token/refresh_token 兩個 cookie；瀏覽器自動帶 cookie 出去
      await api.post('/auth/logout')
    } catch (err) {
      console.error('登出錯誤:', err)
    } finally {
      setAccessTokenExpiry(null)
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

  // 初始化：沒有 localStorage 可以偷看「是否曾登入」了（access_token 是
  // httpOnly cookie），直接嘗試打 /auth/me；沒有有效 session 就讓它自然
  // 401，user 維持 null，router guard 導去登入頁。只做一次（initialized
  // 旗標），不然每次導覽都會重打。
  async function initialize() {
    if (initialized.value) return
    initialized.value = true
    await fetchCurrentUser()
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
      error.value = resolveAuthError(err, 'auth.sendResetEmailFailed')
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
      error.value = resolveAuthError(err, 'auth.resetPasswordFailed')
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
      setAccessTokenExpiry(response.data.expires_at)
      await fetchCurrentUser()

      return { success: true }
    } catch (err) {
      error.value = resolveAuthError(err, 'auth.googleLoginError')
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
      error.value = resolveAuthError(err, 'auth.googleBindError')
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
      error.value = resolveAuthError(err, 'auth.googleUnbindError')
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
        error: resolveAuthError(err, 'auth.updatePreferencesFailed')
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

  // 加購套餐目錄近乎靜態，session 內快取，避免 PlanPanel 重開 / CheckoutView 重複抓
  let packagesPromise = null
  async function getPackages() {
    if (!packagesPromise) {
      packagesPromise = api.get('/subscriptions/packages')
        .then(r => r.data.packages)
        .catch(err => { packagesPromise = null; throw err })  // 失敗不快取，允許重試
    }
    return packagesPromise
  }

  // 方案定義（額度 + features）的唯一真實來源在後端 QUOTA_TIERS，session 內快取
  let tiersPromise = null
  async function getTiers() {
    if (!tiersPromise) {
      tiersPromise = api.get('/subscriptions/tiers')
        .then(r => r.data.tiers)
        .catch(err => { tiersPromise = null; throw err })  // 失敗不快取，允許重試
    }
    return tiersPromise
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
      setAccessTokenExpiry(null)
      user.value = null
      return { success: true }
    } catch (err) {
      error.value = resolveAuthError(err, 'auth.deleteAccountFailed')
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
      error.value = resolveAuthError(err, 'auth.setPasswordFailed')
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
    initialized,
    // Getters
    isAuthenticated,
    isAdmin,
    quota,
    maxKeepAudio,
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
    getTiers,
    getOrders,
    submitNewebpayForm,
  }
})
