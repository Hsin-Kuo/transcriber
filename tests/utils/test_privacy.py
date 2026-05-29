"""PII helpers 測試。"""
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

from src.utils.privacy import mask_email  # noqa: E402


@pytest.mark.parametrize("email, expected", [
    ("alice@example.com", "a***@example.com"),
    ("a@example.com", "***@example.com"),  # 1 字 localpart 全遮
    ("longusername@sub.example.com", "l***@sub.example.com"),
    ("ab@x.io", "a***@x.io"),  # 2 字 localpart 只露首字
])
def test_mask_email_normal(email, expected):
    assert mask_email(email) == expected


@pytest.mark.parametrize("bad", [
    "",
    "not-an-email",
    "@nolocal.com",
    "noatsign.com",
    "trailing@",
    None,
    123,
])
def test_mask_email_handles_garbage(bad):
    assert mask_email(bad) == "***"


def test_mask_email_preserves_domain():
    """Domain 整段不遮蔽 — 方便 debug 時辨識公司/服務 provider。"""
    assert mask_email("john.doe@company.internal").endswith("@company.internal")


def test_mask_email_unicode_localpart():
    """中文 / Unicode localpart 應正確處理（不 crash、首字符遮蔽邏輯一致）。"""
    assert mask_email("用戶@example.com") == "用***@example.com"


def test_mask_email_idn_domain():
    """IDN（國際化網域）domain 整段保留。"""
    assert mask_email("alice@台灣.tw") == "a***@台灣.tw"


def test_mask_email_emoji_localpart():
    """Emoji localpart（極少見但理論可能）— 不該 crash。"""
    result = mask_email("📧test@example.com")
    assert result.endswith("@example.com")
    assert "📧" in result or result.startswith("?")  # 取首字即可
