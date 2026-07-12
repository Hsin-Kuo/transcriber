"""JWT Token 處理"""
import calendar
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


def create_access_token(data: dict) -> tuple[str, int]:
    """生成 Access Token

    Args:
        data: Token 資料，應包含 sub (user_id), email, role

    Returns:
        (JWT Token 字串, 過期時間 UTC epoch 毫秒)——過期時間單獨回傳供呼叫端
        塞進 TokenResponse.expires_at，前端靠這個時間戳判斷是否該主動
        refresh，不需要（也讀不到，httpOnly cookie 下）解析 JWT payload。

        注意：用 calendar.timegm(expire.utctimetuple()) 而非
        expire.timestamp()——expire 是 datetime.utcnow() 產生的 naive
        datetime（沒有 tzinfo），.timestamp() 會誤當成「本地時區時間」轉換，
        在非 UTC 時區的機器上（例如本地開發常見的 UTC+8）算出來的 epoch
        會整整差 8 小時。timegm 明確把 tuple 當 UTC 處理，才是正確轉法。
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    expires_at_ms = calendar.timegm(expire.utctimetuple()) * 1000
    return token, expires_at_ms


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
            # utcfromtimestamp，不是 fromtimestamp——後者會把 epoch 誤當本地
            # 時區轉換，非 UTC 時區的機器（如本機 UTC+8）算出來的 naive
            # datetime 會整整差 8 小時。目前沒有任何呼叫端讀這個欄位（純
            # 附帶修正，不影響現有行為——過期檢查由 jwt.decode 內部處理，
            # 走的是 JWT payload 原始數值，不受這裡影響）。
            exp=datetime.utcfromtimestamp(payload.get("exp"))
        )
    except JWTError:
        return None
