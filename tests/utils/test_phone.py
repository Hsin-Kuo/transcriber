"""電話正規化（91APP cardHolder.phoneNumber 專案）單元測試。"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "a" * 64)

from src.utils.phone import normalize_tw_phone  # noqa: E402


class TestNormalizeTwPhone:
    def test_local_format_09_prefixed(self):
        assert normalize_tw_phone("0912345678") == "+886912345678"

    def test_international_format_passthrough(self):
        assert normalize_tw_phone("+886912345678") == "+886912345678"

    def test_strips_whitespace_and_dashes(self):
        assert normalize_tw_phone("09-1234-5678") == "+886912345678"
        assert normalize_tw_phone("0912 345 678") == "+886912345678"
        assert normalize_tw_phone("+886 912 345 678") == "+886912345678"
        assert normalize_tw_phone("+886-912-345-678") == "+886912345678"

    @pytest.mark.parametrize("bad", [
        "",
        None,
        "12345",
        "0212345678",       # 市話（02 開頭），非手機
        "091234567",        # 少一碼
        "09123456789",      # 多一碼
        "+886212345678",    # 國碼後不是 9 開頭
        "+88691234567",     # 國際碼格式但少一碼
        "abcdefghij",
    ])
    def test_invalid_formats_raise(self, bad):
        with pytest.raises(ValueError):
            normalize_tw_phone(bad)
