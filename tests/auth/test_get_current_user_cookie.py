"""get_current_user / get_current_user_sse 改讀 httpOnly cookie 後的硬切換
規格測試（XSS audit TODO-8 方案 B）。

把「不再接受 Authorization header」這個決策寫成可執行的測試，而不只是
程式碼註解——特別是 cookie 與舊 header 同時存在時，header 必須被完全
忽略（見 tests/auth/test_get_current_user_cookie.py::test_stray_header_is_ignored_*）。
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.auth.dependencies import get_current_user, get_current_user_sse  # noqa: E402
from src.auth.jwt_handler import create_access_token  # noqa: E402

_PAYLOAD = {"sub": "507f1f77bcf86cd799439011", "email": "susan@example.com", "role": "user"}


class _FakeRequest:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


async def _dummy_db():
    return object()


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_valid_cookie_succeeds(self):
        token, _ = create_access_token(_PAYLOAD)
        user = await get_current_user(request=_FakeRequest(cookies={"access_token": token}), db=object())
        assert str(user["_id"]) == _PAYLOAD["sub"]
        assert user["email"] == _PAYLOAD["email"]

    @pytest.mark.asyncio
    async def test_missing_cookie_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=_FakeRequest(), db=object())
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_cookie_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=_FakeRequest(cookies={"access_token": "garbage.not.a.jwt"}), db=object())
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_stray_authorization_header_is_ignored_when_cookie_present(self):
        """硬切換規格：cookie 有效時，就算同時帶著（可能是舊快取的）
        Authorization header，也完全不影響結果——header 不會被讀取。"""
        token, _ = create_access_token(_PAYLOAD)
        request = _FakeRequest(
            cookies={"access_token": token},
            headers={"Authorization": "Bearer some-other-completely-different-token"},
        )
        user = await get_current_user(request=request, db=object())
        assert str(user["_id"]) == _PAYLOAD["sub"]

    @pytest.mark.asyncio
    async def test_authorization_header_alone_no_longer_works(self):
        """硬切換規格：只有 Authorization header、沒有 cookie，必須 401——
        這條規則的存在本身就是這次遷移的核心行為。"""
        token, _ = create_access_token(_PAYLOAD)
        request = _FakeRequest(headers={"Authorization": f"Bearer {token}"})
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=request, db=object())
        assert exc.value.status_code == 401


class TestGetCurrentUserSse:
    @pytest.mark.asyncio
    async def test_valid_cookie_succeeds(self):
        token, _ = create_access_token(_PAYLOAD)
        user = await get_current_user_sse(request=_FakeRequest(cookies={"access_token": token}), db=object())
        assert str(user["_id"]) == _PAYLOAD["sub"]

    @pytest.mark.asyncio
    async def test_missing_cookie_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_current_user_sse(request=_FakeRequest(), db=object())
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_query_token_no_longer_accepted(self):
        """回歸守衛：舊版靠 ?token= 查詢參數認證，這裡確認 get_current_user_sse
        的簽名已經沒有這個參數了——EventSource 現在完全靠 cookie 認證。"""
        import inspect
        sig = inspect.signature(get_current_user_sse)
        assert "token" not in sig.parameters, (
            "get_current_user_sse 不應該再有 token query 參數——"
            "SSE 認證應該完全改走 httpOnly cookie"
        )
