"""JWT Token 處理"""
import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from pydantic import BaseModel

# JWT 配置（從環境變數讀取）
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-here")  # 生產環境必須設定
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))


class TokenData(BaseModel):
    """Token 解析後的資料"""
    user_id: str
    email: str
    role: str
    exp: datetime


def create_access_token(data: dict) -> str:
    """生成 Access Token

    Args:
        data: Token 資料，應包含 sub (user_id), email, role

    Returns:
        JWT Token 字串
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """生成 Refresh Token

    Args:
        data: Token 資料，應包含 sub (user_id), email

    Returns:
        JWT Token 字串
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str, token_type: str = "access") -> Optional[TokenData]:
    """驗證並解析 Token

    Args:
        token: JWT Token 字串
        token_type: Token 類型 ("access" 或 "refresh")

    Returns:
        TokenData 物件，驗證失敗返回 None
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        # 檢查 Token 類型
        if payload.get("type") != token_type:
            return None

        return TokenData(
            user_id=payload.get("sub"),
            email=payload.get("email"),
            role=payload.get("role", "user"),
            exp=datetime.fromtimestamp(payload.get("exp"))
        )
    except JWTError:
        return None
