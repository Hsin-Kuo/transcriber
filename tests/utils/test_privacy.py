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
    ("alice@example.com", "al***@example.com"),
    ("a@example.com", "a***@example.com"),
    ("longusername@sub.example.com", "lo***@sub.example.com"),
    ("ab@x.io", "ab***@x.io"),
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
