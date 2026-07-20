"""RBAC P0-1 Phase 0 規格測試。

分兩層：
1. 純能力表（rbac.py）——角色↔能力對照是授權的單一事實來源，鎖住「support 不能刪除
   /重設密碼/退款/升降 admin」「read_only 只有唯讀」這些關鍵約束。
2. require_permission 依賴——含過渡相容（未 migrate 的 admin 暫當 superadmin）與
   非法角色被擋等 request 期行為。
"""
import os
import sys
from pathlib import Path

import pytest
from bson import ObjectId
from fastapi import HTTPException

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.auth.rbac import AdminRole, Permission, ROLE_PERMISSIONS, role_has, permissions_for  # noqa: E402
from src.auth.dependencies import require_permission  # noqa: E402

_UID = "507f1f77bcf86cd799439011"


# ---------- 純能力表 ----------

class TestRolePermissions:
    def test_superadmin_has_everything(self):
        for perm in Permission:
            assert role_has(AdminRole.SUPERADMIN, perm), f"superadmin 應具備 {perm}"

    def test_read_only_has_exactly_read_permissions(self):
        expected = {p for p in Permission if p.value.endswith(":read")}
        assert ROLE_PERMISSIONS[AdminRole.READ_ONLY] == expected
        # read_only 不得有任何寫入/危險能力
        for perm in (Permission.USER_MANAGE, Permission.TASK_DELETE,
                     Permission.BILLING_WRITE, Permission.ADMIN_GRANT):
            assert not role_has(AdminRole.READ_ONLY, perm)

    def test_support_cannot_do_dangerous_ops(self):
        """客服的核心約束：不能重設密碼、刪除、退款、升降 admin。"""
        for perm in (Permission.USER_PASSWORD_RESET, Permission.TASK_DELETE,
                     Permission.BILLING_WRITE, Permission.ADMIN_GRANT, Permission.OPS):
            assert not role_has(AdminRole.SUPPORT, perm), f"support 不應有 {perm}"
        # 但客服該有的日常能力要在
        for perm in (Permission.USER_READ, Permission.USER_MANAGE,
                     Permission.USER_QUOTA, Permission.TASK_MANAGE):
            assert role_has(AdminRole.SUPPORT, perm)

    def test_billing_has_billing_write_but_not_task_delete_or_grant(self):
        assert role_has(AdminRole.BILLING, Permission.BILLING_WRITE)
        assert role_has(AdminRole.BILLING, Permission.AUDIT_EXPORT)
        assert not role_has(AdminRole.BILLING, Permission.TASK_DELETE)
        assert not role_has(AdminRole.BILLING, Permission.ADMIN_GRANT)

    def test_admin_grant_is_superadmin_only(self):
        holders = [r for r in AdminRole if role_has(r, Permission.ADMIN_GRANT)]
        assert holders == [AdminRole.SUPERADMIN]

    def test_permissions_for_returns_copy(self):
        got = permissions_for(AdminRole.SUPPORT)
        got.add(Permission.TASK_DELETE)  # 改回傳值不得污染原表
        assert Permission.TASK_DELETE not in ROLE_PERMISSIONS[AdminRole.SUPPORT]


# ---------- require_permission 依賴 ----------

class _FakeUsers:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, query):
        return self._doc


class _FakeDB:
    def __init__(self, doc):
        self.users = _FakeUsers(doc)


def _admin_doc(admin_role):
    doc = {"_id": ObjectId(_UID), "role": "admin"}
    if admin_role is not None:
        doc["admin_role"] = admin_role
    return doc


def _current_user():
    return {"_id": ObjectId(_UID), "role": "admin"}


class TestRequirePermission:
    @pytest.mark.asyncio
    async def test_role_with_permission_passes(self):
        checker = require_permission(Permission.USER_READ)
        result = await checker(current_user=_current_user(), db=_FakeDB(_admin_doc("support")))
        assert result["admin_role"] == "support"

    @pytest.mark.asyncio
    async def test_role_without_permission_403(self):
        checker = require_permission(Permission.TASK_DELETE)
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=_current_user(), db=_FakeDB(_admin_doc("support")))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unmigrated_admin_treated_as_superadmin(self):
        """過渡相容：沒有 admin_role 的舊 admin 暫時全開（Phase 3 前）。"""
        checker = require_permission(Permission.ADMIN_GRANT)
        result = await checker(current_user=_current_user(), db=_FakeDB(_admin_doc(None)))
        assert result["admin_role"] == AdminRole.SUPERADMIN.value

    @pytest.mark.asyncio
    async def test_invalid_admin_role_403(self):
        checker = require_permission(Permission.USER_READ)
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=_current_user(), db=_FakeDB(_admin_doc("wizard")))
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_read_only_blocked_from_write(self):
        checker = require_permission(Permission.USER_MANAGE)
        with pytest.raises(HTTPException) as exc:
            await checker(current_user=_current_user(), db=_FakeDB(_admin_doc("read_only")))
        assert exc.value.status_code == 403
