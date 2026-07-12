"""download_audio 改讀 httpOnly cookie 後的硬切換規格測試（XSS audit
TODO-8 方案 B）。

跟 get_current_user 不同，這個端點原本自己寫了一份雙模式驗證（沒有共用
共用 dependency），所以需要單獨測——這正是深挖評估時特別點名的一處。

跟 tests/routers/test_batch_gating.py 同樣手法：monkeypatch
TaskRepository，只驗證到「認證通過、進到任務查詢」這一步（用 task not
found 當認證成功的訊號），不起真的 Mongo、不測後面的 S3/檔案回應邏輯。
"""
import inspect
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import transcriptions  # noqa: E402
from src.auth.jwt_handler import create_access_token  # noqa: E402

_PAYLOAD = {"sub": "507f1f77bcf86cd799439011", "email": "susan@example.com", "role": "user"}


class _FakeRequest:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


class _FakeTaskRepoTaskNotFound:
    def __init__(self, db):
        pass

    async def get_by_id_and_user(self, task_id, user_id):
        return None


@pytest.mark.asyncio
async def test_missing_cookie_raises_401():
    with pytest.raises(HTTPException) as exc:
        await transcriptions.download_audio(task_id="t1", request=_FakeRequest(), db=object())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_cookie_raises_401():
    request = _FakeRequest(cookies={"access_token": "garbage.not.a.jwt"})
    with pytest.raises(HTTPException) as exc:
        await transcriptions.download_audio(task_id="t1", request=request, db=object())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_valid_cookie_reaches_task_lookup(monkeypatch):
    """驗證 cookie 有效時真的會往下走到資料庫查詢（用 404 task-not-found
    當「認證這關過了」的訊號，而不是卡在 401）。"""
    monkeypatch.setattr(transcriptions, "TaskRepository", _FakeTaskRepoTaskNotFound)
    token, _ = create_access_token(_PAYLOAD)
    request = _FakeRequest(cookies={"access_token": token})

    with pytest.raises(HTTPException) as exc:
        await transcriptions.download_audio(task_id="t1", request=request, db=object())
    assert exc.value.status_code == 404, (
        f"預期認證通過後卡在 404 task-not-found，實際卻是 {exc.value.status_code}"
        f"（detail={exc.value.detail}）——代表認證這關可能沒過"
    )


@pytest.mark.asyncio
async def test_query_token_and_authorization_header_no_longer_in_signature():
    """回歸守衛：舊版靠 ?token= 查詢參數或 Authorization header 認證
    （因為 <audio> 元素不支援自訂 header），這裡確認兩者都已經從函式簽名
    移除——認證完全改走 httpOnly cookie，不再有任何 token-in-URL 曝露面。"""
    sig = inspect.signature(transcriptions.download_audio)
    assert "token" not in sig.parameters
    assert "credentials" not in sig.parameters
