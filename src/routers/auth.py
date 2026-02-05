"""認證路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from datetime import datetime, timedelta
import secrets
from ..utils.time_utils import get_utc_timestamp


# ============================================
# 忘記密碼 - 速率限制設定
# ============================================
FORGOT_PASSWORD_MAX_REQUESTS_PER_HOUR = 5   # 每 IP 每小時最多請求次數
FORGOT_PASSWORD_COOLDOWN_SECONDS = 300       # 同一 Email 冷卻時間（秒）
from ..models.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    RefreshTokenRequest,
    ResendVerificationRequest,
    ChangePasswordRequest,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest
)
from ..auth.password import hash_password, verify_password
from ..auth.jwt_handler import create_access_token, create_refresh_token, verify_token
from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.rate_limit_repo import RateLimitRepository
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
    now = get_utc_timestamp()
    verification_expires = now + (24 * 60 * 60)  # 24 小時後過期

    # 建立新用戶 (未激活狀態)
    user = await user_repo.create({
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "auth_providers": ["password"],
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
            "last_reset": now,
            "total_transcriptions": 0,
            "total_duration_minutes": 0
        },
        "refresh_tokens": [],
        "created_at": now,
        "updated_at": now
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
    verification_expires = user.get("verification_expires")
    if verification_expires:
        # 處理舊格式（datetime）和新格式（timestamp）
        if hasattr(verification_expires, 'timestamp'):
            verification_expires = int(verification_expires.timestamp())
        if verification_expires < get_utc_timestamp():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="驗證連結已過期，請重新申請驗證郵件"
            )

    # 更新用戶狀態
    await user_repo.update(str(user["_id"]), {
        "is_active": True,
        "email_verified": True,
        "verification_token": None,  # 清除 token
        "verification_expires": None
        # updated_at 由 user_repo.update() 自動設置
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
    verification_expires = get_utc_timestamp() + (24 * 60 * 60)  # 24 小時後過期

    # 更新用戶的驗證 token
    await user_repo.update(str(user["_id"]), {
        "verification_token": verification_token,
        "verification_expires": verification_expires
        # updated_at 由 user_repo.update() 自動設置
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
    http_request: Request,
    request: RefreshTokenRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """登出（撤銷 Refresh Token）

    Args:
        http_request: HTTP Request 對象
        request: Refresh Token 請求
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        成功訊息
    """
    user_repo = UserRepository(db)
    await user_repo.revoke_refresh_token(str(current_user["_id"]), request.refresh_token)

    # 記錄登出
    audit_logger = get_audit_logger()
    await audit_logger.log_auth(
        request=http_request,
        action="logout",
        user_id=str(current_user["_id"]),
        status_code=200,
        message="登出成功"
    )

    return {"message": "登出成功"}


@router.post("/change-password")
async def change_password(
    http_request: Request,
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """更改密碼

    Args:
        http_request: HTTP Request 對象
        request: 更改密碼請求（current_password, new_password）
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: 目前密碼錯誤或新密碼不符合要求
    """
    user_repo = UserRepository(db)

    # 從資料庫獲取完整用戶資料（包含 password_hash）
    user = await user_repo.get_by_id(str(current_user["_id"]))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 驗證目前密碼
    if not verify_password(request.current_password, user["password_hash"]):
        # 記錄密碼變更失敗
        audit_logger = get_audit_logger()
        await audit_logger.log_auth(
            request=http_request,
            action="change_password_failed",
            user_id=str(current_user["_id"]),
            status_code=400,
            message="密碼變更失敗：目前密碼錯誤"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="目前密碼錯誤"
        )

    # 檢查新密碼不能與舊密碼相同
    if request.current_password == request.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼不能與目前密碼相同"
        )

    # 驗證密碼複雜度（與註冊時相同）
    import re
    new_pwd = request.new_password
    if not re.search(r'[A-Z]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼必須包含至少一個大寫字母"
        )
    if not re.search(r'[a-z]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼必須包含至少一個小寫字母"
        )
    if not re.search(r'[0-9]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼必須包含至少一個數字"
        )

    # 更新密碼
    new_password_hash = hash_password(request.new_password)
    await user_repo.update(str(current_user["_id"]), {
        "password_hash": new_password_hash
    })

    # 記錄密碼變更成功
    audit_logger = get_audit_logger()
    await audit_logger.log_auth(
        request=http_request,
        action="change_password",
        user_id=str(current_user["_id"]),
        status_code=200,
        message="密碼變更成功"
    )

    return {"message": "密碼已更新成功"}


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

    # 處理 created_at（可能是 datetime 或 int）
    created_at = full_user["created_at"]
    if hasattr(created_at, 'timestamp'):
        # datetime 對象，轉換為 timestamp
        created_at = int(created_at.timestamp())

    # 處理 usage.last_reset（可能是 datetime 或 int）
    usage = full_user.get("usage", {})
    if usage and "last_reset" in usage:
        last_reset = usage["last_reset"]
        if hasattr(last_reset, 'timestamp'):
            usage = {**usage, "last_reset": int(last_reset.timestamp())}

    # 計算 auth_providers
    auth_providers = full_user.get("auth_providers", [])
    # 相容舊帳號：如果沒有 auth_providers 但有密碼，則為 password
    if not auth_providers and full_user.get("password_hash"):
        auth_providers = ["password"]

    return UserResponse(
        id=str(full_user["_id"]),
        email=full_user["email"],
        role=full_user["role"],
        is_active=full_user["is_active"],
        quota=full_user["quota"],
        usage=usage,
        created_at=created_at,
        auth_providers=auth_providers
    )


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
    db=Depends(get_database)
):
    """發送密碼重設郵件

    Args:
        request: 忘記密碼請求（包含 email）
        http_request: HTTP 請求物件（用於取得 IP）
        db: 資料庫實例

    Returns:
        成功訊息（無論 email 是否存在都返回相同訊息，防止 email 枚舉攻擊）

    Raises:
        HTTPException: 超過速率限制
    """
    # 取得客戶端 IP（支援反向代理）
    client_ip = http_request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = http_request.client.host if http_request.client else "unknown"

    user_repo = UserRepository(db)
    rate_limit_repo = RateLimitRepository(db)
    email_service = get_email_service()

    # 檢查 IP 速率限制（使用 MongoDB 存儲，支援多實例）
    ip_allowed, ip_remaining = await rate_limit_repo.check_rate_limit(
        limit_type="forgot_password_ip",
        key=client_ip,
        max_requests=FORGOT_PASSWORD_MAX_REQUESTS_PER_HOUR,
        window_seconds=3600  # 1 小時
    )
    if not ip_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="請求過於頻繁，請稍後再試"
        )

    user = await user_repo.get_by_email(request.email)

    # 無論 email 是否存在，都返回相同訊息（防止 email 枚舉攻擊）
    success_message = {
        "message": "如果該 Email 已註冊，您將會收到密碼重設郵件",
        "email": request.email
    }

    # 記錄此 IP 的請求（無論 email 是否存在都記錄，防止探測）
    await rate_limit_repo.record_request(
        limit_type="forgot_password_ip",
        key=client_ip,
        ttl_seconds=3600
    )

    if not user:
        return success_message

    # 檢查帳號是否已激活
    if not user.get("email_verified"):
        return success_message

    # 檢查 Email 冷卻時間
    last_request = user.get("password_reset_requested_at")
    cooldown_allowed, cooldown_remaining = await rate_limit_repo.check_cooldown(
        last_request_timestamp=last_request,
        cooldown_seconds=FORGOT_PASSWORD_COOLDOWN_SECONDS
    )
    if not cooldown_allowed:
        remaining_minutes = (cooldown_remaining + 59) // 60  # 向上取整
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"請等待 {remaining_minutes} 分鐘後再試"
        )

    # 生成密碼重設 token
    reset_token = secrets.token_urlsafe(32)
    now = get_utc_timestamp()
    reset_expires = now + (60 * 60)  # 1 小時後過期

    # 更新用戶的重設 token 和請求時間
    await user_repo.update(str(user["_id"]), {
        "password_reset_token": reset_token,
        "password_reset_expires": reset_expires,
        "password_reset_requested_at": now
    })

    # 發送密碼重設郵件
    await email_service.send_password_reset_email(
        to_email=request.email,
        reset_token=reset_token
    )

    # 記錄忘記密碼請求
    audit_logger = get_audit_logger()
    await audit_logger.log_auth(
        request=http_request,
        action="forgot_password",
        user_id=str(user["_id"]),
        status_code=200,
        message=f"發送密碼重設郵件：{request.email}"
    )

    return success_message


@router.post("/reset-password")
async def reset_password(
    http_request: Request,
    request: ResetPasswordRequest,
    db=Depends(get_database)
):
    """重設密碼

    Args:
        http_request: HTTP Request 對象
        request: 重設密碼請求（包含 token 和新密碼）
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: Token 無效、已過期或密碼不符合要求
    """
    import re
    user_repo = UserRepository(db)

    # 查找具有此重設 token 的用戶
    user = await user_repo.get_by_password_reset_token(request.token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="重設連結無效或已過期"
        )

    # 檢查 token 是否過期
    reset_expires = user.get("password_reset_expires")
    if reset_expires:
        if hasattr(reset_expires, 'timestamp'):
            reset_expires = int(reset_expires.timestamp())
        if reset_expires < get_utc_timestamp():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="重設連結已過期，請重新申請"
            )

    # 驗證密碼複雜度
    new_pwd = request.new_password
    if not re.search(r'[A-Z]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼必須包含至少一個大寫字母"
        )
    if not re.search(r'[a-z]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼必須包含至少一個小寫字母"
        )
    if not re.search(r'[0-9]', new_pwd):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼必須包含至少一個數字"
        )

    # 更新密碼並清除重設 token 和冷卻記錄
    new_password_hash = hash_password(request.new_password)
    await user_repo.update(str(user["_id"]), {
        "password_hash": new_password_hash,
        "password_reset_token": None,
        "password_reset_expires": None,
        "password_reset_requested_at": None
    })

    # 記錄密碼重設成功
    audit_logger = get_audit_logger()
    await audit_logger.log_auth(
        request=http_request,
        action="reset_password",
        user_id=str(user["_id"]),
        status_code=200,
        message=f"密碼重設成功：{user.get('email')}"
    )

    return {"message": "密碼已重設成功，請使用新密碼登入"}
