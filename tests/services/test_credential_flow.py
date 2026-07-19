"""CredentialFlow 單元測試。

驗證 deepening 的價值——email-proof credential 的每一條 transition（含 enumeration
不變式）都能用 plain input + fake user_repo 覆蓋，不需要 FastAPI / SMTP / rate_limit_repo。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.auth.password import hash_token  # noqa: E402
from src.services.credential_flow import (  # noqa: E402
    CredentialCooldown,
    CredentialFlow,
    CredentialIntent,
    CredentialPurpose,
    CredentialTokenExpired,
    CredentialTokenInvalid,
    SendAccountExists,
    SendPasswordReset,
    SendVerification,
    WeakPassword,
)
from src.auth.password import verify_password  # noqa: E402
from src.utils.time_utils import get_utc_timestamp  # noqa: E402


def _make(user=None):
    """建一個 CredentialFlow，唯一依賴 user_repo 全 fake。"""
    user_repo = MagicMock()
    user_repo.get_by_email = AsyncMock(return_value=user)
    user_repo.get_by_verification_token = AsyncMock(return_value=user)
    user_repo.get_by_password_reset_token = AsyncMock(return_value=user)
    user_repo.create = AsyncMock(side_effect=lambda d: {**d, "_id": "uid"})
    user_repo.update = AsyncMock(return_value=True)
    user_repo.delete = AsyncMock(return_value=True)
    return CredentialFlow(user_repo=user_repo), user_repo


class TestRegisterIssue:
    async def test_unknown_email_creates_user_and_sends_verification(self):
        flow, user_repo = _make(user=None)

        out = await flow.issue(CredentialIntent.REGISTER, "New@x.com", password="Abc12345")

        # 新帳號：inactive + unverified，DB 只存 token 的 hash
        created = user_repo.create.await_args.args[0]
        assert created["email"] == "New@x.com"
        assert created["is_active"] is False
        assert created["email_verified"] is False
        assert created.get("verification_token") is None  # 不存 plaintext
        assert created["verification_token_hash"]

        # 信帶 plaintext token，且與 DB 存的 hash 對得起來
        assert isinstance(out.email, SendVerification)
        assert out.email.to == "New@x.com"
        assert hash_token(out.email.token) == created["verification_token_hash"]

        # 對外回應 + audit
        assert out.response["email_sent"] is True
        assert out.audit.action == "register"
        assert out.audit.user_id == "uid"

    async def test_consent_record_is_persisted_when_provided(self):
        flow, user_repo = _make(user=None)

        consent = {"agreed": True, "terms_version": "2026-07-19", "method": "register"}
        await flow.issue(
            CredentialIntent.REGISTER, "New@x.com", password="Abc12345", consent=consent
        )

        created = user_repo.create.await_args.args[0]
        assert created["consent"] == consent

    async def test_consent_absent_when_not_provided(self):
        flow, user_repo = _make(user=None)

        await flow.issue(CredentialIntent.REGISTER, "New@x.com", password="Abc12345")

        created = user_repo.create.await_args.args[0]
        assert "consent" not in created

    async def test_verified_email_sends_account_exists_without_token_write(self):
        verified = {"_id": "u1", "email": "a@x.com", "email_verified": True}
        flow, user_repo = _make(user=verified)

        out = await flow.issue(CredentialIntent.REGISTER, "a@x.com", password="Abc12345")

        # 防 enumeration：對外回應與全新註冊完全一致
        assert out.response["email_sent"] is True
        # 但寄給真正擁有者的是「帳號已存在」信，且不重簽 token / 不建帳號
        assert isinstance(out.email, SendAccountExists)
        assert out.email.to == "a@x.com"
        user_repo.create.assert_not_awaited()
        user_repo.update.assert_not_awaited()
        assert out.audit.action == "register_duplicate_verified"

    async def test_unverified_email_reissues_verification_token(self):
        unverified = {"_id": "u2", "email": "b@x.com", "email_verified": False}
        flow, user_repo = _make(user=unverified)

        out = await flow.issue(CredentialIntent.REGISTER, "b@x.com", password="Abc12345")

        # 重簽：更新既有 user 的 token hash（不建新帳號），信帶新 plaintext
        user_repo.create.assert_not_awaited()
        updates = user_repo.update.await_args.args[1]
        assert updates["verification_token"] is None  # 清 legacy plaintext
        assert isinstance(out.email, SendVerification)
        assert hash_token(out.email.token) == updates["verification_token_hash"]
        assert out.response == _make(user=unverified)[0]._register_response("b@x.com")
        assert out.audit.action == "register_duplicate_unverified_resent"


class TestResendIssue:
    @pytest.mark.parametrize("user", [
        None,                                                  # unknown
        {"_id": "u1", "email_verified": True},                 # 已驗證
        {"_id": "u1", "email_verified": False, "email_bounced": True},  # 已 bounce
    ], ids=["unknown", "verified", "bounced"])
    async def test_non_actionable_states_stay_silent(self, user):
        flow, user_repo = _make(user=user)

        out = await flow.issue(CredentialIntent.RESEND, "x@x.com")

        # 不寄信、不寫 DB；對外回統一訊息（三種狀態彼此不可區分）
        assert out.email is None
        user_repo.create.assert_not_awaited()
        user_repo.update.assert_not_awaited()
        assert out.response["email"] == "x@x.com"
        assert "message" in out.response

    async def test_unverified_not_bounced_reissues(self):
        user = {"_id": "u9", "email_verified": False}
        flow, user_repo = _make(user=user)

        out = await flow.issue(CredentialIntent.RESEND, "x@x.com")

        updates = user_repo.update.await_args.args[1]
        assert isinstance(out.email, SendVerification)
        assert hash_token(out.email.token) == updates["verification_token_hash"]
        assert updates["verification_token"] is None


class TestForgotIssue:
    @pytest.mark.parametrize("user", [
        None,                                          # unknown
        {"_id": "u1", "email_verified": False},        # 未驗證
    ], ids=["unknown", "unverified"])
    async def test_non_actionable_states_stay_silent(self, user):
        flow, user_repo = _make(user=user)

        out = await flow.issue(CredentialIntent.FORGOT, "x@x.com")

        assert out.email is None
        user_repo.update.assert_not_awaited()
        assert out.response["email"] == "x@x.com"

    async def test_verified_issues_reset_token(self):
        user = {"_id": "u1", "email_verified": True}
        flow, user_repo = _make(user=user)

        out = await flow.issue(CredentialIntent.FORGOT, "a@x.com")

        updates = user_repo.update.await_args.args[1]
        assert isinstance(out.email, SendPasswordReset)
        assert hash_token(out.email.token) == updates["password_reset_token_hash"]
        assert updates["password_reset_token"] is None
        assert updates["password_reset_requested_at"]  # 寫入冷卻時間戳
        assert out.audit.action == "forgot_password"

    async def test_within_cooldown_raises(self):
        from src.utils.time_utils import get_utc_timestamp
        user = {
            "_id": "u1", "email_verified": True,
            "password_reset_requested_at": get_utc_timestamp(),  # 剛剛才請求過
        }
        flow, user_repo = _make(user=user)

        with pytest.raises(CredentialCooldown) as ei:
            await flow.issue(CredentialIntent.FORGOT, "a@x.com")

        assert ei.value.remaining_seconds > 0
        user_repo.update.assert_not_awaited()

    async def test_within_cooldown_handles_datetime_timestamp(self):
        # 回歸：password_reset_requested_at 可能是 BSON datetime（舊資料 / Mongo Date）。
        # 必須跟原 check_cooldown 一樣容忍 datetime，不可 int(datetime) 拋 TypeError → 500。
        from datetime import datetime, timezone
        user = {
            "_id": "u1", "email_verified": True,
            "password_reset_requested_at": datetime.now(timezone.utc),  # 剛請求過
        }
        flow, user_repo = _make(user=user)

        with pytest.raises(CredentialCooldown):
            await flow.issue(CredentialIntent.FORGOT, "a@x.com")
        user_repo.update.assert_not_awaited()


class TestConsumeVerifyEmail:
    async def test_valid_token_activates_account(self):
        user = {
            "_id": "u1", "email": "a@x.com", "email_verified": False,
            "verification_expires": get_utc_timestamp() + 999,
        }
        flow, user_repo = _make(user=user)

        out = await flow.consume(CredentialPurpose.VERIFY_EMAIL, "tok")

        updates = user_repo.update.await_args.args[1]
        assert updates["is_active"] is True
        assert updates["email_verified"] is True
        assert updates["verification_token_hash"] is None  # 燒掉 token
        assert out.response["verified"] is True
        assert out.email is None
        assert out.audit.action == "verify_email"

    async def test_unknown_token_raises_invalid(self):
        flow, _ = _make(user=None)
        with pytest.raises(CredentialTokenInvalid):
            await flow.consume(CredentialPurpose.VERIFY_EMAIL, "nope")

    async def test_already_verified_keeps_distinct_message(self):
        # 保留舊行為：already-verified 與 not-found 的訊息不同
        user = {"_id": "u1", "email": "a@x.com", "email_verified": True}
        flow, user_repo = _make(user=user)
        with pytest.raises(CredentialTokenInvalid) as ei:
            await flow.consume(CredentialPurpose.VERIFY_EMAIL, "tok")
        assert "已完成驗證" in str(ei.value)
        user_repo.update.assert_not_awaited()

    async def test_expired_token_raises_expired(self):
        user = {"_id": "u1", "email_verified": False, "verification_expires": get_utc_timestamp() - 1}
        flow, user_repo = _make(user=user)
        with pytest.raises(CredentialTokenExpired) as ei:
            await flow.consume(CredentialPurpose.VERIFY_EMAIL, "old")
        assert ei.value.user_id == "u1"  # edge 用此落 verify_email_expired audit
        user_repo.update.assert_not_awaited()


class TestConsumeResetPassword:
    async def test_valid_token_sets_password_and_clears(self):
        user = {"_id": "u1", "email": "a@x.com", "password_reset_expires": get_utc_timestamp() + 999}
        flow, user_repo = _make(user=user)

        out = await flow.consume(CredentialPurpose.RESET_PASSWORD, "tok", new_password="NewPass123")

        updates = user_repo.update.await_args.args[1]
        assert verify_password("NewPass123", updates["password_hash"])
        assert updates["password_reset_token_hash"] is None  # 燒掉 reset token
        assert updates["password_reset_requested_at"] is None  # 清冷卻
        assert out.audit.action == "reset_password"
        assert out.email is None

    async def test_weak_password_rejected_before_write(self):
        user = {"_id": "u1", "email": "a@x.com", "password_reset_expires": get_utc_timestamp() + 999}
        flow, user_repo = _make(user=user)

        with pytest.raises(WeakPassword):
            await flow.consume(CredentialPurpose.RESET_PASSWORD, "tok", new_password="alllowercase")
        user_repo.update.assert_not_awaited()  # 弱密碼不可寫進 DB

    async def test_unknown_token_raises_invalid(self):
        flow, _ = _make(user=None)
        with pytest.raises(CredentialTokenInvalid):
            await flow.consume(CredentialPurpose.RESET_PASSWORD, "nope", new_password="NewPass123")

    async def test_expired_token_raises_expired(self):
        user = {"_id": "u1", "password_reset_expires": get_utc_timestamp() - 1}
        flow, _ = _make(user=user)
        with pytest.raises(CredentialTokenExpired):
            await flow.consume(CredentialPurpose.RESET_PASSWORD, "old", new_password="NewPass123")


class TestPreflight:
    async def test_verify_valid_returns_info_without_write(self):
        exp = get_utc_timestamp() + 999
        user = {"_id": "u1", "email": "a@x.com", "email_verified": False, "verification_expires": exp}
        flow, user_repo = _make(user=user)

        result = await flow.preflight(CredentialPurpose.VERIFY_EMAIL, "tok")

        assert result.email == "a@x.com"
        assert result.expires_at == exp
        # 唯讀：絕不可消耗 token / 寫 DB（防 mail gateway 預掃燒 token）
        user_repo.update.assert_not_awaited()

    async def test_verify_already_verified_raises_invalid(self):
        user = {"_id": "u1", "email": "a@x.com", "email_verified": True}
        flow, _ = _make(user=user)
        with pytest.raises(CredentialTokenInvalid):
            await flow.preflight(CredentialPurpose.VERIFY_EMAIL, "tok")

    async def test_reset_expired_raises_without_write(self):
        user = {"_id": "u1", "password_reset_expires": get_utc_timestamp() - 1}
        flow, user_repo = _make(user=user)
        with pytest.raises(CredentialTokenExpired):
            await flow.preflight(CredentialPurpose.RESET_PASSWORD, "old")
        user_repo.update.assert_not_awaited()
