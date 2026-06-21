"""密碼加密與驗證"""
import bcrypt
import hashlib
from typing import Optional


def hash_password(plain_password: str) -> str:
    """加密密碼

    Args:
        plain_password: 明文密碼

    Returns:
        加密後的密碼
    """
    # 生成 salt 並加密密碼 (work factor = 12)
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    """驗證密碼

    Args:
        plain_password: 明文密碼
        hashed_password: 加密後的密碼（OAuth-only 帳號為 None）

    Returns:
        是否匹配
    """
    # OAuth-only 帳號的 password_hash 為 None（見 src/routers/oauth.py），
    # 若直接 .encode() 會拋 AttributeError → login 變成未處理的 500。
    # 無密碼憑證一律視為驗證失敗，交由呼叫端回 401。
    if not hashed_password:
        return False
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def hash_token(token: str) -> str:
    """高 entropy token（verification / password reset）的 sha256 hash。

    與 hash_password 不同：
    - 不用 bcrypt：input 已是 secrets.token_urlsafe(32) 產的 256-bit secret，
      brute force 不可行，慢 hash 沒意義
    - 不用 salt：input 本身已 random
    - 用 sha256 hex（64 字元）方便 MongoDB 直接索引/比對

    用途僅限非密碼類 token；密碼一律走 hash_password。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
