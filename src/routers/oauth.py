"""OAuth 第三方登入路由"""
import os
from fastapi import APIRouter, Depends, status, Response
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


class _BoundedTimeoutRequest(google_requests.Request):
    """google.auth Request 的 10s timeout 版本。

    原 google.auth.transport.requests.Request.__call__ 預設 timeout=120s，
    Google endpoint 偶有卡頓時會把 worker 阻塞兩分鐘。透過 subclass override
    __call__ 預設 timeout，所有 verify_oauth2_token 內部請求都受限。

    （舊版用 requests.Session().timeout = 10 是 no-op，Session 沒有
    timeout 屬性，timeout 只能 per-request 傳入。）
    """
    def __call__(self, url, method="GET", body=None, headers=None, timeout=10, **kwargs):
        return super().__call__(url, method, body, headers, timeout, **kwargs)

from ..utils.time_utils import get_utc_timestamp
from ..utils.config_loader import get_parameter
from ..models.auth import (
    GoogleAuthRequest,
    GoogleBindRequest,
    SetPasswordRequest,
    TokenResponse
)
from ..auth.password import hash_password
from ..auth.jwt_handler import create_access_token, create_refresh_token
from ..auth.cookies import set_refresh_cookie, set_access_cookie
from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..models.quota import QUOTA_TIERS, QuotaTier
from ..utils.api_errors import api_error
from ..utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["OAuth"])
log = get_logger(__name__)

# Google OAuth 設定（AWS 從 SSM 讀取，本地從環境變數）
GOOGLE_CLIENT_ID = get_parameter("/transcriber/google-client-id", fallback_env="GOOGLE_CLIENT_ID", default="")

if GOOGLE_CLIENT_ID:
    log.info("oauth.client_id.loaded")
else:
    log.warning("oauth.client_id.missing")


def verify_google_token(credential: str) -> dict:
    """驗證 Google ID Token

    Args:
        credential: Google ID Token

    Returns:
        用戶資訊 dict，包含 sub (Google ID), email, name, picture 等

    Raises:
        HTTPException: Token 無效
    """
    if not GOOGLE_CLIENT_ID:
        raise api_error(
            "OAUTH_NOT_CONFIGURED",
            "Google OAuth is not configured",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            _BoundedTimeoutRequest(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )

        # 驗證 issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Invalid issuer')

        return idinfo

    except ValueError as e:
        # 細節只寫 log，response 給通用訊息避免洩漏內部錯誤結構給 client
        log.warning("oauth.google_token.invalid", error=str(e))
        raise api_error(
            "OAUTH_TOKEN_INVALID",
            "Invalid Google token",
            status.HTTP_401_UNAUTHORIZED,
        )
    except Exception as e:
        log.warning("oauth.google_token.verify_error", error_type=type(e).__name__, error=str(e))
        raise api_error(
            "OAUTH_TOKEN_VERIFY_FAILED",
            "Google token verification failed",
            status.HTTP_401_UNAUTHORIZED,
        )


@router.post("/google", response_model=TokenResponse)
async def google_auth(
    request: GoogleAuthRequest,
    response: Response,
    db=Depends(get_database)
):
    """Google 登入/註冊

    流程：
    1. 驗證 Google Token
    2. 檢查是否已有綁定此 Google ID 的帳號
    3. 如有 → 登入
    4. 如無 → 建立新帳號

    Args:
        request: Google Auth 請求（包含 credential）
        db: 資料庫實例

    Returns:
        Token 響應
    """
    # 驗證 Google Token
    google_info = verify_google_token(request.credential)
    google_id = google_info['sub']
    email = google_info.get('email', '')

    if not email:
        raise api_error(
            "OAUTH_EMAIL_UNAVAILABLE",
            "Could not retrieve the email of the Google account",
            status.HTTP_400_BAD_REQUEST,
        )

    user_repo = UserRepository(db)

    # 1. 先檢查是否有綁定此 Google ID 的帳號
    user = await user_repo.get_by_google_id(google_id)

    if user:
        # 已有帳號，直接登入
        if not user.get("is_active"):
            raise api_error(
                "OAUTH_ACCOUNT_DISABLED",
                "Account has been disabled",
                status.HTTP_403_FORBIDDEN,
            )
    else:
        # 2. 檢查是否有同 email 的帳號（但未綁定 Google）
        existing_user = await user_repo.get_by_email(email)

        if existing_user:
            # 有同 email 帳號但未綁定 Google，不自動關聯
            # 用戶需要登入後手動綁定
            raise api_error(
                "OAUTH_EMAIL_EXISTS_UNLINKED",
                "An account with this email already exists; please sign in with your password and link Google in settings",
                status.HTTP_409_CONFLICT,
            )

        # 3. 建立新帳號
        now = get_utc_timestamp()
        user = await user_repo.create({
            "email": email,
            "password_hash": None,  # OAuth 用戶無密碼
            "google_id": google_id,
            "auth_providers": ["google"],
            "role": "user",
            "is_active": True,  # Google 已驗證 email
            "email_verified": True,
            "quota": {
                "tier": QuotaTier.FREE,
                **{k: v for k, v in QUOTA_TIERS[QuotaTier.FREE].items() if k not in ("name", "price")}
            },
            "usage": {
                "transcriptions": 0,
                "duration_minutes": 0,
                "ai_summaries": 0,
                "last_reset": now,
                "total_transcriptions": 0,
                "total_duration_minutes": 0,
                "total_ai_summaries": 0
            },
            "refresh_tokens": [],
            "created_at": now,
            "updated_at": now
        })

    # 生成 Token
    access_token, expires_at = create_access_token({
        "sub": str(user["_id"]),
        "email": user["email"],
        "role": user["role"]
    })
    refresh_token_value = create_refresh_token({
        "sub": str(user["_id"]),
        "email": user["email"],
        "role": user["role"]
    })

    # 存儲 Refresh Token
    await user_repo.save_refresh_token(str(user["_id"]), refresh_token_value)

    # httpOnly cookie 傳給 client；body 不再回 refresh_token
    set_refresh_cookie(response, refresh_token_value)
    set_access_cookie(response, access_token)

    return TokenResponse(token_type="bearer", expires_at=expires_at)


@router.post("/google/bind")
async def bind_google(
    request: GoogleBindRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """綁定 Google 帳號到現有帳號

    Args:
        request: 綁定請求（包含 Google credential）
        current_user: 當前登入用戶
        db: 資料庫實例

    Returns:
        成功訊息
    """
    # 驗證 Google Token
    google_info = verify_google_token(request.credential)
    google_id = google_info['sub']
    google_email = google_info.get('email', '')

    user_repo = UserRepository(db)

    # 檢查此 Google ID 是否已被其他帳號綁定
    existing = await user_repo.get_by_google_id(google_id)
    if existing:
        if str(existing["_id"]) == str(current_user["_id"]):
            raise api_error(
                "OAUTH_ALREADY_LINKED_SELF",
                "This Google account is already linked to your account",
                status.HTTP_400_BAD_REQUEST,
            )
        else:
            raise api_error(
                "OAUTH_ALREADY_LINKED_OTHER",
                "This Google account is already linked to another account",
                status.HTTP_409_CONFLICT,
            )

    # 取得用戶完整資料
    user = await user_repo.get_by_id(str(current_user["_id"]))
    if not user:
        raise api_error(
            "OAUTH_USER_NOT_FOUND",
            "User does not exist",
            status.HTTP_404_NOT_FOUND,
        )

    # 更新用戶資料
    auth_providers = user.get("auth_providers", [])
    if "password" not in auth_providers and user.get("password_hash"):
        auth_providers.append("password")
    if "google" not in auth_providers:
        auth_providers.append("google")

    await user_repo.update(str(user["_id"]), {
        "google_id": google_id,
        "auth_providers": auth_providers
    })

    return {
        "message": "已成功綁定 Google 帳號",
        "google_email": google_email
    }


@router.delete("/google/unbind")
async def unbind_google(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """解除綁定 Google 帳號

    注意：如果用戶沒有設定密碼，則不能解綁（否則無法登入）

    Args:
        current_user: 當前登入用戶
        db: 資料庫實例

    Returns:
        成功訊息
    """
    user_repo = UserRepository(db)

    # 取得用戶完整資料
    user = await user_repo.get_by_id(str(current_user["_id"]))
    if not user:
        raise api_error(
            "OAUTH_USER_NOT_FOUND",
            "User does not exist",
            status.HTTP_404_NOT_FOUND,
        )

    # 檢查是否有綁定 Google
    if not user.get("google_id"):
        raise api_error(
            "OAUTH_NOT_LINKED",
            "Google account is not linked yet",
            status.HTTP_400_BAD_REQUEST,
        )

    # 檢查是否有其他登入方式（密碼）
    if not user.get("password_hash"):
        raise api_error(
            "OAUTH_UNLINK_REQUIRES_PASSWORD",
            "Please set a password before unlinking, otherwise you will not be able to sign in",
            status.HTTP_400_BAD_REQUEST,
        )

    # 更新用戶資料
    auth_providers = user.get("auth_providers", [])
    if "google" in auth_providers:
        auth_providers.remove("google")

    await user_repo.update(str(user["_id"]), {
        "google_id": None,
        "auth_providers": auth_providers
    })

    return {"message": "已解除綁定 Google 帳號"}


@router.post("/set-password")
async def set_password(
    request: SetPasswordRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """設定密碼（給 OAuth 用戶首次設定密碼）

    Args:
        request: 設定密碼請求
        current_user: 當前登入用戶
        db: 資料庫實例

    Returns:
        成功訊息
    """
    import re
    user_repo = UserRepository(db)

    # 取得用戶完整資料
    user = await user_repo.get_by_id(str(current_user["_id"]))
    if not user:
        raise api_error(
            "OAUTH_USER_NOT_FOUND",
            "User does not exist",
            status.HTTP_404_NOT_FOUND,
        )

    # 檢查是否已有密碼
    if user.get("password_hash"):
        raise api_error(
            "OAUTH_PASSWORD_ALREADY_SET",
            "Password already set, please use the \"Change password\" feature",
            status.HTTP_400_BAD_REQUEST,
        )

    # 驗證密碼複雜度
    new_pwd = request.new_password
    if not re.search(r'[A-Z]', new_pwd):
        raise api_error(
            "OAUTH_PASSWORD_NO_UPPERCASE",
            "Password must contain at least one uppercase letter",
            status.HTTP_400_BAD_REQUEST,
        )
    if not re.search(r'[a-z]', new_pwd):
        raise api_error(
            "OAUTH_PASSWORD_NO_LOWERCASE",
            "Password must contain at least one lowercase letter",
            status.HTTP_400_BAD_REQUEST,
        )
    if not re.search(r'[0-9]', new_pwd):
        raise api_error(
            "OAUTH_PASSWORD_NO_DIGIT",
            "Password must contain at least one digit",
            status.HTTP_400_BAD_REQUEST,
        )

    # 設定密碼
    auth_providers = user.get("auth_providers", [])
    if "password" not in auth_providers:
        auth_providers.append("password")

    await user_repo.update(str(user["_id"]), {
        "password_hash": hash_password(request.new_password),
        "auth_providers": auth_providers
    })

    return {"message": "密碼設定成功"}
