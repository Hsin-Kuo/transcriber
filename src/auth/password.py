"""密碼加密與驗證"""
from passlib.context import CryptContext

# 密碼加密上下文
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # 工作因子，平衡安全與效能
)


def hash_password(plain_password: str) -> str:
    """加密密碼"""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """驗證密碼"""
    return pwd_context.verify(plain_password, hashed_password)
