/**
 * 認證狀態管理 Store
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import api from '../utils/api'

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
      // 註冊 API 已不發 token；保留呼叫保留註冊流程
      return { success: true, message: response.data?.message }
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
      // access_token / refresh_token 都由後端寫進 httpOnly cookie，前端不再保管
      await api.post('/auth/login', { email, password })
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
      // 後端會清 access_token/refresh_token 兩個 cookie；瀏覽器自動帶 cookie 出去
      await api.post('/auth/logout')
    } catch (err) {
      console.error('登出錯誤:', err)
    } finally {
      user.value = null
    }
  }

  async function fetchCurrentUser() {
    try {
      const response = await api.get('/auth/me')
      user.value = response.data
    } catch (err) {
      console.error('獲取用戶資訊失敗:', err)
      user.value = null
    }
  }

  // 初始化：沒有 localStorage 可以偷看「是否曾登入」了（access_token 是
  // httpOnly cookie），直接嘗試打 /auth/me；沒有有效 session 就讓它自然
  // 401，authStore.user 維持 null，router guard 導去登入頁。
  //
  // 用「記住進行中的 promise」而非布林旗標去重——布林旗標在 fetchCurrentUser()
  // resolve 前就先設成 true，若兩個導覽的 router guard 幾乎同時觸發
  // （Vue Router 的 beforeEach 不會把後一個導覽的 guard 排隊等前一個結束），
  // 第二個 guard 會看到旗標已經是 true 就直接放行，但這時 user 還是 null，
  // 導致已登入的使用者被誤導向 /login。記住 promise 才能讓並發呼叫真的等
  // 同一次請求 resolve；呼叫結束後清掉 promise，暫時性網路失敗才不會讓後面
  // 所有導覽永遠不重試。
  let initializePromise = null
  async function initialize() {
    if (!initializePromise) {
      initializePromise = fetchCurrentUser().finally(() => {
        initializePromise = null
      })
    }
    await initializePromise
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
