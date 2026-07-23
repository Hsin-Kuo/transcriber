/**
 * 後台能力常數 — 與後端 src/auth/rbac.py 的 Permission enum 一一對應。
 * 用來搭配 authStore.can(PERM.X) 隱藏無權操作的 UI。
 *
 * 注意：這只是「渲染輔助」。真正的授權閘門在後端各 endpoint 的 require_permission，
 * 前端隱藏純為 UX/縱深防禦——就算沒隱藏，後端仍會回 403。
 */
export const PERM = {
  USER_READ: 'user:read',
  USER_MANAGE: 'user:manage',
  USER_QUOTA: 'user:quota',
  USER_PASSWORD_RESET: 'user:password_reset',
  TASK_READ: 'task:read',
  TASK_MANAGE: 'task:manage',
  TASK_DELETE: 'task:delete',
  ANALYTICS_READ: 'analytics:read',
  PRESENCE_VIEW: 'presence:view',
  BILLING_READ: 'billing:read',
  BILLING_WRITE: 'billing:write',
  AUDIT_READ: 'audit:read',
  AUDIT_EXPORT: 'audit:export',
  ADMIN_GRANT: 'admin:grant',
  OPS: 'ops',
}
