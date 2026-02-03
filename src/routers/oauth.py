"""OAuth 第三方登入路由"""
import os
from fastapi import APIRouter, Depends, HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from ..utils.time_utils import get_utc_timestamp
from ..models.auth import (
    GoogleAuthRequest,
    GoogleBindRequest,
    SetPasswordRequest,
    TokenResponse
)
from ..auth.password import hash_password
from ..auth.jwt_handler import create_access_token, create_refresh_token
from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository

router = APIRouter(prefix="/auth", tags=["OAuth"])

# Google OAuth 設定
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# 啟動時印出設定狀態（除錯用）
if GOOGLE_CLIENT_ID:
    print(f"[OAuth] Google Client ID 已載入: {GOOGLE_CLIENT_ID[:20]}...")
else:
    print("[OAuth] 警告: GOOGLE_CLIENT_ID 未設定")


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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth 未設定"
        )

    try:
        idinfo = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10  # 允許 10 秒的時間誤差
        )

        # 驗證 issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Invalid issuer')

        return idinfo

    except ValueError as e:
        print(f"[OAuth] Google Token 驗證失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google Token 無效: {str(e)}"
        )
    except Exception as e:
        print(f"[OAuth] Google Token 驗證異常: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google Token 驗證失敗: {str(e)}"
        )


@router.post("/google", response_model=TokenResponse)
async def google_auth(
    request: GoogleAuthRequest,
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無法取得 Google 帳號的 Email"
        )

    user_repo = UserRepository(db)

    # 1. 先檢查是否有綁定此 Google ID 的帳號
    user = await user_repo.get_by_google_id(google_id)

    if user:
        # 已有帳號，直接登入
        if not user.get("is_active"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="帳號已被停用"
            )
    else:
        # 2. 檢查是否有同 email 的帳號（但未綁定 Google）
        existing_user = await user_repo.get_by_email(email)

        if existing_user:
            # 有同 email 帳號但未綁定 Google，不自動關聯
            # 用戶需要登入後手動綁定
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="此 Email 已有帳號，請使用密碼登入後在設定頁面綁定 Google"
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
                "tier": "free",
                "max_transcriptions": 10,
                "max_duration_minutes": 60,
                "max_concurrent_tasks": 1,
                "features": {
                    "speaker_diarization": False,
                    "punctuation": True,
                    "batch_operations": False
                }
            },
            "usage": {
                "transcriptions": 0,
                "duration_minutes": 0,
                "last_reset": now,
                "total_transcriptions": 0,
                "total_duration_minutes": 0
            },
            "refresh_tokens": [],
            "created_at": now,
            "updated_at": now
        })

    # 生成 Token
    access_token = create_access_token({
        "sub": str(user["_id"]),
        "email": user["email"],
        "role": user["role"]
    })
    refresh_token = create_refresh_token({
        "sub": str(user["_id"]),
        "email": user["email"]
    })

    # 存儲 Refresh Token
    await user_repo.save_refresh_token(str(user["_id"]), refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="此 Google 帳號已綁定到您的帳號"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="此 Google 帳號已綁定到其他帳號"
            )

    # 取得用戶完整資料
    user = await user_repo.get_by_id(str(current_user["_id"]))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 檢查是否有綁定 Google
    if not user.get("google_id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="尚未綁定 Google 帳號"
        )

    # 檢查是否有其他登入方式（密碼）
    if not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請先設定密碼後再解除綁定，否則將無法登入"
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 檢查是否已有密碼
    if user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已設定密碼，請使用「更改密碼」功能"
        )

    # 驗證密碼複雜度
    new_pwd = request.new_password
    if not re.search(r'[A-Z]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密碼必須包含至少一個大寫字母"
        )
    if not re.search(r'[a-z]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密碼必須包含至少一個小寫字母"
        )
    if not re.search(r'[0-9]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密碼必須包含至少一個數字"
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
