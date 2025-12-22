import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import TranscriptionView from '../views/TranscriptionView.vue'
import TasksView from '../views/TasksView.vue'
import AudioEditorView from '../views/AudioEditorView.vue'
import AdminDashboard from '../views/AdminDashboard.vue'
import UserSettingsView from '../views/UserSettingsView.vue'
import TranscriptDetailView from '../views/TranscriptDetailView.vue'
import LoginView from '../views/auth/LoginView.vue'
import RegisterView from '../views/auth/RegisterView.vue'

const routes = [
  {
    path: '/',
    name: 'transcription',
    component: TranscriptionView,
    meta: {
      title: '轉錄服務',
      requiresAuth: true
    }
  },
  {
    path: '/tasks',
    name: 'tasks',
    component: TasksView,
    meta: {
      title: '所有任務',
      requiresAuth: true
    }
  },
  {
    path: '/editor',
    name: 'audioEditor',
    component: AudioEditorView,
    meta: {
      title: '音訊編輯',
      requiresAuth: true
    }
  },
  {
    path: '/admin',
    name: 'admin',
    component: AdminDashboard,
    meta: {
      title: '系統統計後台',
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
  document.title = to.meta.title || 'Whisper 逐字稿工具'
})

export default router
