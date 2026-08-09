"""驗證 /auth/refresh 真的把新 access token 種進 cookie（這是硬切換能
安全上線的關鍵路徑——舊分頁的 401 攔截器會呼叫這支，順便把 cookie
補上，使用者完全無感，見 PR 說明的「為什麼不需要過渡期」論證）。

跟 tests/routers/test_batch_gating.py 同樣手法：monkeypatch repo，
直接呼叫 router 函式，不起真的 Mongo。
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi import Response

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import auth  # noqa: E402
from src.auth.jwt_handler import create_refresh_token, verify_token  # noqa: E402
from tests.response_helpers import get_set_cookie_headers  # noqa: E402

_PAYLOAD = {"sub": "507f1f77bcf86cd799439011", "email": "susan@example.com", "role": "user"}


class _FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class _FakeUserRepoValid:
    """DB user doc 預設是 active、role=user、email 與舊 refresh claim 一致。

    P2-12：refresh 現在會查 `get_by_id`，既有的 fake repo 必須補上這個方法，
    否則所有既有測試都會因為呼叫不存在的方法而炸掉（不是 auth.py 的邏輯錯，是
    fake 沒跟上新規格——見 P2-12 規格要求「補 get_by_id」）。
    """
    _DB_USER = {"_id": "507f1f77bcf86cd799439011", "email": "susan@example.com",
                "role": "user", "is_active": True, "deleted_at": None}

    def __init__(self, db):
        pass

    async def verify_refresh_token(self, user_id, token):
        return True

    async def get_by_id(self, user_id):
        return dict(self._DB_USER)


def _decode_access_cookie(response: Response):
    access_cookie = next(
        (h for h in get_set_cookie_headers(response) if h.startswith("access_token=")), None
    )
    assert access_cookie is not None
    token = access_cookie.split("access_token=", 1)[1].split(";", 1)[0]
    return verify_token(token, "access")


@pytest.mark.asyncio
async def test_refresh_sets_new_access_cookie_and_expires_at(monkeypatch):
    monkeypatch.setattr(auth, "UserRepository", _FakeUserRepoValid)

    refresh_token_value = create_refresh_token(_PAYLOAD)
    response = Response()
    result = await auth.refresh_token(
        request=_FakeRequest(cookies={"refresh_token": refresh_token_value}),
        response=response,
        db=object(),
    )

    assert result.expires_at is not None
    assert result.access_token is None

    access_cookie = next(
        (h for h in get_set_cookie_headers(response) if h.startswith("access_token=")), None
    )
    assert access_cookie is not None
    assert "HttpOnly" in access_cookie
    assert "Path=/" in access_cookie and "Path=/auth" not in access_cookie


@pytest.mark.asyncio
async def test_refresh_without_cookie_raises_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await auth.refresh_token(request=_FakeRequest(), response=Response(), db=object())
    assert exc.value.status_code == 401


# ── P2-12：refresh 撤銷/降權防護 ──────────────────────────────────────────────

class _FakeUserRepoInactive(_FakeUserRepoValid):
    async def get_by_id(self, user_id):
        return {**self._DB_USER, "is_active": False}


class _FakeUserRepoDeleted(_FakeUserRepoValid):
    async def get_by_id(self, user_id):
        return {**self._DB_USER, "deleted_at": 1723000000}


class _FakeUserRepoMissing(_FakeUserRepoValid):
    async def get_by_id(self, user_id):
        return None


class _FakeUserRepoDowngraded(_FakeUserRepoValid):
    """DB 目前 role=user，但舊 refresh token 的 claim 裡 role=admin——
    模擬「曾是 admin、被降權後 refresh token 還沒過期」的情境。"""
    async def get_by_id(self, user_id):
        return {**self._DB_USER, "role": "user", "email": "downgraded@example.com"}


@pytest.mark.parametrize("fake_repo_cls", [
    _FakeUserRepoInactive, _FakeUserRepoDeleted, _FakeUserRepoMissing,
])
@pytest.mark.asyncio
async def test_refresh_rejects_inactive_deleted_or_missing_user(monkeypatch, fake_repo_cls):
    from fastapi import HTTPException

    monkeypatch.setattr(auth, "UserRepository", fake_repo_cls)
    refresh_token_value = create_refresh_token(_PAYLOAD)
    response = Response()

    with pytest.raises(HTTPException) as exc:
        await auth.refresh_token(
            request=_FakeRequest(cookies={"refresh_token": refresh_token_value}),
            response=response,
            db=object(),
        )
    assert exc.value.status_code == 401

    # 401 時 access/refresh cookie 都要被清除（比照刪帳號先例，避免瀏覽器繼續帶著
    # 已停用/刪除帳號的 cookie 打其他 API）。response.delete_cookie 會下 Max-Age=0。
    all_cookie_headers = get_set_cookie_headers(response)
    access_hdr = next((h for h in all_cookie_headers if h.startswith("access_token=")), None)
    refresh_hdr = next((h for h in all_cookie_headers if h.startswith("refresh_token=")), None)
    assert access_hdr is not None and "Max-Age=0" in access_hdr
    assert refresh_hdr is not None and "Max-Age=0" in refresh_hdr


class _FakeUserRepoRevoked(_FakeUserRepoValid):
    """refresh token 已被 revoke_all 清空（admin 停用/重設密碼後最常撞的路徑）——
    verify_refresh_token 回 False，早於 is_active 檢查。"""
    async def verify_refresh_token(self, user_id, token):
        return False


@pytest.mark.asyncio
async def test_refresh_revoked_branch_clears_both_cookies(monkeypatch):
    """L1（第二意見審查）：停用帳號走 revoke_all → 下次 refresh 撞 revoked 分支（不是
    is_active 分支），這條也要清 access cookie，否則 access 留到 ≤15 分鐘自然過期。"""
    from fastapi import HTTPException

    monkeypatch.setattr(auth, "UserRepository", _FakeUserRepoRevoked)
    refresh_token_value = create_refresh_token(_PAYLOAD)
    response = Response()

    with pytest.raises(HTTPException) as exc:
        await auth.refresh_token(
            request=_FakeRequest(cookies={"refresh_token": refresh_token_value}),
            response=response, db=object(),
        )
    assert exc.value.status_code == 401
    headers = get_set_cookie_headers(response)
    access_hdr = next((h for h in headers if h.startswith("access_token=")), None)
    refresh_hdr = next((h for h in headers if h.startswith("refresh_token=")), None)
    assert access_hdr is not None and "Max-Age=0" in access_hdr
    assert refresh_hdr is not None and "Max-Age=0" in refresh_hdr


@pytest.mark.asyncio
async def test_refresh_new_access_token_role_and_email_come_from_db_not_old_claim(monkeypatch):
    """核心迴歸：舊 refresh claim 是 role=admin，DB 現在是 role=user（已被降權）——
    新 access token 必須是 role=user，不能讓舊 claim 復活 admin 權限。"""
    monkeypatch.setattr(auth, "UserRepository", _FakeUserRepoDowngraded)

    admin_claim_payload = {**_PAYLOAD, "role": "admin"}
    refresh_token_value = create_refresh_token(admin_claim_payload)
    response = Response()

    result = await auth.refresh_token(
        request=_FakeRequest(cookies={"refresh_token": refresh_token_value}),
        response=response,
        db=object(),
    )
    assert result.expires_at is not None

    new_token_data = _decode_access_cookie(response)
    assert new_token_data is not None
    assert new_token_data.role == "user"  # 來自 DB，不是舊 claim 的 admin
    assert new_token_data.email == "downgraded@example.com"
