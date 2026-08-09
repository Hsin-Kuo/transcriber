"""card_token 加密工具（金流體檢 P2-10）。

91APP 免 CVV 續扣憑證（card_token）原本以明文存在 `orders.card_token` /
`users.subscription.card_token`——這支模組把它改成 AES-256-GCM 密文，only
decrypt 於實際扣款那一點（見 `src/services/renewal_service.py`）。

**設計選型：SSM SecureString KEK + app 層 AES-GCM，而非 app 層 KMS envelope
encryption**：

- `config_loader.get_parameter()` 讀 SSM SecureString 早就帶 `WithDecryption=True`
  （經 KMS 解密），KEK 本身落地時已受 KMS 保護，不需要在應用層再包一層
  per-value KMS Encrypt/Decrypt round-trip（省掉一次 API call + 延遲，續扣是
  同步扣款路徑）。
- local 開發與 prod 走同一段 AES 程式碼（KEK 來源不同，運算邏輯相同），不需要
  為本地測試另外 mock KMS client。
- 版本前綴 `v1:` 讓未來若要輪替 KEK / 換演算法（例如導入真正的 KMS envelope）
  可以發 `v2:`，對存量資料做漸進式 re-encrypt，不用一次性 migration 卡關。

**絕不 log token 或 KEK 的值**——即使是錯誤訊息，也只帶「發生了什麼」不帶「值是
什麼」。呼叫端（routers/services）同樣不得把這個模組的輸出/輸入值寫進 log。
"""
import base64
from typing import Optional

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

from .config_loader import get_parameter

_VERSION_PREFIX = "v1:"
_KEK_BYTE_LEN = 32          # AES-256
_NONCE_BYTE_LEN = 12        # GCM 標準 nonce 長度
_TAG_BYTE_LEN = 16          # GCM auth tag 長度

# 模組級 lazy cache（比照 config_loader._ssm_client 的慣例）：第一次使用時讀取
# +驗證 KEK，之後重用，避免每次 encrypt/decrypt 都重打 SSM。
_kek_cache: Optional[bytes] = None


def _get_kek() -> bytes:
    """讀取並驗證 KEK（base64 編碼的 32 bytes）。

    `required=True`：prod-aws 若缺這把金鑰，fail-fast 直接 RuntimeError（P1-6
    語意）——不能讓 card_token 靜默退化成明文寫入。

    Raises:
        RuntimeError: 參數缺值，或 decode 後長度不是 32 bytes（fail-closed）。
    """
    global _kek_cache
    if _kek_cache is not None:
        return _kek_cache

    raw = get_parameter(
        "/transcriber/card-token-kek", fallback_env="CARD_TOKEN_KEK", required=True
    )
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as e:
        # 不带 raw 值：即使是格式錯誤也不能把可能的金鑰片段寫進例外訊息/log。
        raise RuntimeError("card token KEK is not valid base64") from e

    if len(key) != _KEK_BYTE_LEN:
        raise RuntimeError(
            f"card token KEK has invalid length (expected {_KEK_BYTE_LEN} bytes)"
        )

    _kek_cache = key
    return key


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """把明文 card_token 加密成 `v1:` 前綴的密文字串。

    空字串/None 原樣回傳——空 token 代表「無卡」，這個語意不該被加密掩蓋
    （呼叫端常用 `if not sub.get("card_token")` 判斷是否有卡）。
    """
    if not plaintext:
        return plaintext

    key = _get_kek()
    nonce = get_random_bytes(_NONCE_BYTE_LEN)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    payload = base64.b64encode(nonce + ct + tag).decode("ascii")
    return _VERSION_PREFIX + payload


def decrypt(stored: Optional[str]) -> Optional[str]:
    """把 `v1:` 密文解回明文；非 `v1:` 開頭者視為明文相容，原樣回傳。

    明文相容涵蓋：存量尚未 migrate 的資料、測試 fixture、空值/None。
    篡改偵測：GCM tag 驗證失敗會拋例外（`ValueError`，pycryptodome 的
    `decrypt_and_verify` 行為），呼叫端不應吞掉。
    """
    if not stored or not stored.startswith(_VERSION_PREFIX):
        return stored

    key = _get_kek()
    raw = base64.b64decode(stored[len(_VERSION_PREFIX):])
    nonce = raw[:_NONCE_BYTE_LEN]
    tag = raw[-_TAG_BYTE_LEN:]
    ct = raw[_NONCE_BYTE_LEN:-_TAG_BYTE_LEN]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ct, tag)
    return plaintext.decode("utf-8")
