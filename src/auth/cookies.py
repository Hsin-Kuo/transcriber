"""Refresh token cookie 工具。

Refresh token 存於 httpOnly cookie，JavaScript 無法讀取，可抵禦 XSS
竊取 token 後的長期帳號接管。Access token 仍走 Authorization header（短壽命）。

Cookie 設定：
- HttpOnly：JS 無法讀
- Secure：僅 HTTPS（local 開發例外）
- SameSite=strict：跨站請求不送，防 CSRF
- Path=/auth：只在 /auth/* 端點送出，最小曝露面
- Max-Age：30 天，與 REFRESH_TOKEN_EXPIRE_DAYS 對齊
"""
import os

from fastapi import Response

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"
REFRESH_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天

# local 開發走 http，必須關閉 Secure 否則瀏覽器不送 cookie
_IS_LOCAL = os.getenv("DEPLOY_ENV", "local") == "local"


def set_refresh_cookie(response: Response, token: str) -> None:
    """寫入 refresh token cookie"""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_COOKIE_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=not _IS_LOCAL,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    """清除 refresh token cookie（登出時呼叫）"""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
    )
