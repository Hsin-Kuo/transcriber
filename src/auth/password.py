"""密碼加密與驗證"""
import bcrypt


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


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """驗證密碼

    Args:
        plain_password: 明文密碼
        hashed_password: 加密後的密碼

    Returns:
        是否匹配
    """
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )
