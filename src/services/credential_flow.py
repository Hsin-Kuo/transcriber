"""CredentialFlow — email-proof credential 流程的 deep module。

擁有 [[Email credential challenge]] 的完整生命週期（issue / consume / preflight）。
module 自己做 user_repo 寫入；只把「非自己領域」的副作用（寄哪封信 / 不寄、要清哪些
rate-limit key、audit 描述）由 CredentialOutcome 帶回，edge 執行。

enumeration 防護的單一守點：「是否找到 user」與「對外回什麼 + 寄哪封信」的耦合收斂於此。
test surface 就是 CredentialOutcome dataclass——不碰 FastAPI / SMTP / rate_limit_repo。
詳見 CONTEXT.md「認證與憑證」。
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union
import secrets

from ..auth.password import hash_token
from ..database.repositories.user_repo import UserRepository
from ..models.quota import QUOTA_TIERS, QuotaTier
from ..utils.privacy import mask_email
from ..utils.time_utils import get_utc_timestamp
from ..utils.logger import get_logger

log = get_logger(__name__)

VERIFICATION_TTL_SECONDS = 24 * 60 * 60  # 24h
RESET_TTL_SECONDS = 60 * 60              # 1h
FORGOT_COOLDOWN_SECONDS = 300            # 同帳號兩次 reset 請求最小間隔


class CredentialError(Exception):
    """CredentialFlow 的 domain exception 基底（edge 負責 map 成 HTTP）。

    user_id 為選用，僅供 edge 落 audit log 用（非 enumeration 敏感——能拿到 token
    本身就代表是該帳號的連結持有者）。
    """
    def __init__(self, message: str = "", *, user_id: Optional[str] = None):
        self.user_id = user_id
        super().__init__(message)


class CredentialCooldown(CredentialError):
    """同帳號 reset 請求過於頻繁（edge → 429）。"""
    def __init__(self, remaining_seconds: int):
        self.remaining_seconds = remaining_seconds
        super().__init__(f"cooldown {remaining_seconds}s")


class CredentialTokenInvalid(CredentialError):
    """consume/preflight 撞到無效（含已用 / 已驗證）token（edge → 400）。"""


class CredentialTokenExpired(CredentialError):
    """consume/preflight 撞到過期 token（edge → 410）。"""


class WeakPassword(CredentialError):
    """新密碼不符複雜度要求（edge → 400）。"""


class CredentialPurpose(str, Enum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


def validate_password_complexity(password: str) -> None:
    """大小寫 + 數字各至少一個，否則拋 WeakPassword。未來 change_password 共用。"""
    import re
    if not re.search(r"[A-Z]", password):
        raise WeakPassword("新密碼必須包含至少一個大寫字母")
    if not re.search(r"[a-z]", password):
        raise WeakPassword("新密碼必須包含至少一個小寫字母")
    if not re.search(r"[0-9]", password):
        raise WeakPassword("新密碼必須包含至少一個數字")


def _as_ts(expires) -> Optional[int]:
    """把可能是 datetime 的 expiry 正規化成 int timestamp。"""
    if expires is None:
        return None
    if hasattr(expires, "timestamp"):
        return int(expires.timestamp())
    return expires


def _is_expired(expires) -> bool:
    """token expiry 可能存成 int 或 datetime；統一判定是否已過期。"""
    if not expires:
        return False
    if hasattr(expires, "timestamp"):
        expires = int(expires.timestamp())
    return expires < get_utc_timestamp()


class CredentialIntent(str, Enum):
    REGISTER = "register"
    RESEND = "resend"
    FORGOT = "forgot"


# ── EmailInstruction variants（決策，不是寄送動作）─────────────────────────────

@dataclass(frozen=True)
class SendVerification:
    to: str
    token: str


@dataclass(frozen=True)
class SendAccountExists:
    to: str


@dataclass(frozen=True)
class SendPasswordReset:
    to: str
    token: str


EmailInstruction = Union[SendVerification, SendAccountExists, SendPasswordReset]


@dataclass(frozen=True)
class AuditDescriptor:
    action: str
    user_id: Optional[str]
    status_code: int
    message: str


@dataclass(frozen=True)
class PreflightResult:
    """preflight 的唯讀回傳（token 仍有效時）。reset 流程忽略 email。"""
    expires_at: Optional[int] = None
    email: Optional[str] = None


@dataclass(frozen=True)
class CredentialOutcome:
    response: dict
    email: Optional[EmailInstruction] = None
    rate_limit_clears: tuple = ()
    audit: Optional[AuditDescriptor] = None


def _new_token() -> tuple[str, str]:
    """回傳 (plaintext, hash)：plaintext 給信、hash 進 DB。"""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def _free_quota() -> dict:
    return {
        "tier": QuotaTier.FREE,
        **{k: v for k, v in QUOTA_TIERS[QuotaTier.FREE].items() if k not in ("name", "price")},
    }


class CredentialFlow:
    def __init__(self, *, user_repo: UserRepository):
        self.user_repo = user_repo

    async def issue(
        self,
        intent: CredentialIntent,
        email: str,
        password: Optional[str] = None,
        consent: Optional[dict] = None,
    ) -> CredentialOutcome:
        if intent == CredentialIntent.REGISTER:
            return await self._issue_register(email, password, consent)
        if intent == CredentialIntent.RESEND:
            return await self._issue_resend(email)
        if intent == CredentialIntent.FORGOT:
            return await self._issue_forgot(email)
        raise NotImplementedError(intent)

    async def _issue_forgot(self, email: str) -> CredentialOutcome:
        silent = {
            "message": "如果該 Email 已註冊，您將會收到密碼重設郵件",
            "email": email,
        }
        user = await self.user_repo.get_by_email(email)
        # 未驗證 / unknown → silent。已驗證即使 email_bounced 也照發（bounce 可能為暫時，
        # silent skip 會把真實用戶永久鎖死）—— 見 CONTEXT.md。
        if user is None or not user.get("email_verified"):
            return CredentialOutcome(response=silent)

        if user.get("email_bounced"):
            log.info(
                "auth.forgot_password.attempt_for_bounced_user",
                user_id=str(user["_id"]), email=mask_email(email),
            )

        # password_reset_requested_at 可能是 int 或 BSON datetime；統一正規化（同原 check_cooldown）
        last = _as_ts(user.get("password_reset_requested_at"))
        if last:
            elapsed = get_utc_timestamp() - last
            if elapsed < FORGOT_COOLDOWN_SECONDS:
                raise CredentialCooldown(FORGOT_COOLDOWN_SECONDS - elapsed)

        token, token_hash = _new_token()
        now = get_utc_timestamp()
        await self.user_repo.update(str(user["_id"]), {
            "password_reset_token": None,
            "password_reset_token_hash": token_hash,
            "password_reset_expires": now + RESET_TTL_SECONDS,
            "password_reset_requested_at": now,
        })
        return CredentialOutcome(
            response=silent,
            email=SendPasswordReset(to=email, token=token),
            audit=AuditDescriptor("forgot_password", str(user["_id"]), 200, f"發送密碼重設郵件：{email}"),
        )

    async def _issue_resend(self, email: str) -> CredentialOutcome:
        # 對外一律相同，僅在「未驗證且未 bounce」時實際重簽 + 寄信。
        silent = CredentialOutcome(response={
            "message": "驗證郵件已重新發送，請查看您的郵箱",
            "email": email,
        })
        user = await self.user_repo.get_by_email(email)
        if user is None or user.get("email_verified") or user.get("email_bounced"):
            return silent
        token, token_hash = await self._reissue_verification_token(str(user["_id"]))
        return CredentialOutcome(
            response=silent.response,
            email=SendVerification(to=email, token=token),
        )

    # ── consume（驗 token + 套效果）────────────────────────────────────────

    async def consume(
        self, purpose: CredentialPurpose, token: str, new_password: Optional[str] = None
    ) -> CredentialOutcome:
        if purpose == CredentialPurpose.VERIFY_EMAIL:
            return await self._consume_verify_email(token)
        if purpose == CredentialPurpose.RESET_PASSWORD:
            return await self._consume_reset_password(token, new_password)
        raise NotImplementedError(purpose)

    # ── preflight（唯讀，絕不寫 DB / 絕不 consume）──────────────────────────

    async def preflight(self, purpose: CredentialPurpose, token: str) -> PreflightResult:
        if purpose == CredentialPurpose.VERIFY_EMAIL:
            user = await self.user_repo.get_by_verification_token(token)
            if not user:
                raise CredentialTokenInvalid("驗證連結無效")
            if user.get("email_verified"):
                raise CredentialTokenInvalid("此 Email 已完成驗證")
            expires = user.get("verification_expires")
            if _is_expired(expires):
                raise CredentialTokenExpired("驗證連結已過期，請重新申請驗證郵件")
            return PreflightResult(expires_at=_as_ts(expires), email=user["email"])

        user = await self.user_repo.get_by_password_reset_token(token)
        if not user:
            raise CredentialTokenInvalid("重設連結無效或已過期")
        expires = user.get("password_reset_expires")
        if _is_expired(expires):
            raise CredentialTokenExpired("重設連結已過期，請重新申請")
        return PreflightResult(expires_at=_as_ts(expires))

    async def _consume_reset_password(self, token: str, new_password: Optional[str]) -> CredentialOutcome:
        from ..auth.password import hash_password

        user = await self.user_repo.get_by_password_reset_token(token)
        if not user:
            raise CredentialTokenInvalid("重設連結無效或已過期")
        if _is_expired(user.get("password_reset_expires")):
            raise CredentialTokenExpired("重設連結已過期，請重新申請")
        validate_password_complexity(new_password or "")  # 弱密碼在寫 DB 之前就擋
        await self.user_repo.update(str(user["_id"]), {
            "password_hash": hash_password(new_password),
            "password_reset_token": None,
            "password_reset_token_hash": None,
            "password_reset_expires": None,
            "password_reset_requested_at": None,
        })
        return CredentialOutcome(
            response={"message": "密碼已重設成功，請使用新密碼登入"},
            audit=AuditDescriptor("reset_password", str(user["_id"]), 200, f"密碼重設成功：{user.get('email')}"),
        )

    async def _consume_verify_email(self, token: str) -> CredentialOutcome:
        user = await self.user_repo.get_by_verification_token(token)
        if not user:
            raise CredentialTokenInvalid("驗證連結無效")
        if user.get("email_verified"):
            raise CredentialTokenInvalid("此 Email 已完成驗證")
        if _is_expired(user.get("verification_expires")):
            raise CredentialTokenExpired(
                "驗證連結已過期，請重新申請驗證郵件", user_id=str(user["_id"])
            )
        await self.user_repo.update(str(user["_id"]), {
            "is_active": True,
            "email_verified": True,
            "verification_token": None,
            "verification_token_hash": None,
            "verification_expires": None,
        })
        return CredentialOutcome(
            response={"verified": True, "email": user["email"]},
            audit=AuditDescriptor("verify_email", str(user["_id"]), 200, f"Email 驗證成功: {user['email']}"),
        )

    async def _reissue_verification_token(self, user_id: str) -> tuple[str, str]:
        """重簽 verification token：寫 hash + expiry、清 legacy plaintext。回 (plaintext, hash)。"""
        token, token_hash = _new_token()
        await self.user_repo.update(user_id, {
            "verification_token": None,
            "verification_token_hash": token_hash,
            "verification_expires": get_utc_timestamp() + VERIFICATION_TTL_SECONDS,
        })
        return token, token_hash

    @staticmethod
    def _register_response(email: str) -> dict:
        # 對外一律相同字串 → unknown 與 duplicate 不可區分（防 enumeration）。
        return {
            "message": "註冊成功！請查看您的郵箱完成驗證",
            "email": email,
            "email_sent": True,
        }

    async def _issue_register(
        self, email: str, password: Optional[str], consent: Optional[dict] = None
    ) -> CredentialOutcome:
        from ..auth.password import hash_password

        existing = await self.user_repo.get_by_email(email)
        if existing is not None:
            if existing.get("email_verified"):
                return CredentialOutcome(
                    response=self._register_response(email),
                    email=SendAccountExists(to=email),
                    audit=AuditDescriptor(
                        "register_duplicate_verified", str(existing["_id"]), 200,
                        f"重複註冊嘗試: {email}",
                    ),
                )
            token, _ = await self._reissue_verification_token(str(existing["_id"]))
            return CredentialOutcome(
                response=self._register_response(email),
                email=SendVerification(to=email, token=token),
                audit=AuditDescriptor(
                    "register_duplicate_unverified_resent", str(existing["_id"]), 200,
                    f"重複註冊嘗試: {email}",
                ),
            )

        # unknown email → 建新（inactive + unverified）帳號並簽 verification token
        token, token_hash = _new_token()
        now = get_utc_timestamp()
        new_user = {
            "email": email,
            "password_hash": hash_password(password),
            "auth_providers": ["password"],
            "role": "user",
            "is_active": False,
            "email_verified": False,
            "verification_token": None,
            "verification_token_hash": token_hash,
            "verification_expires": now + VERIFICATION_TTL_SECONDS,
            "quota": _free_quota(),
            "usage": {
                "transcriptions": 0,
                "duration_minutes": 0,
                "ai_summaries": 0,
                "last_reset": now,
                "total_transcriptions": 0,
                "total_duration_minutes": 0,
                "total_ai_summaries": 0,
            },
            "refresh_tokens": [],
            "created_at": now,
            "updated_at": now,
        }
        # 同意軌跡（edge 已把關「無同意不得註冊」，這裡僅落檔快照）
        if consent:
            new_user["consent"] = consent
        created = await self.user_repo.create(new_user)
        return CredentialOutcome(
            response=self._register_response(email),
            email=SendVerification(to=email, token=token),
            audit=AuditDescriptor("register", str(created["_id"]), 200, f"新用戶註冊: {email}"),
        )


def build_credential_flow(db) -> CredentialFlow:
    """以 request-scoped db 組出 CredentialFlow（唯一依賴 user_repo）。"""
    return CredentialFlow(user_repo=UserRepository(db))
