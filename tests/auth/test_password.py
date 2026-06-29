"""verify_password / hash_password 單元測試。

回歸重點：OAuth-only 帳號的 password_hash 為 None，
若 verify_password 不防呆會 .encode() 拋 AttributeError，
讓 email+密碼登入變成未處理的 HTTP 500（而非預期的 401）。
"""
import pytest

from src.auth.password import hash_password, verify_password


def test_correct_password_verifies():
    h = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", h) is True


def test_wrong_password_fails():
    h = hash_password("correct-horse-battery")
    assert verify_password("wrong", h) is False


@pytest.mark.parametrize("empty_hash", [None, ""])
def test_oauth_account_without_password_hash_returns_false(empty_hash):
    # OAuth-only 帳號 password_hash=None：必須回 False，不可拋例外，
    # 否則 login 會 500 而非走 401 invalid-credentials 分支。
    assert verify_password("any-password", empty_hash) is False
