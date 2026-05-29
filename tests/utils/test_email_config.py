"""EmailService 設定驗證測試（P1-11）。

確保 startup 時就抓到漏設 FROM_EMAIL / SMTP 等問題，
避免上線後第一個用戶註冊才爆炸。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.utils.email_service import EmailConfigError, EmailService  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    """每個 test 前清掉所有 email 相關 env，避免 host shell 污染。"""
    for key in (
        "EMAIL_PROVIDER",
        "FROM_EMAIL",
        "FROM_NAME",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "RESEND_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    # 清掉 module-level cache，避免上輪 test 留下的值
    from src.utils import config_loader
    config_loader._param_cache.clear()


def test_console_provider_no_validation(clean_env, monkeypatch):
    """console 模式下不檢查任何欄位 — 本地開發體驗。"""
    monkeypatch.setenv("EMAIL_PROVIDER", "console")
    svc = EmailService()
    assert svc.email_provider == "console"
    assert svc.from_email == ""  # 沒設也 OK


def test_default_provider_is_console(clean_env):
    """完全沒設 EMAIL_PROVIDER 預設走 console，不應炸。"""
    svc = EmailService()
    assert svc.email_provider == "console"


def test_resend_without_from_email_raises(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    with pytest.raises(EmailConfigError, match="FROM_EMAIL"):
        EmailService()


def test_resend_with_invalid_from_email_raises(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("FROM_EMAIL", "not-an-email")
    with pytest.raises(EmailConfigError, match="非合法 email"):
        EmailService()


def test_resend_without_api_key_raises(clean_env, monkeypatch):
    """EMAIL_PROVIDER=resend 但缺 RESEND_API_KEY 應啟動失敗，不要等
    第一個用戶註冊才在 _send_via_resend 拋 ValueError。"""
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("FROM_EMAIL", "noreply@soundlite.app")
    with pytest.raises(EmailConfigError, match="RESEND_API_KEY"):
        EmailService()


def test_resend_with_valid_config_ok(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("FROM_EMAIL", "noreply@soundlite.app")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
    svc = EmailService()
    assert svc.from_email == "noreply@soundlite.app"


def test_ses_without_from_email_raises(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "ses")
    with pytest.raises(EmailConfigError, match="FROM_EMAIL"):
        EmailService()


def test_smtp_missing_credentials_raises(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("FROM_EMAIL", "noreply@soundlite.app")
    # 缺 SMTP_USER 與 SMTP_PASSWORD
    with pytest.raises(EmailConfigError, match="SMTP_USER"):
        EmailService()


def test_smtp_with_full_config_ok(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("FROM_EMAIL", "noreply@soundlite.app")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    svc = EmailService()
    assert svc.smtp_user == "user@example.com"


def test_unknown_provider_raises(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "sendgrid")
    with pytest.raises(EmailConfigError, match="不支援"):
        EmailService()


def test_from_email_strips_whitespace(clean_env, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("FROM_EMAIL", "  noreply@soundlite.app  ")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_xxx")
    svc = EmailService()
    assert svc.from_email == "noreply@soundlite.app"
