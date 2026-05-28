import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

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
      title: '上傳音檔',
      requiresAuth: true
    }
  },
  {
    path: '/all',
    name: 'tasks',
    component: TasksView,
    meta: {
      title: '所有任務',
      requiresAuth: true
    }
  },
  {
    path: '/settings',
    name: 'settings',
    component: UserSettingsView,
    meta: {
      title: '使用者設定',
      requiresAuth: true
    }
  },
  {
    path: '/checkout',
    name: 'checkout',
    component: CheckoutView,
    meta: {
      title: '結帳',
      requiresAuth: true,
      hideNav: true
    }
  },
  {
    path: '/payment/return',
    name: 'paymentReturn',
    component: PaymentReturnView,
    meta: {
      title: '付款結果',
      requiresAuth: true,
      hideNav: true
    }
  },
  {
    path: '/transcript/:taskId',
    name: 'transcript',
    component: TranscriptDetailView,
    meta: {
      title: '逐字稿詳情',
      requiresAuth: true
    }
  },
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: {
      title: '登入',
      guest: true
    }
  },
  {
    path: '/register',
    name: 'register',
    component: RegisterView,
    meta: {
      title: '註冊',
      guest: true
    }
  },
  {
    path: '/verify-email',
    name: 'verifyEmail',
    component: VerifyEmailView,
    meta: {
      title: 'Email 驗證',
      guest: true
    }
  },
  {
    path: '/register/verify-pending',
    name: 'verifyPending',
    component: VerifyPendingView,
    meta: {
      title: '請查看您的信箱',
      guest: true
    }
  },
  {
    path: '/forgot-password',
    name: 'forgotPassword',
    component: ForgotPasswordView,
    meta: {
      title: '忘記密碼',
      guest: true
    }
  },
  {
    path: '/reset-password',
    name: 'resetPassword',
    component: ResetPasswordView,
    meta: {
      title: '重設密碼',
      guest: true
    }
  },
  {
    path: '/s/:token',
    name: 'sharedTranscript',
    component: SharedTranscriptView,
    meta: {
      title: '分享的逐字稿',
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

  // 訪客頁面（已登入用戶不應訪問）
  if (to.meta.guest && authStore.isAuthenticated) {
    next({ name: 'transcription' })
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
