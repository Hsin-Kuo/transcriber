"""後台角色指派的護欄邏輯（RBAC P0-1 Phase 2）。

純函式，不碰 DB / HTTP——所需的 superadmin 人數由呼叫端查好傳進來。這樣護欄規則
（禁止移除最後一個 superadmin、不能改自己、只能指派給 admin、admin_role 白名單）
可以完全單元測試，endpoint 只負責把回傳的 error code 轉成 api_error。

回傳 None 表示通過；否則回傳 (error_code, message)。
"""
from typing import Optional, Tuple, Union

from ..auth.rbac import AdminRole

VALID_ADMIN_ROLES = {r.value for r in AdminRole}

ValidationError = Optional[Tuple[str, str]]


def validate_admin_role_assignment(
    *,
    is_self: bool,
    target_role: str,
    new_admin_role: str,
    target_admin_role: Optional[str],
    superadmin_count: int,
) -> ValidationError:
    """指派 admin_role（PUT /users/{id}/admin-role）的護欄。

    - new_admin_role 必須是白名單值。
    - 不能改自己的細分角色（避免自我鎖死 / 自我提權）。
    - 目標必須已是 admin（細分角色只對 admin 有意義）。
    - 若把某個現任 superadmin 改成非 superadmin，系統至少要再留 1 個 superadmin。
    """
    if new_admin_role not in VALID_ADMIN_ROLES:
        return ("ADMIN_INVALID_ADMIN_ROLE",
                f"admin_role must be one of {sorted(VALID_ADMIN_ROLES)}")
    if is_self:
        return ("ADMIN_CANNOT_CHANGE_OWN_ADMIN_ROLE",
                "You cannot change your own admin role")
    if target_role != "admin":
        return ("ADMIN_TARGET_NOT_ADMIN",
                "Target user is not an admin; promote to admin first")
    if _would_drop_last_superadmin(
        target_admin_role=target_admin_role,
        becomes_superadmin=(new_admin_role == AdminRole.SUPERADMIN.value),
        superadmin_count=superadmin_count,
    ):
        return ("ADMIN_LAST_SUPERADMIN", "Cannot remove the last superadmin")
    return None


def validate_role_demotion(
    *,
    target_admin_role: Optional[str],
    superadmin_count: int,
) -> ValidationError:
    """把 admin 降級為一般用戶（PUT /users/{id}/role role=user）前的護欄：
    不能降掉最後一個 superadmin。"""
    if _would_drop_last_superadmin(
        target_admin_role=target_admin_role,
        becomes_superadmin=False,
        superadmin_count=superadmin_count,
    ):
        return ("ADMIN_LAST_SUPERADMIN", "Cannot demote the last superadmin")
    return None


def normalize_promotion_admin_role(requested: Optional[str]) -> Union[str, Tuple[str, str]]:
    """把 user 升級為 admin 時要套用的 admin_role。

    未指定 → 預設 read_only（最小權限；升級者再視需要提權，避免相容路徑把新 admin
    當成 superadmin）。有指定則須通過白名單。回傳字串 = 採用的角色；回傳 tuple = 錯誤。
    """
    if requested is None:
        return AdminRole.READ_ONLY.value
    if requested not in VALID_ADMIN_ROLES:
        return ("ADMIN_INVALID_ADMIN_ROLE",
                f"admin_role must be one of {sorted(VALID_ADMIN_ROLES)}")
    return requested


def _would_drop_last_superadmin(
    *, target_admin_role: Optional[str], becomes_superadmin: bool, superadmin_count: int
) -> bool:
    is_currently_super = target_admin_role == AdminRole.SUPERADMIN.value
    return is_currently_super and not becomes_superadmin and superadmin_count <= 1
