"""P2-12（金流體檢）：admin 停用帳號 / admin 重設密碼要連動撤銷全部 refresh token。

跟 tests/routers/test_refresh_access_cookie.py 同樣手法：monkeypatch repo，直接呼叫
router 函式（略過 FastAPI 的 Depends 解析——顯式傳入 kwargs 即可覆蓋預設值），不起
真的 Mongo、不觸碰 audit_logger 的全域狀態（直接 monkeypatch log_admin_action）。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import admin as admin_router  # noqa: E402


class FakeRequest:
    """log_admin_action 只需要 .headers.get(...) / .client——這裡整支被 monkeypatch 掉，
    純粹是位置參數需要一個佔位物件。"""
    headers = {}
    client = None


ADMIN = {"_id": ObjectId(), "email": "admin@example.com"}


class _FakeUserRepo:
    def __init__(self, db):
        pass

    _users = {}

    @classmethod
    def seed(cls, user_id, doc):
        cls._users[str(user_id)] = doc

    async def get_by_id(self, user_id):
        return self._users.get(str(user_id))

    async def update(self, user_id, updates):
        self._users[str(user_id)] = {**self._users.get(str(user_id), {}), **updates}
        return True

    async def count(self, query):
        return 1

    revoke_all_refresh_tokens: AsyncMock


@pytest.fixture(autouse=True)
def _patch_admin_router(monkeypatch):
    monkeypatch.setattr(admin_router, "log_admin_action", AsyncMock())
    monkeypatch.setattr(admin_router, "_notify_user_async", lambda **kw: None)
    yield


def _make_fake_repo_cls(user_doc):
    """回傳一個乾淨的 _FakeUserRepo 子類，帶獨立的 revoke_all_refresh_tokens mock
    （避免測試間共用 class-level state 互相污染)。"""
    cls = type("_FakeUserRepoInstance", (_FakeUserRepo,), {"_users": {}})
    cls.seed(user_doc["_id"], user_doc)
    cls.revoke_all_refresh_tokens = AsyncMock(return_value=True)
    return cls


@pytest.mark.asyncio
async def test_disable_user_revokes_all_refresh_tokens(monkeypatch):
    target_id = ObjectId()
    fake_cls = _make_fake_repo_cls({"_id": target_id, "email": "u@x.com", "is_active": True})
    monkeypatch.setattr(admin_router, "UserRepository", fake_cls)

    body = admin_router.UpdateUserStatusRequest(is_active=False)
    result = await admin_router.update_user_status(
        user_id=str(target_id), body=body, http_request=FakeRequest(),
        admin=ADMIN, db=object(),
    )

    assert result["success"] is True
    fake_cls.revoke_all_refresh_tokens.assert_awaited_once_with(str(target_id))


@pytest.mark.asyncio
async def test_enable_user_does_not_revoke_refresh_tokens(monkeypatch):
    target_id = ObjectId()
    fake_cls = _make_fake_repo_cls({"_id": target_id, "email": "u@x.com", "is_active": False})
    monkeypatch.setattr(admin_router, "UserRepository", fake_cls)

    body = admin_router.UpdateUserStatusRequest(is_active=True)
    await admin_router.update_user_status(
        user_id=str(target_id), body=body, http_request=FakeRequest(),
        admin=ADMIN, db=object(),
    )

    fake_cls.revoke_all_refresh_tokens.assert_not_awaited()


@pytest.mark.asyncio
async def test_disable_user_revoke_failure_does_not_break_endpoint(monkeypatch):
    """revoke 失敗（DB 抖動）不該讓停用帳號本身回傳失敗——包 try/except。"""
    target_id = ObjectId()
    fake_cls = _make_fake_repo_cls({"_id": target_id, "email": "u@x.com", "is_active": True})
    fake_cls.revoke_all_refresh_tokens = AsyncMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(admin_router, "UserRepository", fake_cls)

    body = admin_router.UpdateUserStatusRequest(is_active=False)
    result = await admin_router.update_user_status(
        user_id=str(target_id), body=body, http_request=FakeRequest(),
        admin=ADMIN, db=object(),
    )
    assert result["success"] is True  # 主流程仍然成功


@pytest.mark.asyncio
async def test_reset_password_revokes_all_refresh_tokens(monkeypatch):
    target_id = ObjectId()
    fake_cls = _make_fake_repo_cls({"_id": target_id, "email": "u@x.com"})
    monkeypatch.setattr(admin_router, "UserRepository", fake_cls)

    body = admin_router.ResetPasswordRequest(new_password="NewPass123")
    result = await admin_router.reset_user_password(
        user_id=str(target_id), body=body, http_request=FakeRequest(),
        admin=ADMIN, db=object(),
    )

    assert result["success"] is True
    fake_cls.revoke_all_refresh_tokens.assert_awaited_once_with(str(target_id))


@pytest.mark.asyncio
async def test_role_change_does_not_revoke_refresh_tokens(monkeypatch):
    """P2-12 A4：role 變更刻意不撤銷（A2 修好後舊 refresh 只會鑄出 DB 當前 role 的
    token，沒有安全洞）——這裡確認 update_user_role 完全不呼叫 revoke_all_refresh_tokens
    （fake repo 甚至不提供這個方法都不該被摸到）。"""
    target_id = ObjectId()
    fake_cls = _make_fake_repo_cls({"_id": target_id, "email": "u@x.com", "role": "user"})
    # 刻意不設 revoke_all_refresh_tokens，若被呼叫到會是 AttributeError（比 Mock 更嚴格）
    if hasattr(fake_cls, "revoke_all_refresh_tokens"):
        delattr(fake_cls, "revoke_all_refresh_tokens")
    monkeypatch.setattr(admin_router, "UserRepository", fake_cls)
    monkeypatch.setattr(admin_router, "validate_role_demotion", lambda **kw: None, raising=False)

    body = admin_router.UpdateUserRoleRequest(role="admin", admin_role="support")
    result = await admin_router.update_user_role(
        user_id=str(target_id), body=body, http_request=FakeRequest(),
        admin=ADMIN, db=object(),
    )
    assert result["success"] is True


# ── L4（第二意見審查）：自助改密碼也要撤銷全部 refresh token ──────────────────

@pytest.mark.asyncio
async def test_change_password_revokes_all_refresh_tokens(monkeypatch):
    """帳號被盜 → 使用者改密碼趕走入侵者，入侵者手上的 refresh token 必須失效。
    與 admin 重設 / 自助重設一致（credential_flow / admin.py）。"""
    from src.routers import auth as auth_router
    from src.models.auth import ChangePasswordRequest
    from src.auth.password import hash_password

    uid = ObjectId()
    old_hash = hash_password("OldPass123")

    class _Repo:
        revoke = AsyncMock(return_value=True)

        def __init__(self, db):
            pass

        async def get_by_id(self, user_id):
            return {"_id": uid, "email": "u@example.com", "password_hash": old_hash}

        async def update(self, user_id, updates):
            return True

        async def revoke_all_refresh_tokens(self, user_id):
            return await _Repo.revoke(user_id)

    _Repo.revoke = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_router, "UserRepository", _Repo)

    audit = AsyncMock()
    monkeypatch.setattr(auth_router, "get_audit_logger", lambda: type("A", (), {"log_auth": audit})())

    await auth_router.change_password(
        http_request=FakeRequest(),
        request=ChangePasswordRequest(current_password="OldPass123", new_password="NewPass456"),
        current_user={"_id": uid},
        db=object(),
    )
    _Repo.revoke.assert_awaited_once_with(str(uid))
