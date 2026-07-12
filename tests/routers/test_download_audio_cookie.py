"""download_audio 端點測試（XSS audit TODO-8 方案 B 後續清理）。

這個端點原本自己寫了一份跟 get_current_user 重複的雙模式驗證（header
或 ?token= 查詢參數），code review 抓到後已收斂成
`current_user: dict = Depends(get_current_user)`，不再自己讀 cookie/驗
token。cookie/header/query-token 的認證行為改由
tests/auth/test_get_current_user_cookie.py 覆蓋（那邊測的是共用邏輯，
這裡不重複測）；這裡只驗證 download_audio 自己的「拿 current_user 查
任務」這段 wiring，以及鎖住「不再有 token-in-URL 參數」這個規格。

跟 tests/routers/test_batch_gating.py 同樣手法：monkeypatch
TaskRepository，不起真的 Mongo。
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

CURRENT_USER = {"_id": "507f1f77bcf86cd799439011", "email": "susan@example.com"}


class _FakeTaskRepoTaskNotFound:
    def __init__(self, db):
        pass

    async def get_by_id_and_user(self, task_id, user_id):
        return None


class _FakeTaskRepoRecordsCall:
    def __init__(self, db):
        pass

    async def get_by_id_and_user(self, task_id, user_id):
        _FakeTaskRepoRecordsCall.last_call = (task_id, user_id)
        return None  # 404 之後的邏輯不在這個測試範圍內，不用真的回一個 task


@pytest.mark.asyncio
async def test_uses_current_user_id_to_look_up_task(monkeypatch):
    """驗證 download_audio 真的把 current_user["_id"] 轉成字串傳給
    get_by_id_and_user，跟其他端點的既有慣例一致（見 transcriptions.py
    其他端點的 str(current_user["_id"]) 呼叫）。"""
    monkeypatch.setattr(transcriptions, "TaskRepository", _FakeTaskRepoRecordsCall)

    with pytest.raises(HTTPException):
        await transcriptions.download_audio(task_id="t1", current_user=CURRENT_USER, db=object())

    assert _FakeTaskRepoRecordsCall.last_call == ("t1", str(CURRENT_USER["_id"]))


@pytest.mark.asyncio
async def test_task_not_found_raises_404(monkeypatch):
    monkeypatch.setattr(transcriptions, "TaskRepository", _FakeTaskRepoTaskNotFound)

    with pytest.raises(HTTPException) as exc:
        await transcriptions.download_audio(task_id="t1", current_user=CURRENT_USER, db=object())
    assert exc.value.status_code == 404


def test_no_longer_has_its_own_token_in_url_auth_params():
    """回歸守衛：舊版靠 ?token= 查詢參數或 Authorization header 認證
    （因為 <audio> 元素不支援自訂 header），這裡確認函式簽名裡沒有這些
    參數、也沒有自己的 request 物件——認證完全交給共用的 get_current_user
    （httpOnly cookie），不再有獨立的 token-in-URL 曝露面或重複的驗證
    邏輯。"""
    sig = inspect.signature(transcriptions.download_audio)
    assert "token" not in sig.parameters
    assert "credentials" not in sig.parameters
    assert "request" not in sig.parameters
    assert "current_user" in sig.parameters
