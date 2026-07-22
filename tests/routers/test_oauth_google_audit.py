"""驗證 Google OAuth 路徑會寫稽核紀錄（audit_logs），與 email/password 路徑對齊。

背景：`/auth/google` 過去完全沒呼叫 audit logger，新用戶用 Google 註冊、
或既有用戶用 Google 登入，後台 audit_logs 都查不到。本測試鎖定修復後的行為：
- 新用戶（首次 Google 登入 → 建帳）→ action="oauth_register"
- 既有用戶登入 → action="oauth_login"
- 停用帳號嘗試登入 → action="oauth_login_disabled_account" 且仍擋下（403）

手法同 tests/routers/test_login_access_cookie.py：monkeypatch router 模組內的
repo / audit logger / verify_google_token，直接呼叫 router 函式，不起真的 Mongo。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException, Response  # noqa: E402

from src.routers import oauth  # noqa: E402
from src.models.auth import GoogleAuthRequest  # noqa: E402

GOOGLE_ID = "google-sub-123"
EMAIL = "newcomer@example.com"

EXISTING_ACTIVE_USER = {
    "_id": "507f1f77bcf86cd799439011",
    "email": EMAIL,
    "google_id": GOOGLE_ID,
    "role": "user",
    "is_active": True,
}
EXISTING_DISABLED_USER = {**EXISTING_ACTIVE_USER, "is_active": False}


class _FakeRequest:
    headers = {}
    client = None


class _SpyAuditLogger:
    """記錄所有 log_auth 呼叫，供斷言。"""

    def __init__(self):
        self.calls = []

    async def log_auth(self, **kwargs):
        self.calls.append(kwargs)


def _make_user_repo(by_gid=None, by_email=None):
    class _Repo:
        def __init__(self, db):
            pass

        async def get_by_google_id(self, gid):
            return by_gid

        async def get_by_email(self, email):
            return by_email

        async def create(self, doc):
            # 模擬 Mongo 寫入後回填 _id
            return {**doc, "_id": "newly-created-oauth-user"}

        async def save_refresh_token(self, user_id, token):
            pass

    return _Repo


def _patch_common(monkeypatch, user_repo_cls, spy):
    monkeypatch.setattr(oauth, "UserRepository", user_repo_cls)
    monkeypatch.setattr(oauth, "get_audit_logger", lambda: spy)
    monkeypatch.setattr(
        oauth, "verify_google_token",
        lambda credential: {"sub": GOOGLE_ID, "email": EMAIL},
    )


@pytest.mark.asyncio
async def test_new_google_user_writes_register_audit(monkeypatch):
    """新用戶用 Google 註冊 → audit_logs 應有一筆 oauth_register。"""
    spy = _SpyAuditLogger()
    _patch_common(monkeypatch, _make_user_repo(by_gid=None, by_email=None), spy)

    await oauth.google_auth(
        request=GoogleAuthRequest(credential="fake-token", agreed_to_terms=True),
        response=Response(),
        http_request=_FakeRequest(),
        db=object(),
    )

    assert len(spy.calls) == 1, f"預期剛好一筆 audit，實際={spy.calls}"
    call = spy.calls[0]
    assert call["action"] == "oauth_register"
    assert call["user_id"] == "newly-created-oauth-user"
    assert call["status_code"] == 200
    # 稽核訊息不得含 Google credential / id_token
    assert "fake-token" not in (call.get("message") or "")


@pytest.mark.asyncio
async def test_existing_google_user_writes_login_audit(monkeypatch):
    """既有用戶用 Google 登入 → audit_logs 應有一筆 oauth_login。"""
    spy = _SpyAuditLogger()
    _patch_common(monkeypatch, _make_user_repo(by_gid=EXISTING_ACTIVE_USER), spy)

    await oauth.google_auth(
        request=GoogleAuthRequest(credential="fake-token", agreed_to_terms=False),
        response=Response(),
        http_request=_FakeRequest(),
        db=object(),
    )

    assert len(spy.calls) == 1, f"預期剛好一筆 audit，實際={spy.calls}"
    call = spy.calls[0]
    assert call["action"] == "oauth_login"
    assert call["user_id"] == str(EXISTING_ACTIVE_USER["_id"])
    assert call["status_code"] == 200


@pytest.mark.asyncio
async def test_disabled_google_user_audited_and_blocked(monkeypatch):
    """停用帳號嘗試 Google 登入 → 記 oauth_login_disabled_account 且回 403。"""
    spy = _SpyAuditLogger()
    _patch_common(monkeypatch, _make_user_repo(by_gid=EXISTING_DISABLED_USER), spy)

    with pytest.raises(HTTPException) as exc_info:
        await oauth.google_auth(
            request=GoogleAuthRequest(credential="fake-token", agreed_to_terms=False),
            response=Response(),
            http_request=_FakeRequest(),
            db=object(),
        )

    assert exc_info.value.status_code == 403
    assert len(spy.calls) == 1, f"預期擋下時仍記一筆 audit，實際={spy.calls}"
    assert spy.calls[0]["action"] == "oauth_login_disabled_account"
    assert spy.calls[0]["status_code"] == 403
