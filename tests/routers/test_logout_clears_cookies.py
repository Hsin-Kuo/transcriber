"""驗證 /auth/logout 清掉兩個 cookie（access_token + refresh_token），
不是只清 refresh_token（既有行為）。

跟 tests/routers/test_batch_gating.py 同樣手法：monkeypatch repo/audit
logger，直接呼叫 router 函式。
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

CURRENT_USER = {"_id": "507f1f77bcf86cd799439011", "email": "susan@example.com"}


class _FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class _FakeUserRepo:
    def __init__(self, db):
        pass

    async def revoke_refresh_token(self, user_id, token):
        pass


class _FakeAuditLogger:
    async def log_auth(self, **kwargs):
        pass


def _get_set_cookie_headers(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k.lower() == b"set-cookie"]


@pytest.mark.asyncio
async def test_logout_clears_both_access_and_refresh_cookies(monkeypatch):
    monkeypatch.setattr(auth, "UserRepository", _FakeUserRepo)
    monkeypatch.setattr(auth, "get_audit_logger", lambda: _FakeAuditLogger())

    response = Response()
    result = await auth.logout(
        http_request=_FakeRequest(cookies={"refresh_token": "some-refresh-token"}),
        response=response,
        current_user=CURRENT_USER,
        db=object(),
    )

    assert result == {"message": "登出成功"}

    set_cookie_headers = _get_set_cookie_headers(response)
    cleared_names = set()
    for header in set_cookie_headers:
        # delete_cookie 會產生 "name=; Path=..." 這種 header，name 在第一個 = 前面
        name = header.split("=", 1)[0]
        cleared_names.add(name)

    assert "access_token" in cleared_names, f"access_token cookie 沒被清除，實際 headers={set_cookie_headers}"
    assert "refresh_token" in cleared_names, f"refresh_token cookie 沒被清除，實際 headers={set_cookie_headers}"
