"""後台 RBAC 角色與能力定義（P0-1 Phase 0）。

設計原則（見 docs/ADMIN_RBAC_PLAN.md）：
- 這裡只放「純資料 + 純函式」：角色、能力、role→能力對照與查詢。無 I/O、無 FastAPI
  依賴，可完全單元測試。實際的 request 期權限檢查在 auth/dependencies.py 的
  require_permission()。
- 以 Permission（細粒度能力）為授權單位，Role 只是 Permission 的組合包；日後新增
  角色或調整能力都只改這張表，不動任何 endpoint。
"""
from enum import Enum
from typing import Optional


class AdminRole(str, Enum):
    """後台管理員角色（存於 user 文件的 admin_role 欄位）。"""
    SUPERADMIN = "superadmin"   # 全開，含升降 admin / 退款 / 刪除 / 維運
    BILLING = "billing"         # 財務：營收、訂單、退款、配額補償
    SUPPORT = "support"         # 客服：看/管用戶與任務，但不能刪除/重設密碼/退款/升降 admin
    READ_ONLY = "read_only"     # 唯讀：任何 *_read 能力


class Permission(str, Enum):
    """細粒度能力。value 以 "<domain>:<action>" 命名；":read" 結尾者屬唯讀能力。"""
    USER_READ = "user:read"
    USER_MANAGE = "user:manage"                 # 停用/啟用帳號
    USER_QUOTA = "user:quota"                   # 改配額 / 重置月配額 / 補償額度
    USER_PASSWORD_RESET = "user:password_reset"
    TASK_READ = "task:read"
    TASK_MANAGE = "task:manage"                 # 取消任務
    TASK_DELETE = "task:delete"                 # 刪除 / 批次刪除
    ANALYTICS_READ = "analytics:read"           # 系統統計 / AI 成本
    BILLING_READ = "billing:read"               # 營收 / 訂單檢視
    BILLING_WRITE = "billing:write"             # 退款 / 手動開通（P0-3）
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"               # 稽核匯出（P0-4）
    ADMIN_GRANT = "admin:grant"                 # 升降 admin / 指派角色
    OPS = "ops"                                 # 維運清理等


# Role → 授予的 Permission 集合。superadmin 恆為全集；read_only 恆為所有唯讀能力。
ROLE_PERMISSIONS: dict[AdminRole, set[Permission]] = {
    AdminRole.SUPERADMIN: set(Permission),
    AdminRole.BILLING: {
        Permission.USER_READ,
        Permission.USER_QUOTA,
        Permission.TASK_READ,
        Permission.ANALYTICS_READ,
        Permission.BILLING_READ,
        Permission.BILLING_WRITE,
        Permission.AUDIT_READ,
        Permission.AUDIT_EXPORT,
    },
    AdminRole.SUPPORT: {
        Permission.USER_READ,
        Permission.USER_MANAGE,
        Permission.USER_QUOTA,
        Permission.TASK_READ,
        Permission.TASK_MANAGE,
        Permission.ANALYTICS_READ,
        Permission.AUDIT_READ,
    },
    AdminRole.READ_ONLY: {p for p in Permission if p.value.endswith(":read")},
}


def role_has(role: AdminRole, perm: Permission) -> bool:
    """該角色是否具備某能力。未知角色一律視為無權（回 False）。"""
    return perm in ROLE_PERMISSIONS.get(role, set())


def permissions_for(role: AdminRole) -> set[Permission]:
    """回傳角色的完整能力集合（供 /me/permissions 之類下發前端渲染用）。"""
    return set(ROLE_PERMISSIONS.get(role, set()))


def resolve_admin_role(raw) -> Optional[AdminRole]:
    """把 user 文件的 admin_role 原始值解析成 AdminRole。

    - None（尚未 migrate 的舊 admin）→ SUPERADMIN（Phase 0 相容政策，Phase 3 移除）。
    - 可辨識的 enum 值 → 對應 AdminRole。
    - 無法辨識 → None（由呼叫端決定如何處理，例如回 403）。
    """
    if raw is None:
        return AdminRole.SUPERADMIN
    try:
        return AdminRole(raw)
    except ValueError:
        return None
