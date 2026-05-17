"""JWT Token 處理"""
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from pydantic import BaseModel

from ..utils.config_loader import get_parameter

# JWT 配置（AWS 從 SSM 讀取，本地從環境變數）
SECRET_KEY = get_parameter("/transcriber/jwt-secret", fallback_env="JWT_SECRET_KEY", default="")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# 驗證 JWT_SECRET_KEY 是否設定
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY 環境變數未設定。\n"
        "請在 .env 檔案中設定：\n"
        "  JWT_SECRET_KEY=$(openssl rand -hex 32)\n"
        "或執行：openssl rand -hex 32 生成密鑰"
    )


def _shannon_entropy(s: str) -> float:
    """計算字串的 Shannon entropy（bits/char）。隨機 hex ~= 4.0，隨機 base64 ~= 5.5。"""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


# 密鑰強度檢查：格式 + 格式對應的 entropy 門檻
# - hex 格式（字元集 16）：理論最高 entropy 4.0，門檻 3.5
# - base64 格式（字元集 64）：理論最高 entropy 6.0，門檻 4.5（足以擋常見弱密碼）
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_BASE64_LIKE = re.compile(r"^[A-Za-z0-9+/=_-]{43,}$")
_entropy = _shannon_entropy(SECRET_KEY)

if _HEX_64.match(SECRET_KEY):
    _min_entropy = 3.5
elif _BASE64_LIKE.match(SECRET_KEY):
    _min_entropy = 4.5
else:
    raise RuntimeError(
        f"JWT_SECRET_KEY 格式不符（長度 {len(SECRET_KEY)}）。\n"
        f"必須是以下之一：\n"
        f"  - openssl rand -hex 32（64 字元 hex）\n"
        f"  - openssl rand -base64 32（44 字元 base64）"
    )

if _entropy < _min_entropy:
    raise RuntimeError(
        f"JWT_SECRET_KEY 熵過低（{_entropy:.2f} bits/char，需 >= {_min_entropy}）。\n"
        f"疑似低隨機性密碼，請執行：openssl rand -hex 32"
    )


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
