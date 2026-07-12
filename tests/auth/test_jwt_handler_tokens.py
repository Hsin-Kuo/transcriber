"""create_access_token / verify_token 測試（access token httpOnly 遷移）。

涵蓋：
- create_access_token 回傳 (token, expires_at_ms) tuple，expires_at_ms
  跟 JWT payload 裡實際的 exp claim（UTC epoch 秒）換算一致——這裡曾經
  踩過 naive datetime + .timestamp() 在非 UTC 時區機器上算錯 8 小時的雷，
  用 calendar.timegm 修正，這裡鎖住不要回退。
- verify_token 回傳的 TokenData.exp 同樣要跟 JWT payload 的 exp claim
  一致（原本用 datetime.fromtimestamp 也有一樣的時區誤判，已改
  datetime.utcfromtimestamp 修正，順手鎖住）。
"""
import calendar
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from jose import jwt  # noqa: E402

from src.auth.jwt_handler import (  # noqa: E402
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    verify_token,
)

_PAYLOAD = {"sub": "u1", "email": "a@b.com", "role": "user"}


class TestCreateAccessToken:
    def test_returns_token_and_expires_at_tuple(self):
        result = create_access_token(_PAYLOAD)
        assert isinstance(result, tuple)
        assert len(result) == 2
        token, expires_at_ms = result
        assert isinstance(token, str)
        assert isinstance(expires_at_ms, int)

    def test_expires_at_matches_raw_jwt_exp_claim(self):
        """expires_at_ms 必須跟 JWT payload 裡的原始 exp claim（UTC epoch 秒）
        換算後完全一致——不能靠 datetime.timestamp() 這種會被本地時區污染
        的轉法，那個在非 UTC 機器上會整整差 8 小時。"""
        token, expires_at_ms = create_access_token(_PAYLOAD)
        raw_payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert raw_payload["exp"] * 1000 == expires_at_ms

    def test_expires_at_is_roughly_expire_minutes_from_now(self):
        import time
        token, expires_at_ms = create_access_token(_PAYLOAD)
        now_ms = int(time.time() * 1000)
        expected_delta_ms = ACCESS_TOKEN_EXPIRE_MINUTES * 60 * 1000
        # 給 5 秒容錯（測試執行耗時）
        assert abs((expires_at_ms - now_ms) - expected_delta_ms) < 5000


class TestVerifyTokenExpFieldConsistency:
    def test_verify_token_exp_matches_expires_at(self):
        """verify_token 回傳的 TokenData.exp 換算回 epoch ms 後，必須跟
        create_access_token 回傳的 expires_at_ms 一致——兩者理應是同一個
        時間點的兩種表示法。"""
        token, expires_at_ms = create_access_token(_PAYLOAD)
        token_data = verify_token(token, "access")
        assert token_data is not None
        exp_ms_from_verify = calendar.timegm(token_data.exp.utctimetuple()) * 1000
        assert exp_ms_from_verify == expires_at_ms
