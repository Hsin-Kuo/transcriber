"""Access/Refresh token cookie 工具。

兩者皆存於 httpOnly cookie，JavaScript 無法讀取，可抵禦 XSS 竊取 token
後的帳號接管（access token 是即時操作，refresh token 是長期接管）。

Cookie 設定共同點：
- HttpOnly：JS 無法讀
- Secure：僅 HTTPS（local 開發例外）
- SameSite=strict：跨站請求不送，防 CSRF

差異：
- refresh_token：Path=/auth（只在 /auth/* 端點送出，最小曝露面），
  Max-Age 30 天。
- access_token：Path=/（每個 API 呼叫都要帶，天生無法縮小曝露面——
  這不是新風險，access token 本來就得對每個呼叫可用，只是換成瀏覽器
  負責夾帶而非 JS 手動加 header），Max-Age 對齊
  ACCESS_TOKEN_EXPIRE_MINUTES。
"""
import os

from fastapi import Response

from .jwt_handler import ACCESS_TOKEN_EXPIRE_MINUTES

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"
REFRESH_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天

ACCESS_COOKIE_NAME = "access_token"
ACCESS_COOKIE_PATH = "/"
ACCESS_COOKIE_MAX_AGE = ACCESS_TOKEN_EXPIRE_MINUTES * 60

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


def set_access_cookie(response: Response, token: str) -> None:
    """寫入 access token cookie"""
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        max_age=ACCESS_COOKIE_MAX_AGE,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=not _IS_LOCAL,
        samesite="strict",
    )


def clear_access_cookie(response: Response) -> None:
    """清除 access token cookie（登出時呼叫）"""
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path=ACCESS_COOKIE_PATH,
    )
