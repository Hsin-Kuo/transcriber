"""card_token_cipher 單元測試（金流體檢 P2-10）。

不打真 SSM/KMS：KEK 一律用 monkeypatch 注入的固定測試值（比照
tests/utils/test_payment_env_failfast.py 的 fake SSM 手法）。conftest.py 已經
setdefault 一把全域測試 KEK，讓其他測試套件的加解密路徑（例如
test_subscriptions_pay.py）不需要各自處理環境變數；這裡針對 cipher 本身的
測試需要切換不同 KEK 值，因此在每個測試前後把 config_loader 的參數 cache 與
card_token_cipher 的 lazy KEK cache 都清空，避免互相汙染。
"""
import base64
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

from src.utils import card_token_cipher  # noqa: E402
from src.utils import config_loader  # noqa: E402
from src.utils.card_token_cipher import decrypt, encrypt  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_kek_state(monkeypatch):
    """每個測試前後清空 KEK 相關的兩層 cache，讓不同測試可以各自指定 CARD_TOKEN_KEK。"""
    config_loader._param_cache.clear()
    monkeypatch.setattr(card_token_cipher, "_kek_cache", None)
    yield
    config_loader._param_cache.clear()
    monkeypatch.setattr(card_token_cipher, "_kek_cache", None)


def _b64_kek(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_original(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        ciphertext = encrypt("CT1")
        assert decrypt(ciphertext) == "CT1"

    def test_ciphertext_has_v1_prefix_and_differs_from_plaintext(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        ciphertext = encrypt("CT1")
        assert ciphertext.startswith("v1:")
        assert ciphertext != "CT1"

    def test_encrypt_is_nondeterministic_random_nonce(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert encrypt("CT1") != encrypt("CT1")


class TestPlaintextCompatibility:
    def test_decrypt_non_v1_prefixed_returns_as_is(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert decrypt("CT1") == "CT1"

    def test_encrypt_empty_string_untouched(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert encrypt("") == ""

    def test_encrypt_none_untouched(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert encrypt(None) is None

    def test_decrypt_empty_string_untouched(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert decrypt("") == ""

    def test_decrypt_none_untouched(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert decrypt(None) is None


class TestTamperDetection:
    def test_decrypt_tampered_ciphertext_raises(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        ciphertext = encrypt("CT1")
        payload = base64.b64decode(ciphertext[len("v1:"):])
        tampered = bytearray(payload)
        tampered[-1] ^= 0xFF  # 翻轉 tag 的最後一個 byte
        tampered_ciphertext = "v1:" + base64.b64encode(bytes(tampered)).decode()
        with pytest.raises(ValueError):
            decrypt(tampered_ciphertext)


class TestKekValidation:
    def test_wrong_length_kek_raises_on_encrypt(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"too-short"))
        with pytest.raises(RuntimeError):
            encrypt("CT1")

    def test_wrong_length_kek_raises_on_decrypt(self, monkeypatch):
        # 先用一把合法 KEK 產生密文，再切換成錯誤長度的 KEK 去解密。
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        ciphertext = encrypt("CT1")
        config_loader._param_cache.clear()
        monkeypatch.setattr(card_token_cipher, "_kek_cache", None)
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"still-too-short"))
        with pytest.raises(RuntimeError):
            decrypt(ciphertext)

    def test_missing_kek_raises(self, monkeypatch):
        monkeypatch.delenv("CARD_TOKEN_KEK", raising=False)
        with pytest.raises(RuntimeError):
            encrypt("CT1")

    def test_kek_is_lazily_cached_after_first_use(self, monkeypatch):
        monkeypatch.setenv("CARD_TOKEN_KEK", _b64_kek(b"0" * 32))
        assert card_token_cipher._kek_cache is None
        encrypt("CT1")
        assert card_token_cipher._kek_cache is not None
        # 換掉 env 也不影響已經 cache 的 KEK（lazy cache 慣例：第一次用時讀+驗，之後重用）。
        monkeypatch.delenv("CARD_TOKEN_KEK", raising=False)
        assert decrypt(encrypt("CT2")) == "CT2"
