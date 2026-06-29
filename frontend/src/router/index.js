import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { resolveLandingPath } from '../utils/loginRedirect'

const TranscriptionView = () => import('../views/TranscriptionView.vue')
const TasksView = () => import('../views/TasksView.vue')
const UserSettingsView = () => import('../views/UserSettingsView.vue')
const TranscriptDetailView = () => import('../views/TranscriptDetailView.vue')
const CheckoutView = () => import('../views/CheckoutView.vue')
const PaymentReturnView = () => import('../views/PaymentReturnView.vue')
const LoginView = () => import('../views/auth/LoginView.vue')
const RegisterView = () => import('../views/auth/RegisterView.vue')
const VerifyEmailView = () => import('../views/auth/VerifyEmailView.vue')
const VerifyPendingView = () => import('../views/auth/VerifyPendingView.vue')
const ForgotPasswordView = () => import('../views/auth/ForgotPasswordView.vue')
const ResetPasswordView = () => import('../views/auth/ResetPasswordView.vue')
const SharedTranscriptView = () => import('../views/SharedTranscriptView.vue')

const routes = [
  {
    path: '/',
    name: 'transcription',
    component: TranscriptionView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/all',
    name: 'tasks',
    component: TasksView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/settings',
    name: 'settings',
    component: UserSettingsView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/checkout',
    name: 'checkout',
    component: CheckoutView,
    meta: {
      requiresAuth: true,
      hideNav: true
    }
  },
  {
    path: '/payment/return',
    name: 'paymentReturn',
    component: PaymentReturnView,
    meta: {
      requiresAuth: true,
      hideNav: true
    }
  },
  {
    path: '/transcript/:taskId',
    name: 'transcript',
    component: TranscriptDetailView,
    meta: {
      requiresAuth: true
    }
  },
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: {
      guest: true
    }
  },
  {
    path: '/register',
    name: 'register',
    component: RegisterView,
    meta: {
      guest: true
    }
  },
  {
    path: '/verify-email',
    name: 'verifyEmail',
    component: VerifyEmailView,
    meta: {
      // 不設 guest：驗證連結為 token-based，須能在「瀏覽器已有另一帳號登入」時
      // 照常驗證；hideNav 維持獨立頁外觀。
      hideNav: true
    }
  },
  {
    path: '/register/verify-pending',
    name: 'verifyPending',
    component: VerifyPendingView,
    meta: {
      // 不設 guest：與驗證流程一致，不因已登入其他帳號被導走；
      // 元件本身有「沒帶 email 就回 /register」的狀態守衛。hideNav 維持獨立頁外觀。
      hideNav: true
    }
  },
  {
    path: '/forgot-password',
    name: 'forgotPassword',
    component: ForgotPasswordView,
    meta: {
      // 不設 guest：忘記/重設密碼以 email token 為憑證，須能在「瀏覽器已有
      // 另一帳號登入」時照常使用；hideNav 維持獨立頁外觀（隱藏導覽列）。
      hideNav: true
    }
  },
  {
    path: '/reset-password',
    name: 'resetPassword',
    component: ResetPasswordView,
    meta: {
      // 不設 guest：見 forgot-password 說明。重設連結為 token-based，
      // 不應因瀏覽器已登入其他帳號而被 guard 導走。
      hideNav: true
    }
  },
  {
    path: '/s/:token',
    name: 'sharedTranscript',
    component: SharedTranscriptView,
    meta: {
      public: true,
      hideNav: true
    }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守衛：檢查認證狀態
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // 初始化認證狀態（如果有 Token）
  if (!authStore.user && localStorage.getItem('access_token')) {
    await authStore.initialize()
  }

  // 需要認證的頁面
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({
      name: 'login',
      query: { redirect: to.fullPath }
    })
    return
  }

  // 訪客頁面（已登入用戶不應訪問）：套用與登入相同的落點邏輯
  // —— 有未刪除任務導任務列表，否則上傳頁（尊重 redirect query）
  if (to.meta.guest && authStore.isAuthenticated) {
    // 帶升級意圖的外部連結（intent=upgrade）：已登入者改去設定頁並開啟方案面板
    if (to.query.intent === 'upgrade') {
      next({ name: 'settings', query: { panel: 'plan' } })
      return
    }
    next(await resolveLandingPath(to.query.redirect))
    return
  }

  next()
})

router.afterEach((to) => {
  // 任務詳情頁的標題由組件內動態設定
  if (to.name !== 'transcript') {
    document.title = 'Sound Lite'
  }
})

export default router
