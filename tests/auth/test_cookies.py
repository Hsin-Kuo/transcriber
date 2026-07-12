"""refresh/access token cookie helper 測試（B3 + access token httpOnly 遷移）。"""
import os
import sys
from pathlib import Path

# 設一個有效的 JWT_SECRET_KEY 讓 jwt_handler import 不炸
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import importlib  # noqa: E402

from fastapi import Response  # noqa: E402

from src.auth import cookies as cookies_module  # noqa: E402


def _reload_cookies(deploy_env: str):
    """切換 DEPLOY_ENV 並重新載入 cookies module，讓 _IS_LOCAL 重新求值。"""
    os.environ["DEPLOY_ENV"] = deploy_env
    importlib.reload(cookies_module)
    return cookies_module


def _get_set_cookie_header(response: Response) -> str:
    headers = response.raw_headers
    for key, value in headers:
        if key.lower() == b"set-cookie":
            return value.decode()
    raise AssertionError("未發現 Set-Cookie header")


class TestSetRefreshCookie:
    def test_production_cookie_has_secure(self):
        mod = _reload_cookies("aws")
        response = Response()
        mod.set_refresh_cookie(response, "fake.jwt.token")
        header = _get_set_cookie_header(response)

        assert "refresh_token=fake.jwt.token" in header
        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=strict" in header
        assert "Path=/auth" in header
        assert "Max-Age=2592000" in header  # 30 天

    def test_local_cookie_omits_secure(self):
        mod = _reload_cookies("local")
        response = Response()
        mod.set_refresh_cookie(response, "fake.jwt.token")
        header = _get_set_cookie_header(response)

        assert "HttpOnly" in header
        assert "Secure" not in header  # 本地走 http
        assert "SameSite=strict" in header
        assert "Path=/auth" in header


class TestClearRefreshCookie:
    def test_clear_sets_empty_value(self):
        mod = _reload_cookies("aws")
        response = Response()
        mod.clear_refresh_cookie(response)
        header = _get_set_cookie_header(response)

        # FastAPI 的 delete_cookie 會 set Max-Age=0
        assert "refresh_token=" in header
        assert "Path=/auth" in header
        # 過期時間應該是 1970 或 Max-Age=0
        assert "Max-Age=0" in header or "expires=Thu, 01 Jan 1970" in header.lower()


class TestSetAccessCookie:
    def test_production_cookie_has_secure(self):
        mod = _reload_cookies("aws")
        response = Response()
        mod.set_access_cookie(response, "fake.jwt.token")
        header = _get_set_cookie_header(response)

        assert "access_token=fake.jwt.token" in header
        assert "HttpOnly" in header
        assert "Secure" in header
        assert "SameSite=strict" in header
        # Path=/（不是 /auth）——access token 每個 API 呼叫都要帶，跟
        # refresh token 刻意縮到 /auth 的曝露面不同，這個差異值得專門斷言，
        # 避免未來重構時複製貼上錯成 /auth。
        assert "Path=/" in header
        assert "Path=/auth" not in header
        assert "Max-Age=900" in header  # 15 分鐘 = ACCESS_TOKEN_EXPIRE_MINUTES 預設值

    def test_local_cookie_omits_secure(self):
        mod = _reload_cookies("local")
        response = Response()
        mod.set_access_cookie(response, "fake.jwt.token")
        header = _get_set_cookie_header(response)

        assert "HttpOnly" in header
        assert "Secure" not in header
        assert "SameSite=strict" in header
        assert "Path=/" in header


class TestClearAccessCookie:
    def test_clear_sets_empty_value(self):
        mod = _reload_cookies("aws")
        response = Response()
        mod.clear_access_cookie(response)
        header = _get_set_cookie_header(response)

        assert "access_token=" in header
        assert "Path=/" in header
        assert "Max-Age=0" in header or "expires=Thu, 01 Jan 1970" in header.lower()
