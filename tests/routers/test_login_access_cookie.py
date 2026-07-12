"""驗證 /auth/login 真的把 access token 寫進 httpOnly cookie：body 不再回傳
有意義的 access_token（硬切換完成後的最終狀態），但 expires_at 要有值、
cookie 要正確種下去。

跟 tests/routers/test_batch_gating.py 同樣手法：monkeypatch router 模組內
的 repo/audit logger 名稱，直接呼叫 router 函式，不起真的 Mongo。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import Response  # noqa: E402

from src.routers import auth  # noqa: E402
from src.models.auth import UserLogin  # noqa: E402

ACTIVE_VERIFIED_USER = {
    "_id": "507f1f77bcf86cd799439011",
    "email": "susan@example.com",
    "password_hash": "irrelevant-because-verify_password-is-mocked",
    "role": "user",
    "email_verified": True,
    "is_active": True,
}


class _FakeRequest:
    headers = {}
    client = None


class _FakeRateLimitRepo:
    def __init__(self, db):
        pass

    async def check_rate_limit(self, **kwargs):
        return True, None

    async def record_request(self, **kwargs):
        pass

    async def clear_records(self, *args, **kwargs):
        pass


class _FakeUserRepo:
    def __init__(self, db):
        pass

    async def get_by_email(self, email):
        return ACTIVE_VERIFIED_USER

    async def save_refresh_token(self, user_id, token):
        pass


class _FakeAuditLogger:
    async def log_auth(self, **kwargs):
        pass


def _get_set_cookie_headers(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k.lower() == b"set-cookie"]


@pytest.mark.asyncio
async def test_login_sets_access_cookie_and_returns_expires_at(monkeypatch):
    monkeypatch.setattr(auth, "RateLimitRepository", _FakeRateLimitRepo)
    monkeypatch.setattr(auth, "UserRepository", _FakeUserRepo)
    monkeypatch.setattr(auth, "get_audit_logger", lambda: _FakeAuditLogger())
    monkeypatch.setattr(auth, "verify_password", lambda plain, hashed: True)

    response = Response()
    result = await auth.login(
        request=_FakeRequest(),
        response=response,
        credentials=UserLogin(email="susan@example.com", password="whatever"),
        db=object(),
    )

    assert result.expires_at is not None
    # 硬切換後 body 不再回傳有意義的 access_token——cookie 才是唯一來源
    assert result.access_token is None

    set_cookie_headers = _get_set_cookie_headers(response)
    access_cookie = next((h for h in set_cookie_headers if h.startswith("access_token=")), None)
    refresh_cookie = next((h for h in set_cookie_headers if h.startswith("refresh_token=")), None)

    assert access_cookie is not None, f"沒有種下 access_token cookie，實際 headers={set_cookie_headers}"
    assert "HttpOnly" in access_cookie
    assert "Path=/" in access_cookie and "Path=/auth" not in access_cookie

    assert refresh_cookie is not None
    assert "Path=/auth" in refresh_cookie
