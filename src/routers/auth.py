"""認證路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from datetime import datetime, timedelta
from ..utils.time_utils import get_utc_timestamp
from ..auth.cookies import (
    REFRESH_COOKIE_NAME,
    set_refresh_cookie,
    clear_refresh_cookie,
    set_access_cookie,
    clear_access_cookie,
)


# ============================================
# 登入 - 速率限制設定
# ============================================
LOGIN_MAX_ATTEMPTS_PER_IP = 20              # 每 IP 每 15 分鐘最多嘗試次數
LOGIN_MAX_ATTEMPTS_PER_EMAIL = 5            # 每 Email 每 15 分鐘最多嘗試次數
LOGIN_RATE_LIMIT_WINDOW = 900               # 15 分鐘（秒）

# ============================================
# 忘記密碼 - 速率限制設定
# ============================================
FORGOT_PASSWORD_MAX_REQUESTS_PER_HOUR = 5   # 每 IP 每小時最多請求次數
FORGOT_PASSWORD_COOLDOWN_SECONDS = 300       # 同一 Email 冷卻時間（秒）

# ============================================
# 註冊 - 速率限制設定
# ============================================
REGISTER_MAX_ATTEMPTS_PER_IP = 5            # 每 IP 每小時最多註冊嘗試次數
REGISTER_MAX_ATTEMPTS_PER_EMAIL = 3         # 每 Email 每小時最多註冊嘗試次數
REGISTER_RATE_LIMIT_WINDOW = 3600           # 1 小時（秒）

# ============================================
# 重發驗證信 - 速率限制設定
# ============================================
RESEND_VERIFICATION_MAX_PER_IP = 5          # 每 IP 每小時最多重發次數
RESEND_VERIFICATION_MAX_PER_EMAIL = 3       # 每 Email 每小時最多重發次數
RESEND_VERIFICATION_COOLDOWN_SECONDS = 60   # 同 Email 兩次重發最小間隔

# ============================================
# Registration status polling - 速率限制
# ============================================
REG_STATUS_MAX_PER_IP = 90                  # 每 IP 每分鐘最多 poll 次數（legit 用戶 ~20）
REG_STATUS_WINDOW = 60

ABANDON_REGISTRATION_MAX_PER_IP = 10        # 每 IP 每小時最多放棄註冊次數
ABANDON_REGISTRATION_WINDOW = 3600
from ..models.auth import (
    MAX_EMAIL_LENGTH,
    UserRegister,
    UserLogin,
    TokenResponse,
    ResendVerificationRequest,
    VerifyEmailRequest,
    AbandonRegistrationRequest,
    ChangePasswordRequest,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UpdatePreferencesRequest,
    DeleteAccountRequest
)
from ..auth.password import hash_password, verify_password
from ..auth.jwt_handler import create_access_token, create_refresh_token, verify_token
from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.rate_limit_repo import RateLimitRepository
from ..utils.audit_logger import get_audit_logger
from ..utils.email_service import get_email_service
from ..services.credential_flow import (
    build_credential_flow,
    CredentialIntent,
    CredentialPurpose,
    CredentialCooldown,
    CredentialTokenInvalid,
    CredentialTokenExpired,
    WeakPassword,
    SendVerification,
    SendAccountExists,
    SendPasswordReset,
)
from ..utils.privacy import mask_email
from ..utils.api_errors import api_error
from ..models.quota import QUOTA_TIERS, QuotaTier

from ..utils.logger import get_logger

router = APIRouter(prefix="/auth", tags=["Authentication"])
log = get_logger(__name__)


# ============================================
# CredentialFlow edge adapters
# ============================================
# CredentialFlow 決定「寄哪封信 / 不寄」，edge 負責真的呼叫 email_service。
# 詳見 CONTEXT.md「認證與憑證」。

async def _dispatch_credential_email(email_service, instruction) -> bool:
    """執行 CredentialFlow 回傳的 EmailInstruction（None 視為成功，不寄）。"""
    if instruction is None:
        return True
    if isinstance(instruction, SendVerification):
        return await email_service.send_verification_email(
            to_email=instruction.to, verification_token=instruction.token
        )
    if isinstance(instruction, SendAccountExists):
        return await email_service.send_account_exists_email(to_email=instruction.to)
    if isinstance(instruction, SendPasswordReset):
        return await email_service.send_password_reset_email(
            to_email=instruction.to, reset_token=instruction.token
        )
    return True


async def _log_credential_audit(audit_logger, request, audit) -> None:
    if audit is None:
        return
    await audit_logger.log_auth(
        request=request,
        action=audit.action,
        user_id=audit.user_id,
        status_code=audit.status_code,
        message=audit.message,
    )


@router.post("/register")
async def register(
    user_data: UserRegister,
    request: Request,
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
    rate_limit_repo = RateLimitRepository(db)
    email_service = get_email_service()
    audit_logger = get_audit_logger()

    # --- 速率限制（在任何 DB 寫入 / 寄信之前） ---
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    normalized_email = user_data.email.strip().lower()

    ip_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="register_ip",
        key=client_ip,
        max_requests=REGISTER_MAX_ATTEMPTS_PER_IP,
        window_seconds=REGISTER_RATE_LIMIT_WINDOW,
    )
    if not ip_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many registration requests, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    email_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="register_email",
        key=normalized_email,
        max_requests=REGISTER_MAX_ATTEMPTS_PER_EMAIL,
        window_seconds=REGISTER_RATE_LIMIT_WINDOW,
    )
    if not email_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many registration requests, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # 不論 email 是否存在都記錄 → 避免「rate-limit 觸發行為」洩漏帳號是否存在
    await rate_limit_repo.record_request(
        limit_type="register_ip", key=client_ip, ttl_seconds=REGISTER_RATE_LIMIT_WINDOW
    )
    await rate_limit_repo.record_request(
        limit_type="register_email", key=normalized_email, ttl_seconds=REGISTER_RATE_LIMIT_WINDOW
    )

    # 委派 CredentialFlow：決定建帳號 / 重簽 / account-exists + 寄哪封信。
    # 對外回應由 outcome 統一給出（unknown 與 duplicate 不可區分，防 enumeration）。
    flow = build_credential_flow(db)
    outcome = await flow.issue(
        CredentialIntent.REGISTER, user_data.email, password=user_data.password
    )
    email_sent = await _dispatch_credential_email(email_service, outcome.email)

    # 新用戶驗證信寄送失敗 → 降級訊息（保留 inactive user，引導重發）。
    # 寄信失敗通常 transient（Resend 5xx / SMTP timeout）；不砍 user，使用者可走
    # /auth/resend-verification。duplicate 路徑沿用舊行為，不因寄信失敗改變對外回應。
    if not email_sent and outcome.audit and outcome.audit.action == "register":
        await audit_logger.log_auth(
            request=request, action="register_email_failed",
            user_id=outcome.audit.user_id, status_code=200,
            message=f"註冊但驗證信寄送失敗: {user_data.email}",
        )
        return {
            "message": "帳號已建立，但驗證信寄送發生問題。請稍後使用「重新發送驗證信」。",
            "email": user_data.email,
            "email_sent": False,
        }

    await _log_credential_audit(audit_logger, request, outcome.audit)
    return outcome.response


@router.get("/verify-email")
async def verify_email_preflight(
    token: str,
    db=Depends(get_database)
):
    """預檢 token 是否有效（**不消耗 token、不寫 DB**）。

    這個 endpoint 給前端用來在「點此完成驗證」按鈕渲染前確認 token 仍有效。
    真正的驗證動作要走 POST /verify-email — 避免 Outlook Safe Links /
    企業 mail gateway / 連結預掃 bot 自動 GET 就把 token 燒掉。

    Args:
        token: 驗證 token (from URL query parameter)
        db: 資料庫實例

    Returns:
        {"email": ..., "expires_at": ...}

    Raises:
        HTTPException: 400 token 無效 / 已驗證；410 token 已過期
    """
    flow = build_credential_flow(db)
    try:
        result = await flow.preflight(CredentialPurpose.VERIFY_EMAIL, token)
    except CredentialTokenInvalid as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except CredentialTokenExpired as e:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))

    return {
        "email": result.email,
        "expires_at": result.expires_at,
    }


@router.post("/verify-email")
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db=Depends(get_database)
):
    """完成 Email 驗證（不自動登入）。

    必須由使用者明確點擊前端按鈕觸發 → 防 link-preview bot 預掃消耗 token。
    驗證成功後不發 token、不寫 refresh cookie，避免覆蓋瀏覽器內其他已登入的
    session（refresh cookie 為 domain 共用一份）；改由使用者自行登入。
    """
    audit_logger = get_audit_logger()
    flow = build_credential_flow(db)
    try:
        outcome = await flow.consume(CredentialPurpose.VERIFY_EMAIL, payload.token)
    except CredentialTokenInvalid as e:
        await audit_logger.log_auth(
            request=request, action="verify_email_invalid", user_id=None,
            status_code=400, message=str(e),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except CredentialTokenExpired as e:
        await audit_logger.log_auth(
            request=request, action="verify_email_expired", user_id=e.user_id,
            status_code=410, message=str(e),
        )
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(e))

    await _log_credential_audit(audit_logger, request, outcome.audit)
    return outcome.response


@router.post("/resend-verification")
async def resend_verification_email(
    request: ResendVerificationRequest,
    http_request: Request,
    db=Depends(get_database)
):
    """重新發送驗證郵件

    Args:
        request: 重新發送驗證郵件請求（包含 email）
        http_request: HTTP Request（用於取得 IP 做速率限制）
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: Email 不存在、已驗證、超過速率限制或發送失敗
    """
    rate_limit_repo = RateLimitRepository(db)
    email_service = get_email_service()

    # --- 速率限制（在 DB 查詢 / 寄信之前） ---
    client_ip = http_request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = http_request.client.host if http_request.client else "unknown"
    normalized_email = request.email.strip().lower()

    ip_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="resend_verification_ip",
        key=client_ip,
        max_requests=RESEND_VERIFICATION_MAX_PER_IP,
        window_seconds=REGISTER_RATE_LIMIT_WINDOW,
    )
    if not ip_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many requests, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # 同 email 60s 內只能重發 1 次
    cooldown_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="resend_verification_cooldown",
        key=normalized_email,
        max_requests=1,
        window_seconds=RESEND_VERIFICATION_COOLDOWN_SECONDS,
    )
    if not cooldown_allowed:
        raise api_error(
            "AUTH_RESEND_COOLDOWN",
            "Please wait {seconds} seconds before resending",
            status.HTTP_429_TOO_MANY_REQUESTS,
            seconds=RESEND_VERIFICATION_COOLDOWN_SECONDS,
        )

    # 同 email 每小時上限
    email_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="resend_verification_email",
        key=normalized_email,
        max_requests=RESEND_VERIFICATION_MAX_PER_EMAIL,
        window_seconds=REGISTER_RATE_LIMIT_WINDOW,
    )
    if not email_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many resend attempts, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # 不論 email 是否存在都記錄 → 避免 rate-limit 行為洩漏帳號是否存在
    await rate_limit_repo.record_request(
        limit_type="resend_verification_ip",
        key=client_ip,
        ttl_seconds=REGISTER_RATE_LIMIT_WINDOW,
    )
    await rate_limit_repo.record_request(
        limit_type="resend_verification_cooldown",
        key=normalized_email,
        ttl_seconds=RESEND_VERIFICATION_COOLDOWN_SECONDS,
    )
    await rate_limit_repo.record_request(
        limit_type="resend_verification_email",
        key=normalized_email,
        ttl_seconds=REGISTER_RATE_LIMIT_WINDOW,
    )

    # 委派 CredentialFlow：unknown / verified / bounced 一律 silent（email=None），
    # 僅未驗證且未 bounce 才回 SendVerification。對外訊息統一防 enumeration。
    flow = build_credential_flow(db)
    outcome = await flow.issue(CredentialIntent.RESEND, request.email)
    if outcome.email is not None:
        email_sent = await _dispatch_credential_email(email_service, outcome.email)
        if not email_sent:
            # 寄信失敗（Resend transient 5xx 等）仍回 silent success — 不洩漏 user 存在。
            log.warning("auth.resend_verification.send_failed", email=mask_email(request.email))
    return outcome.response


@router.get("/registration-status")
async def registration_status(
    email: str,
    request: Request,
    db=Depends(get_database)
):
    """供「請查信」中間頁 poll：回報指定 email 的註冊驗證狀態。

    用於偵測 Resend webhook 標記的 bounce / complaint，讓使用者可以即時
    重新選 email。為防 enumeration，未知 email、格式錯誤 email 都與
    pending 同回應（不用 EmailStr 是為了避免 422 vs 200 變成「該字串是
    否為合法 email 格式」的部分 oracle）。

    Returns:
        {"status": "pending" | "verified" | "bounced" | "complained"}

    Raises:
        HTTPException: 429 超過 rate limit
    """
    rate_limit_repo = RateLimitRepository(db)
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    ip_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="registration_status_ip",
        key=client_ip,
        max_requests=REG_STATUS_MAX_PER_IP,
        window_seconds=REG_STATUS_WINDOW,
    )
    if not ip_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many requests, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    await rate_limit_repo.record_request(
        limit_type="registration_status_ip",
        key=client_ip,
        ttl_seconds=REG_STATUS_WINDOW,
    )

    # 簡易 sanity 檢查：完全不像 email 直接回 pending（不 422）以維持
    # enumeration 一致性。實際 email 是否合法由 DB lookup 命中與否決定。
    # 含控制字元也視同非法格式。
    if (
        "@" not in email
        or len(email) > MAX_EMAIL_LENGTH
        or any(ch in email for ch in "\r\n\t\0")
    ):
        return {"status": "pending"}

    # 直接以原樣 lookup（與 register 流程儲存的 email 格式一致 — pydantic
    # EmailStr 只 lowercase domain，保留 localpart 大小寫）
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(email)

    # 未知 email → 偽裝成 pending（防 enumeration）
    if not user:
        return {"status": "pending"}

    # 已驗證的 user 也回 pending — 否則此 endpoint 可被未認證攻擊者用來
    # enumerate「哪些 email 已是 SoundLite 已驗證用戶」。代價：cross-tab
    # 場景下另一 tab 完成驗證後本 tab 無法自動跳轉（保留人工 navigate）。
    if user.get("email_verified"):
        return {"status": "pending"}

    if user.get("email_bounced"):
        # bounced/complained 仍洩漏「該 email 有未驗證註冊」— 但這個資訊在
        # register flow 也已能取得（用同 email 嘗試註冊會 silent return 200），
        # 不算新增洩漏。對使用者體驗（典型 typo case）價值很高。
        event = user.get("email_bounce_event", "bounced")
        return {"status": event}

    return {"status": "pending"}


@router.post("/abandon-registration")
async def abandon_registration(
    payload: AbandonRegistrationRequest,
    request: Request,
    db=Depends(get_database)
):
    """放棄已 bounce 的未驗證註冊 — 刪除 user record 讓使用者可換 email 重來。

    安全條件：只有 (未驗證 AND email_bounced) 的 user 會被刪除。已驗證帳號
    永遠不會經此路徑刪除 — 真實用戶不會誤刪。

    為防 enumeration，無論 user 存在與否、是否符合刪除條件，一律回 200。
    """
    rate_limit_repo = RateLimitRepository(db)
    audit_logger = get_audit_logger()
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    ip_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="abandon_registration_ip",
        key=client_ip,
        max_requests=ABANDON_REGISTRATION_MAX_PER_IP,
        window_seconds=ABANDON_REGISTRATION_WINDOW,
    )
    if not ip_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many requests, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    await rate_limit_repo.record_request(
        limit_type="abandon_registration_ip",
        key=client_ip,
        ttl_seconds=ABANDON_REGISTRATION_WINDOW,
    )

    # 格式 sanity（與 registration-status 一致），不合法直接 200 不查 DB。
    # 同時擋掉含控制字元（\n / \r / \t 等）的 email — 雖然 production 用 JSON
    # logger 不會 log injection，但 audit_logs DB 仍儲存 raw 字串，避免之後
    # admin UI render 出怪東西。
    if (
        "@" not in payload.email
        or len(payload.email) > MAX_EMAIL_LENGTH
        or any(ch in payload.email for ch in "\r\n\t\0")
    ):
        return {"status": "ok"}

    # lookup 用原樣 email（與 register 寫入時一致）
    user_repo = UserRepository(db)
    user = await user_repo.get_by_email(payload.email)

    deleted = False
    # 安全約束：只有「未驗證 AND 已 bounced」的 user 會被刪除。
    # 已驗證帳號永不經此路徑刪除 — 即使未來重構也要保留這個約束
    # （請保留 `not user.get("email_verified")` 條件）。
    if (
        user
        and not user.get("email_verified")
        and user.get("email_bounced")
    ):
        deleted = await user_repo.delete(str(user["_id"]))
        if deleted:
            await audit_logger.log_auth(
                request=request,
                action="abandon_registration",
                user_id=str(user["_id"]),
                status_code=200,
                message=f"放棄已 bounce 的註冊: {payload.email}"
            )
            # rate-limit key 用 normalize 過的 email（與 register 階段一致）
            rate_key_email = payload.email.strip().lower()
            await rate_limit_repo.clear_records("register_email", rate_key_email)
            await rate_limit_repo.clear_records("resend_verification_email", rate_key_email)
            await rate_limit_repo.clear_records("resend_verification_cooldown", rate_key_email)
            # 也清掉該 IP 的 register 計數 — 用戶誠實 abandon 不該算 failed attempt，
            # 否則連續 typo 兩三次後 IP 會被擋住無法以正確 email 重來
            await rate_limit_repo.clear_records("register_ip", client_ip)

    return {"status": "ok"}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    credentials: UserLogin,
    db=Depends(get_database)
):
    """用戶登入。

    Refresh token 以 httpOnly cookie 寫入；response body 只回 access_token。
    """
    audit_logger = get_audit_logger()
    user_repo = UserRepository(db)
    rate_limit_repo = RateLimitRepository(db)

    # --- 速率限制（在驗證密碼之前） ---
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"

    ip_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="login_ip",
        key=client_ip,
        max_requests=LOGIN_MAX_ATTEMPTS_PER_IP,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW
    )
    if not ip_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many login attempts, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    normalized_email = credentials.email.strip().lower()
    email_allowed, _ = await rate_limit_repo.check_rate_limit(
        limit_type="login_email",
        key=normalized_email,
        max_requests=LOGIN_MAX_ATTEMPTS_PER_EMAIL,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW
    )
    if not email_allowed:
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many login attempts, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # --- 驗證憑證 ---
    user = await user_repo.get_by_email(credentials.email)

    if not user or not verify_password(credentials.password, user["password_hash"]):
        await rate_limit_repo.record_request(
            limit_type="login_ip", key=client_ip, ttl_seconds=LOGIN_RATE_LIMIT_WINDOW
        )
        await rate_limit_repo.record_request(
            limit_type="login_email", key=normalized_email, ttl_seconds=LOGIN_RATE_LIMIT_WINDOW
        )
        await audit_logger.log_auth(
            request=request,
            action="login_failed",
            user_id=str(user["_id"]) if user else None,
            status_code=401,
            message=f"登入失敗: {credentials.email}"
        )
        raise api_error(
            "AUTH_INVALID_CREDENTIALS",
            "Incorrect email or password",
            status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 檢查 Email 是否已驗證
    if not user.get("email_verified"):
        raise api_error(
            "AUTH_EMAIL_NOT_VERIFIED",
            "Please verify your email first",
            status.HTTP_403_FORBIDDEN,
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
        raise api_error(
            "AUTH_ACCOUNT_DISABLED",
            "This account has been disabled",
            status.HTTP_403_FORBIDDEN,
        )

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
    # access token 過渡期：cookie + body 雙軌並存（見 TokenResponse docstring）
    set_access_cookie(response, access_token)

    # 登入成功：清除該 email 的失敗計數
    await rate_limit_repo.clear_records("login_email", normalized_email)

    # 記錄成功登入
    await audit_logger.log_auth(
        request=request,
        action="login",
        user_id=str(user["_id"]),
        status_code=200,
        message="登入成功"
    )

    return TokenResponse(access_token=access_token, token_type="bearer", expires_at=expires_at)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db=Depends(get_database)
):
    """刷新 Access Token。

    從 httpOnly cookie 讀 refresh token，舊版傳 body 的呼叫一律拒絕（401）。
    """
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not cookie_token:
        raise api_error(
            "AUTH_REFRESH_TOKEN_MISSING",
            "Missing refresh token cookie",
            status.HTTP_401_UNAUTHORIZED,
        )

    token_data = verify_token(cookie_token, "refresh")
    if not token_data:
        # 順手清掉壞掉的 cookie，避免下次再帶錯
        clear_refresh_cookie(response)
        raise api_error(
            "AUTH_REFRESH_TOKEN_INVALID",
            "Invalid refresh token",
            status.HTTP_401_UNAUTHORIZED,
        )

    # 驗證 Token 是否在資料庫中且未被撤銷
    user_repo = UserRepository(db)
    if not await user_repo.verify_refresh_token(token_data.user_id, cookie_token):
        clear_refresh_cookie(response)
        raise api_error(
            "AUTH_REFRESH_TOKEN_REVOKED",
            "Refresh token has been revoked or expired",
            status.HTTP_401_UNAUTHORIZED,
        )

    # 生成新 Access Token；refresh token 沿用不旋轉（簡化 client 同步）
    access_token, expires_at = create_access_token({
        "sub": token_data.user_id,
        "email": token_data.email,
        "role": token_data.role
    })
    set_access_cookie(response, access_token)

    return TokenResponse(access_token=access_token, token_type="bearer", expires_at=expires_at)


@router.post("/logout")
async def logout(
    http_request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """登出：清 cookie + 撤銷 DB 中的 refresh token。"""
    user_repo = UserRepository(db)
    cookie_token = http_request.cookies.get(REFRESH_COOKIE_NAME)
    if cookie_token:
        await user_repo.revoke_refresh_token(str(current_user["_id"]), cookie_token)
    clear_refresh_cookie(response)
    clear_access_cookie(response)

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
        raise api_error(
            "AUTH_USER_NOT_FOUND",
            "User not found",
            status.HTTP_404_NOT_FOUND,
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
        raise api_error(
            "AUTH_CURRENT_PASSWORD_INCORRECT",
            "Current password is incorrect",
            status.HTTP_400_BAD_REQUEST,
        )

    # 檢查新密碼不能與舊密碼相同
    if request.current_password == request.new_password:
        raise api_error(
            "AUTH_NEW_PASSWORD_SAME_AS_OLD",
            "New password must be different from the current password",
            status.HTTP_400_BAD_REQUEST,
        )

    # 驗證密碼複雜度（與註冊時相同）
    import re
    new_pwd = request.new_password
    if not re.search(r'[A-Z]', new_pwd):
        raise api_error(
            "AUTH_PASSWORD_MISSING_UPPERCASE",
            "New password must contain at least one uppercase letter",
            status.HTTP_400_BAD_REQUEST,
        )
    if not re.search(r'[a-z]', new_pwd):
        raise api_error(
            "AUTH_PASSWORD_MISSING_LOWERCASE",
            "New password must contain at least one lowercase letter",
            status.HTTP_400_BAD_REQUEST,
        )
    if not re.search(r'[0-9]', new_pwd):
        raise api_error(
            "AUTH_PASSWORD_MISSING_DIGIT",
            "New password must contain at least one digit",
            status.HTTP_400_BAD_REQUEST,
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
        raise api_error(
            "AUTH_USER_NOT_FOUND",
            "User not found",
            status.HTTP_404_NOT_FOUND,
        )

    # 跨月自動歸零配額
    from src.auth.quota import QuotaManager
    usage = full_user.get("usage", {})
    usage = await QuotaManager._reset_monthly_quota_if_needed(full_user, usage, db=db)

    # 處理 created_at（可能是 datetime 或 int）
    created_at = full_user["created_at"]
    if hasattr(created_at, 'timestamp'):
        # datetime 對象，轉換為 timestamp
        created_at = int(created_at.timestamp())

    # 處理 usage.last_reset（可能是 datetime 或 int）
    if usage and "last_reset" in usage:
        last_reset = usage["last_reset"]
        if hasattr(last_reset, 'timestamp'):
            usage = {**usage, "last_reset": int(last_reset.timestamp())}

    # 計算 auth_providers
    auth_providers = full_user.get("auth_providers", [])
    # 相容舊帳號：如果沒有 auth_providers 但有密碼，則為 password
    if not auth_providers and full_user.get("password_hash"):
        auth_providers = ["password"]

    # 從 tier 定義補齊缺少的 quota 欄位（相容舊用戶）
    user_quota = full_user.get("quota", {})
    tier = user_quota.get("tier", QuotaTier.FREE)
    tier_defaults = {k: v for k, v in QUOTA_TIERS.get(tier, QUOTA_TIERS[QuotaTier.FREE]).items() if k not in ("name", "price")}
    merged_quota = {**tier_defaults, **user_quota}

    # 過濾掉次數相關欄位（只用時數限制）
    quota_filtered = {k: v for k, v in merged_quota.items() if k != "max_transcriptions"}
    usage_filtered = {k: v for k, v in usage.items() if k not in ("transcriptions", "total_transcriptions")}

    return UserResponse(
        id=str(full_user["_id"]),
        email=full_user["email"],
        role=full_user["role"],
        is_active=full_user["is_active"],
        quota=quota_filtered,
        usage=usage_filtered,
        extra_quota=full_user.get("extra_quota", {}),
        created_at=created_at,
        auth_providers=auth_providers,
        preferences=full_user.get("preferences", {}),
        subscription=full_user.get("subscription"),
    )


@router.patch("/preferences")
async def update_preferences(
    request: UpdatePreferencesRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """更新用戶偏好設定

    Args:
        request: 偏好設定更新請求
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        更新後的 preferences
    """
    user_repo = UserRepository(db)

    prefs_to_update = request.dict(exclude_none=True)
    if not prefs_to_update:
        raise api_error(
            "AUTH_NO_PREFERENCES_PROVIDED",
            "No preferences provided to update",
            status.HTTP_400_BAD_REQUEST,
        )

    updated_preferences = await user_repo.update_preferences(
        str(current_user["_id"]),
        prefs_to_update
    )

    if updated_preferences is None:
        raise api_error(
            "AUTH_USER_NOT_FOUND",
            "User not found",
            status.HTTP_404_NOT_FOUND,
        )

    return {"preferences": updated_preferences}


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
        raise api_error(
            "AUTH_RATE_LIMITED",
            "Too many requests, please try again later",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # 記錄此 IP 的請求（無論 email 是否存在都記錄，防止探測）
    await rate_limit_repo.record_request(
        limit_type="forgot_password_ip",
        key=client_ip,
        ttl_seconds=3600
    )

    # 委派 CredentialFlow：unknown / 未驗證 → silent；已驗證（含 bounced，刻意不 skip
    # 以免真實用戶被永久鎖死）→ 簽 reset token + 寄信。cooldown 由 module 依
    # password_reset_requested_at 判定，超過則拋 CredentialCooldown（edge → 429）。
    flow = build_credential_flow(db)
    try:
        outcome = await flow.issue(CredentialIntent.FORGOT, request.email)
    except CredentialCooldown as e:
        remaining_minutes = (e.remaining_seconds + 59) // 60  # 向上取整
        raise api_error(
            "AUTH_PASSWORD_RESET_COOLDOWN",
            "Please wait {minutes} minutes before trying again",
            status.HTTP_429_TOO_MANY_REQUESTS,
            minutes=remaining_minutes,
        )

    await _dispatch_credential_email(email_service, outcome.email)
    await _log_credential_audit(get_audit_logger(), http_request, outcome.audit)
    return outcome.response


@router.get("/reset-password")
async def reset_password_preflight(
    token: str,
    db=Depends(get_database)
):
    """預檢密碼重設 token 是否有效（**不消耗、不寫 DB**）。

    給前端在渲染重設表單前確認 token 仍有效，讓過期/無效連結能在「點開當下」
    就提示重新申請，而不是等使用者填完送出才被擋。唯讀，故 mail gateway /
    連結預掃 bot 的自動 GET 不會消耗 token。

    Args:
        token: 密碼重設 token (from URL query parameter)
        db: 資料庫實例

    Returns:
        {"valid": True, "expires_at": ...}

    Raises:
        HTTPException: 400 token 無效或已過期
    """
    flow = build_credential_flow(db)
    try:
        result = await flow.preflight(CredentialPurpose.RESET_PASSWORD, token)
    except (CredentialTokenInvalid, CredentialTokenExpired) as e:
        # reset 流程一律以 400 表達無效 / 過期（沿用舊行為）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {"valid": True, "expires_at": result.expires_at}


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
    flow = build_credential_flow(db)
    try:
        outcome = await flow.consume(
            CredentialPurpose.RESET_PASSWORD, request.token, new_password=request.new_password
        )
    except (CredentialTokenInvalid, CredentialTokenExpired, WeakPassword) as e:
        # reset 流程一律以 400 表達無效 / 過期 / 弱密碼（沿用舊行為）
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await _log_credential_audit(get_audit_logger(), http_request, outcome.audit)
    return outcome.response


@router.delete("/account")
async def delete_account(
    http_request: Request,
    request: DeleteAccountRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """刪除帳號

    永久刪除用戶帳號及所有相關資料，使用紀錄去識別化保留。

    Args:
        http_request: HTTP Request 對象
        request: 刪除帳號請求（confirmation, password）
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        成功訊息

    Raises:
        HTTPException: 驗證失敗
    """
    user_repo = UserRepository(db)
    audit_logger = get_audit_logger()
    user_id = str(current_user["_id"])

    # 從資料庫獲取完整用戶資料
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error(
            "AUTH_USER_NOT_FOUND",
            "User not found",
            status.HTTP_404_NOT_FOUND,
        )

    # 驗證 email 確認
    if request.confirmation != user["email"]:
        raise api_error(
            "AUTH_EMAIL_CONFIRMATION_MISMATCH",
            "Email confirmation does not match",
            status.HTTP_400_BAD_REQUEST,
        )

    # 密碼用戶需驗證密碼
    auth_providers = user.get("auth_providers", [])
    if "password" in auth_providers:
        if not request.password:
            raise api_error(
                "AUTH_PASSWORD_REQUIRED",
                "Please enter your password to confirm deletion",
                status.HTTP_400_BAD_REQUEST,
            )
        if not verify_password(request.password, user["password_hash"]):
            raise api_error(
                "AUTH_PASSWORD_INCORRECT",
                "Incorrect password",
                status.HTTP_400_BAD_REQUEST,
            )

    # 記錄刪除操作（在刪除前記錄）
    await audit_logger.log_auth(
        request=http_request,
        action="delete_account",
        user_id=user_id,
        status_code=200,
        message=f"帳號刪除: {user['email']}"
    )

    # 1. 取得用戶所有任務（用於刪除關聯資料）
    from ..database.repositories.task_repo import TaskRepository
    task_repo = TaskRepository(db)
    user_tasks = await task_repo.get_audio_refs_for_user(user_id)

    task_ids = [task["_id"] for task in user_tasks]

    # 2. 刪除 S3/本地音檔
    from ..utils.storage.compact import delete_audio_by_path
    for task in user_tasks:
        audio_path = task.get("result", {}).get("audio_file")
        if audio_path:
            try:
                delete_audio_by_path(audio_path)
            except Exception as e:
                log.warning("audio.delete_failed", task_id=str(task["_id"]), error=str(e))

    # 3. 刪除關聯資料
    if task_ids:
        await db.transcriptions.delete_many({"_id": {"$in": task_ids}})
        await db.segments.delete_many({"_id": {"$in": task_ids}})
        await db.summaries.delete_many({"_id": {"$in": task_ids}})

    # 4. 刪除任務
    await task_repo.delete_all_for_user(user_id)

    # 5. 刪除標籤
    await db.tags.delete_many({"user_id": user_id})

    # 6. 抹除用戶個人資訊（軟刪除，保留 _id 讓 audit_logs 等仍可關聯到去識別帳號）
    now = get_utc_timestamp()
    await user_repo.update(user_id, {
        "email": None,
        "password_hash": None,
        "google_id": None,
        "auth_providers": [],
        "is_active": False,
        "deleted_at": now,
        "refresh_tokens": [],
        "preferences": {},
        "verification_token": None,
        "verification_token_hash": None,
        "verification_expires": None,
        "password_reset_token": None,
        "password_reset_token_hash": None,
        "password_reset_expires": None,
        "password_reset_requested_at": None,
        # email_bounce_reason 可能含 provider 回傳的完整 email 字串或診斷訊息，
        # 屬於 PII，soft-delete 須一併抹除
        "email_bounced": None,
        "email_bounce_event": None,
        "email_bounce_at": None,
        "email_bounce_reason": None
    })

    return {"message": "帳號已永久刪除"}
