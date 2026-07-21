"""RBAC P0-1 Phase 2 — 角色指派護欄純函式測試。

把「不能移除最後一個 superadmin / 不能改自己 / 只能指派給 admin / 白名單」這些安全
約束鎖成可執行規格。這些是授權層的關鍵不變式，值得直接、窮舉地測。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.admin_role_service import (  # noqa: E402
    validate_admin_role_assignment,
    validate_role_demotion,
    normalize_promotion_admin_role,
    VALID_ADMIN_ROLES,
)


class TestValidateAdminRoleAssignment:
    def _ok_args(self, **over):
        base = dict(
            is_self=False,
            target_role="admin",
            new_admin_role="support",
            target_admin_role="read_only",
            superadmin_count=2,
        )
        base.update(over)
        return base

    def test_valid_assignment_passes(self):
        assert validate_admin_role_assignment(**self._ok_args()) is None

    def test_invalid_role_rejected(self):
        err = validate_admin_role_assignment(**self._ok_args(new_admin_role="wizard"))
        assert err[0] == "ADMIN_INVALID_ADMIN_ROLE"

    def test_self_change_rejected(self):
        err = validate_admin_role_assignment(**self._ok_args(is_self=True))
        assert err[0] == "ADMIN_CANNOT_CHANGE_OWN_ADMIN_ROLE"

    def test_target_not_admin_rejected(self):
        err = validate_admin_role_assignment(**self._ok_args(target_role="user"))
        assert err[0] == "ADMIN_TARGET_NOT_ADMIN"

    def test_demoting_last_superadmin_rejected(self):
        err = validate_admin_role_assignment(**self._ok_args(
            target_admin_role="superadmin", new_admin_role="support", superadmin_count=1))
        assert err[0] == "ADMIN_LAST_SUPERADMIN"

    def test_demoting_superadmin_when_others_exist_ok(self):
        assert validate_admin_role_assignment(**self._ok_args(
            target_admin_role="superadmin", new_admin_role="support", superadmin_count=2)) is None

    def test_superadmin_keeping_superadmin_ok_even_if_last(self):
        # 把 superadmin 再設成 superadmin（no-op），即使只有 1 個也不該被擋
        assert validate_admin_role_assignment(**self._ok_args(
            target_admin_role="superadmin", new_admin_role="superadmin", superadmin_count=1)) is None

    def test_promoting_to_superadmin_ok(self):
        assert validate_admin_role_assignment(**self._ok_args(
            target_admin_role="support", new_admin_role="superadmin", superadmin_count=1)) is None


class TestValidateRoleDemotion:
    def test_demoting_last_superadmin_rejected(self):
        err = validate_role_demotion(target_admin_role="superadmin", superadmin_count=1)
        assert err[0] == "ADMIN_LAST_SUPERADMIN"

    def test_demoting_superadmin_with_others_ok(self):
        assert validate_role_demotion(target_admin_role="superadmin", superadmin_count=3) is None

    def test_demoting_non_superadmin_ok(self):
        assert validate_role_demotion(target_admin_role="support", superadmin_count=1) is None
        assert validate_role_demotion(target_admin_role=None, superadmin_count=1) is None


class TestNormalizePromotionAdminRole:
    def test_default_is_read_only(self):
        assert normalize_promotion_admin_role(None) == "read_only"

    def test_valid_passthrough(self):
        assert normalize_promotion_admin_role("support") == "support"

    def test_invalid_returns_error(self):
        result = normalize_promotion_admin_role("wizard")
        assert isinstance(result, tuple) and result[0] == "ADMIN_INVALID_ADMIN_ROLE"

    def test_valid_roles_set_matches_enum(self):
        assert VALID_ADMIN_ROLES == {"superadmin", "billing", "support", "read_only"}
