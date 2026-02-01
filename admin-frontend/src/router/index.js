import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import AdminDashboard from '../views/AdminDashboard.vue'
import AuditLogsView from '../views/AuditLogsView.vue'
import UsersView from '../views/UsersView.vue'
import UserDetailView from '../views/UserDetailView.vue'
import AdminTasksView from '../views/AdminTasksView.vue'
import AdminTaskDetailView from '../views/AdminTaskDetailView.vue'
import LoginView from '../views/auth/LoginView.vue'

const routes = [
  {
    path: '/',
    name: 'admin',
    component: AdminDashboard,
    meta: {
      title: '系統統計',
      requiresAuth: true
    }
  },
  {
    path: '/users',
    name: 'users',
    component: UsersView,
    meta: {
      title: '用戶管理',
      requiresAuth: true
    }
  },
  {
    path: '/users/:id',
    name: 'user-detail',
    component: UserDetailView,
    meta: {
      title: '用戶詳情',
      requiresAuth: true
    }
  },
  {
    path: '/tasks',
    name: 'admin-tasks',
    component: AdminTasksView,
    meta: {
      title: '任務管理',
      requiresAuth: true
    }
  },
  {
    path: '/tasks/:id',
    name: 'admin-task-detail',
    component: AdminTaskDetailView,
    meta: {
      title: '任務詳情',
      requiresAuth: true
    }
  },
  {
    path: '/audit-logs',
    name: 'audit-logs',
    component: AuditLogsView,
    meta: {
      title: '操作記錄',
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
    next({ name: 'admin' })
    return
  }

  next()
})

router.afterEach((to) => {
  document.title = to.meta.title || 'Soundtime - 管理後台'
})

export default router
