"""update_speaker_names 端點回歸測試（XSS audit TODO-5）。

跟 test_batch_gating.py 同樣手法：直接呼叫 router 函式 + monkeypatch
TaskRepository，不起真的 Mongo。長度/數量/型別驗證本身由
SpeakerNamesUpdate（tests/models/test_speaker_names_update.py）覆蓋，這裡
只驗證端點把 body.root 正確餵給既有的改名流程，沒有因為換掉裸 dict 參數
而打壞現有行為。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import transcriptions  # noqa: E402
from src.models.transcription import SpeakerNamesUpdate  # noqa: E402

CURRENT_USER = {"_id": "507f1f77bcf86cd799439011", "email": "susan@example.com"}


@pytest.mark.asyncio
async def test_valid_payload_updates_and_returns_success(monkeypatch):
    captured = {}

    class _FakeTaskRepo:
        def __init__(self, db):
            pass

        async def get_by_id_and_user(self, task_id, user_id):
            return {"_id": task_id}

        async def update(self, task_id, updates):
            captured["task_id"] = task_id
            captured["updates"] = updates
            return True

    monkeypatch.setattr(transcriptions, "TaskRepository", _FakeTaskRepo)

    body = SpeakerNamesUpdate.model_validate({"SPEAKER_00": "張三", "SPEAKER_01": "李四"})
    result = await transcriptions.update_speaker_names(
        task_id="task-1", body=body, current_user=CURRENT_USER, db=object(),
    )

    assert captured["updates"] == {"speaker_names": {"SPEAKER_00": "張三", "SPEAKER_01": "李四"}}
    assert result["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_task_not_found_raises_404(monkeypatch):
    class _FakeTaskRepo:
        def __init__(self, db):
            pass

        async def get_by_id_and_user(self, task_id, user_id):
            return None

    monkeypatch.setattr(transcriptions, "TaskRepository", _FakeTaskRepo)

    body = SpeakerNamesUpdate.model_validate({"SPEAKER_00": "張三"})
    with pytest.raises(Exception) as exc:
        await transcriptions.update_speaker_names(
            task_id="missing", body=body, current_user=CURRENT_USER, db=object(),
        )
    assert "TRANSCRIPTION_TASK_NOT_FOUND" in str(exc.value) or "404" in str(exc.value)
