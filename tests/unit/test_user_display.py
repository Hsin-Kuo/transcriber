"""user_display：已刪除帳號的去識別假名。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.user_display import deleted_user_label, user_email_or_label  # noqa: E402


class TestDeletedUserLabel:
    def test_uses_last6_of_id(self):
        assert deleted_user_label("abcdef123456") == "已刪除用戶#123456"

    def test_stable_for_same_id(self):
        assert deleted_user_label("u-xyz789") == deleted_user_label("u-xyz789")

    def test_empty_id_generic_label(self):
        assert deleted_user_label("") == "已刪除用戶"
        assert deleted_user_label(None) == "已刪除用戶"


class TestUserEmailOrLabel:
    def test_active_user_returns_email(self):
        assert user_email_or_label("a@b.com", "id123456", deleted=False) == "a@b.com"

    def test_deleted_user_returns_label(self):
        assert user_email_or_label(None, "id123456", deleted=True) == "已刪除用戶#123456"

    def test_missing_email_inferred_as_deleted(self):
        # deleted 未指定 + 無 email + 有 id → 推定已刪除
        assert user_email_or_label(None, "id123456") == "已刪除用戶#123456"

    def test_no_email_not_deleted_returns_dash(self):
        assert user_email_or_label(None, "id123456", deleted=False) == "—"
