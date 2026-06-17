"""回歸:batch_operations gating 必須用「DB 載來的完整 user(含 quota)」做檢查。

bug 史:`get_current_user` 為效能只回 JWT 內容、不含 quota；batch 端點原本直接
`has_feature(current_user, ...)` → 永遠 fallback 成 free → 連 Basic 以上也被 403。
修法:端點先 `UserRepository(db).get_by_id(...)` 載完整 user 再 has_feature。
本測試 monkeypatch has_feature 捕捉它收到的 user,確保是含 quota 的完整 user。
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

BASIC_USER = {
    "_id": "507f1f77bcf86cd799439011",
    "email": "susan@example.com",
    "quota": {"tier": "basic", "features": {"batch_operations": True}},
}
# get_current_user 實際回傳的形狀:只有 token 欄位,沒有 quota
TOKEN_ONLY_USER = {"_id": "507f1f77bcf86cd799439011", "email": "susan@example.com"}


@pytest.mark.asyncio
async def test_batch_gating_checks_full_user_not_token_user(monkeypatch):
    captured = {}

    class _FakeUserRepo:
        def __init__(self, db):
            pass

        async def get_by_id(self, user_id):
            return BASIC_USER

    def _fake_has_feature(user, feature):
        captured["user"] = user
        return True  # 放行,讓端點往下走（後續會因 mock 不全而拋例外，無妨）

    monkeypatch.setattr(transcriptions, "UserRepository", _FakeUserRepo)
    monkeypatch.setattr(transcriptions, "has_feature", _fake_has_feature)

    try:
        await transcriptions.create_batch_transcriptions(
            request=None, files=None, default_config="{}", overrides="{}",
            upload_ids=None, ui_language=None,
            current_user=TOKEN_ONLY_USER, db=object(), intake_service=None,
        )
    except Exception:
        pass  # 只關心 gating 階段傳給 has_feature 的 user

    # 關鍵斷言:has_feature 收到的是「含 quota 的完整 user」,不是 token-only
    assert captured.get("user") is BASIC_USER
    assert captured["user"]["quota"]["features"]["batch_operations"] is True


@pytest.mark.asyncio
async def test_batch_gating_rejects_when_feature_false(monkeypatch):
    """完整 user 但無 batch_operations(free)→ 必須 403。"""
    from fastapi import HTTPException

    class _FakeUserRepo:
        def __init__(self, db):
            pass

        async def get_by_id(self, user_id):
            return {"_id": "x", "quota": {"tier": "free", "features": {"batch_operations": False}}}

    monkeypatch.setattr(transcriptions, "UserRepository", _FakeUserRepo)

    with pytest.raises(HTTPException) as exc:
        await transcriptions.create_batch_transcriptions(
            request=None, files=None, default_config="{}", overrides="{}",
            upload_ids=None, ui_language=None,
            current_user=TOKEN_ONLY_USER, db=object(), intake_service=None,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "FEATURE_NOT_AVAILABLE"
