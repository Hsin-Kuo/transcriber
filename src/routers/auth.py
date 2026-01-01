"""認證路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from datetime import datetime, timedelta
import secrets
from ..models.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    RefreshTokenRequest,
    ResendVerificationRequest,
    UserResponse
)
from ..auth.password import hash_password, verify_password
from ..auth.jwt_handler import create_access_token, create_refresh_token, verify_token
from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..utils.audit_logger import get_audit_logger
from ..utils.email_service import get_email_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register")
async def register(
    user_data: UserRegister,
    db=Depends(get_database)
):
    """用戶註冊

    Args:
        user_data: 註冊資料（email, password）
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: Email 已被註冊或發送驗證郵件失敗
    """
    user_repo = UserRepository(db)
    email_service = get_email_service()

    # 檢查 Email 是否已存在
    if await user_repo.get_by_email(user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email 已被註冊"
        )

    # 生成驗證 token (使用 secrets 生成安全的隨機字符串)
    verification_token = secrets.token_urlsafe(32)
    verification_expires = datetime.utcnow() + timedelta(hours=24)

    # 建立新用戶 (未激活狀態)
    user = await user_repo.create({
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "role": "user",
        "is_active": False,  # 需要驗證 email 後才激活
        "email_verified": False,
        "verification_token": verification_token,
        "verification_expires": verification_expires,
        "quota": {
            "tier": "free",
            "max_transcriptions": 10,      # 免費版: 10 次/月
            "max_duration_minutes": 60,    # 免費版: 60 分鐘/月
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
            "last_reset": datetime.utcnow(),
            "total_transcriptions": 0,
            "total_duration_minutes": 0
        },
        "refresh_tokens": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    })

    # 發送驗證郵件
    email_sent = await email_service.send_verification_email(
        to_email=user_data.email,
        verification_token=verification_token
    )

    if not email_sent:
        # 如果郵件發送失敗，刪除剛創建的用戶
        await user_repo.delete(str(user["_id"]))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="發送驗證郵件失敗，請稍後再試"
        )

    return {
        "message": "註冊成功！請查看您的郵箱完成驗證",
        "email": user_data.email
    }


@router.get("/verify-email")
async def verify_email(
    token: str,
    db=Depends(get_database)
):
    """驗證 Email

    Args:
        token: 驗證 token (from URL query parameter)
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: Token 無效或已過期
    """
    user_repo = UserRepository(db)

    # 查找具有此 verification_token 的用戶
    user = await user_repo.get_by_verification_token(token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="驗證連結無效"
        )

    # 檢查 token 是否過期
    if user.get("verification_expires") and user["verification_expires"] < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="驗證連結已過期，請重新申請驗證郵件"
        )

    # 更新用戶狀態
    await user_repo.update(str(user["_id"]), {
        "is_active": True,
        "email_verified": True,
        "verification_token": None,  # 清除 token
        "verification_expires": None,
        "updated_at": datetime.utcnow()
    })

    return {
        "message": "Email 驗證成功！您現在可以登入了",
        "email": user["email"]
    }


@router.post("/resend-verification")
async def resend_verification_email(
    request: ResendVerificationRequest,
    db=Depends(get_database)
):
    """重新發送驗證郵件

    Args:
        request: 重新發送驗證郵件請求（包含 email）
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: Email 不存在、已驗證或發送失敗
    """
    user_repo = UserRepository(db)
    email_service = get_email_service()

    user = await user_repo.get_by_email(request.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="此 Email 尚未註冊"
        )

    if user.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此 Email 已完成驗證"
        )

    # 生成新的驗證 token
    verification_token = secrets.token_urlsafe(32)
    verification_expires = datetime.utcnow() + timedelta(hours=24)

    # 更新用戶的驗證 token
    await user_repo.update(str(user["_id"]), {
        "verification_token": verification_token,
        "verification_expires": verification_expires,
        "updated_at": datetime.utcnow()
    })

    # 發送驗證郵件
    email_sent = await email_service.send_verification_email(
        to_email=request.email,
        verification_token=verification_token
    )

    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="發送驗證郵件失敗，請稍後再試"
        )

    return {
        "message": "驗證郵件已重新發送，請查看您的郵箱",
        "email": request.email
    }


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    credentials: UserLogin,
    db=Depends(get_database)
):
    """用戶登入

    Args:
        request: FastAPI Request 對象
        credentials: 登入憑證（email, password）
        db: 資料庫實例

    Returns:
        Token 響應

    Raises:
        HTTPException: Email 或密碼錯誤、帳號已停用、Email 未驗證
    """
    audit_logger = get_audit_logger()
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(credentials.email)

    # 驗證用戶和密碼
    if not user or not verify_password(credentials.password, user["password_hash"]):
        # 記錄登入失敗
        await audit_logger.log_auth(
            request=request,
            action="login_failed",
            user_id=str(user["_id"]) if user else None,
            status_code=401,
            message=f"登入失敗: {credentials.email}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email 或密碼錯誤",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 檢查 Email 是否已驗證
    if not user.get("email_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="請先驗證您的 Email"
        )

    if not user.get("is_active"):
        # 記錄帳號停用嘗試登入
        await audit_logger.log_auth(
            request=request,
            action="login_disabled_account",
            user_id=str(user["_id"]),
            status_code=403,
            message="嘗試登入已停用帳號"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="帳號已被停用"
        )

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

    # 記錄成功登入
    await audit_logger.log_auth(
        request=request,
        action="login",
        user_id=str(user["_id"]),
        status_code=200,
        message="登入成功"
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db=Depends(get_database)
):
    """刷新 Access Token

    Args:
        request: Refresh Token 請求
        db: 資料庫實例

    Returns:
        新的 Token 響應

    Raises:
        HTTPException: Refresh Token 無效或已撤銷
    """
    token_data = verify_token(request.refresh_token, "refresh")
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的 Refresh Token"
        )

    # 驗證 Token 是否在資料庫中且未被撤銷
    user_repo = UserRepository(db)
    if not await user_repo.verify_refresh_token(token_data.user_id, request.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 已被撤銷或過期"
        )

    # 生成新 Access Token
    access_token = create_access_token({
        "sub": token_data.user_id,
        "email": token_data.email,
        "role": token_data.role
    })

    return {
        "access_token": access_token,
        "refresh_token": request.refresh_token,  # Refresh Token 保持不變
        "token_type": "bearer"
    }


@router.post("/logout")
async def logout(
    request: RefreshTokenRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """登出（撤銷 Refresh Token）

    Args:
        request: Refresh Token 請求
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        成功訊息
    """
    user_repo = UserRepository(db)
    await user_repo.revoke_refresh_token(str(current_user["_id"]), request.refresh_token)
    return {"message": "登出成功"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """獲取當前用戶資訊

    Args:
        current_user: 當前用戶（來自 JWT token）
        db: 資料庫實例

    Returns:
        用戶資訊
    """
    # 從資料庫獲取完整用戶資料（包含 quota, usage, created_at）
    # 這個端點只在登入時調用一次，不像輪詢那樣頻繁，所以可以查 DB
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))

    if not full_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    return UserResponse(
        id=str(full_user["_id"]),
        email=full_user["email"],
        role=full_user["role"],
        is_active=full_user["is_active"],
        quota=full_user["quota"],
        usage=full_user["usage"],
        created_at=full_user["created_at"].isoformat()
    )
