"""RBAC P0-1 Phase 1 — admin router wiring 規格測試。

兩件事：
1. wiring：內省 admin router 每支 route 的依賴樹，斷言它掛的 require_permission 對應
   到「預期的能力」。這把 endpoint→permission 對照鎖成可執行規格——日後有人新增
   endpoint 忘了掛權限、或掛錯權限，這個測試就會紅。
2. /me/permissions：回傳當前 admin 的角色與能力清單（含未 migrate 的相容行為）。
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

from src.routers.admin import router, get_my_permissions  # noqa: E402
from src.auth.rbac import Permission, permissions_for, AdminRole  # noqa: E402

# endpoint→permission 的期望對照（權威施工清單，見 docs/ADMIN_RBAC_PLAN.md）
EXPECTED = {
    ("GET", "/api/admin/users"): Permission.USER_READ,
    ("GET", "/api/admin/users/{user_id}"): Permission.USER_READ,
    ("PUT", "/api/admin/users/{user_id}/status"): Permission.USER_MANAGE,
    ("PUT", "/api/admin/users/{user_id}/role"): Permission.ADMIN_GRANT,
    ("PUT", "/api/admin/users/{user_id}/admin-role"): Permission.ADMIN_GRANT,
    ("PUT", "/api/admin/users/{user_id}/quota"): Permission.USER_QUOTA,
    ("POST", "/api/admin/users/{user_id}/reset-quota"): Permission.USER_QUOTA,
    ("POST", "/api/admin/users/{user_id}/extra-quota"): Permission.USER_QUOTA,
    ("POST", "/api/admin/users/{user_id}/reset-password"): Permission.USER_PASSWORD_RESET,
    ("GET", "/api/admin/tasks"): Permission.TASK_READ,
    ("GET", "/api/admin/tasks/{task_id}"): Permission.TASK_READ,
    ("POST", "/api/admin/tasks/{task_id}/cancel"): Permission.TASK_MANAGE,
    ("DELETE", "/api/admin/tasks/{task_id}"): Permission.TASK_DELETE,
    ("POST", "/api/admin/tasks/batch/delete"): Permission.TASK_DELETE,
    ("GET", "/api/admin/statistics"): Permission.ANALYTICS_READ,
    ("GET", "/api/admin/stats/online"): Permission.ANALYTICS_READ,
    ("GET", "/api/admin/revenue"): Permission.BILLING_READ,
    ("GET", "/api/admin/cost"): Permission.ANALYTICS_READ,
    ("GET", "/api/admin/audit-logs"): Permission.AUDIT_READ,
    ("GET", "/api/admin/audit-logs/failed"): Permission.AUDIT_READ,
    ("GET", "/api/admin/audit-logs/statistics"): Permission.AUDIT_READ,
    ("GET", "/api/admin/audit-logs/resource/{resource_id}"): Permission.AUDIT_READ,
    ("POST", "/api/admin/cleanup/handoff-orphans"): Permission.OPS,
}

# 這些 route 刻意不掛特定能力（任何 admin 皆可）
NO_PERMISSION = {("GET", "/api/admin/me/permissions")}


def _required_permissions(route):
    """遞迴走 route 依賴樹，收集所有 require_permission 標記的能力。"""
    found = []

    def walk(dep):
        call = getattr(dep, "call", None)
        perm = getattr(call, "_required_permission", None)
        if perm is not None:
            found.append(perm)
        for sub in getattr(dep, "dependencies", []):
            walk(sub)

    walk(route.dependant)
    return found


def _admin_routes():
    out = []
    for route in router.routes:
        for method in (route.methods or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            out.append((method, route.path, route))
    return out


class TestPermissionWiring:
    def test_every_endpoint_wired_to_expected_permission(self):
        for method, path, route in _admin_routes():
            key = (method, path)
            perms = _required_permissions(route)
            if key in NO_PERMISSION:
                assert perms == [], f"{key} 不應掛特定能力，卻掛了 {perms}"
                continue
            assert key in EXPECTED, f"未知的 admin route {key}——請補進 EXPECTED 對照並掛權限"
            assert perms == [EXPECTED[key]], (
                f"{key} 期望掛 {EXPECTED[key]}，實際 {perms}"
            )

    def test_all_expected_routes_exist(self):
        """反向守衛：對照表裡列的 route 都必須真的存在（避免對照表過時。）"""
        actual = {(m, p) for m, p, _ in _admin_routes()}
        for key in EXPECTED:
            assert key in actual, f"對照表列了 {key} 但 router 沒有這支 route"


# ---------- /me/permissions ----------

class _FakeUsers:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, query):
        return self._doc


class _FakeDB:
    def __init__(self, doc):
        self.users = _FakeUsers(doc)


class TestMyPermissions:
    @pytest.mark.asyncio
    async def test_returns_role_permissions(self):
        admin = {"_id": ObjectId("507f1f77bcf86cd799439011")}
        db = _FakeDB({"_id": admin["_id"], "role": "admin", "admin_role": "support"})
        result = await get_my_permissions(admin=admin, db=db)
        assert result["role"] == "support"
        assert set(result["permissions"]) == {p.value for p in permissions_for(AdminRole.SUPPORT)}

    @pytest.mark.asyncio
    async def test_unmigrated_admin_denied(self):
        # Phase 3：無 admin_role → 403（相容後門已移除）
        admin = {"_id": ObjectId("507f1f77bcf86cd799439011")}
        db = _FakeDB({"_id": admin["_id"], "role": "admin"})  # 無 admin_role
        with pytest.raises(HTTPException) as exc:
            await get_my_permissions(admin=admin, db=db)
        assert exc.value.status_code == 403
