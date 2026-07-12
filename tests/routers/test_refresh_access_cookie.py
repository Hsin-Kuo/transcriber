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
from src.auth.jwt_handler import create_refresh_token  # noqa: E402

_PAYLOAD = {"sub": "507f1f77bcf86cd799439011", "email": "susan@example.com", "role": "user"}


class _FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class _FakeUserRepoValid:
    def __init__(self, db):
        pass

    async def verify_refresh_token(self, user_id, token):
        return True


def _get_set_cookie_headers(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k.lower() == b"set-cookie"]


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
        (h for h in _get_set_cookie_headers(response) if h.startswith("access_token=")), None
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
