"""JWT_SECRET_KEY 強度驗證測試（B5）。

驗證重點：
- 真實 openssl rand 輸出可通過
- 弱密鑰（短、重複、辭典）被擋下
- 格式檢查 + entropy 雙閘門都生效

注意：jwt_handler.py 在 import 時就驗 SECRET_KEY，所以這裡用 subprocess
跑獨立 Python 進程，每個案例設不同環境變數來測 raise 行為。
"""
import os
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _run_import(secret: str) -> subprocess.CompletedProcess:
    """子進程設 JWT_SECRET_KEY 並 import jwt_handler；exit 0 表示通過。"""
    script = textwrap.dedent(
        f"""
        import os
        os.environ['JWT_SECRET_KEY'] = {secret!r}
        os.environ.pop('AWS_REGION', None)  # 不要走 SSM
        from src.auth import jwt_handler  # noqa: F401
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )


# 真實 openssl rand 輸出（hex / base64）
REAL_HEX_64 = "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2"
REAL_B64_44 = "oA9KZmJ4qPq9rL6JxN3pCYvSWMzL2EjUqXa7pIVZQRA="


class TestStrongKeysPass:
    def test_real_openssl_hex(self):
        result = _run_import(REAL_HEX_64)
        assert result.returncode == 0, result.stderr

    def test_real_openssl_base64(self):
        result = _run_import(REAL_B64_44)
        assert result.returncode == 0, result.stderr


class TestWeakKeysRejected:
    @pytest.mark.parametrize("bad_secret,reason", [
        ("", "empty"),
        ("a" * 32, "too short for hex"),
        ("a" * 64, "64 hex chars but low entropy"),
        ("kJ8sH3mN9xQ2vP5wR7tY", "20 chars random, too short"),
        ("MySuperSecretJwtKey123MySuperSecretJwtKey123", "long but low entropy / dictionary"),
        ("password" * 8, "repeated dictionary word"),
    ])
    def test_rejected(self, bad_secret, reason):
        result = _run_import(bad_secret)
        assert result.returncode != 0, f"應被拒絕（{reason}）但通過了"
        assert "JWT_SECRET_KEY" in result.stderr
