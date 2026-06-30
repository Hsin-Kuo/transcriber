"""reconcile_pinned_audio 單元測試。

驗證降級時：超額釘選音檔被釋放（keep_audio→False + audio_expires_at 寬限期），
保留最新完成的 N 個，且超額為 0 時 idempotent no-op。用 fake db / 不碰 S3 / 不寄信。
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.pinned_audio_reconciler import reconcile_pinned_audio  # noqa: E402


def _pinned_task(task_id: str, completed_at: int):
    return {
        "_id": task_id,
        "user": {"user_id": "u1"},
        "keep_audio": True,
        "result": {"audio_file": f"s3://b/uploads/pro/{task_id}.mp3"},
        "timestamps": {"completed_at": completed_at},
    }


def _make_db(pinned):
    """fake db：tasks.find→cursor.to_list 回 pinned；update_one 記錄呼叫。"""
    db = MagicMock()

    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=list(pinned))
    db.tasks.find = MagicMock(return_value=cursor)
    db.tasks.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

    db.users.find_one = AsyncMock(return_value={"_id": "u1", "email": "user@example.com"})
    return db


def _set_payload(call):
    """從 update_one 的 call 取出 $set dict。"""
    return call.args[1]["$set"]


@pytest.mark.asyncio
async def test_downgrade_to_free_releases_all_pins():
    now = int(time.time())
    pinned = [_pinned_task(f"t{i}", now - i * 86400) for i in range(5)]
    db = _make_db(pinned)
    mock_email = MagicMock()
    mock_email.send_audio_grace_period_email = AsyncMock(return_value=True)

    with patch("src.utils.storage.backend.is_aws", return_value=False), \
         patch("src.utils.email_service.get_email_service", return_value=mock_email):
        released = await reconcile_pinned_audio(db, "507f1f77bcf86cd799439011", "free")

    assert released == 5
    assert db.tasks.update_one.await_count == 5
    for call in db.tasks.update_one.await_args_list:
        payload = _set_payload(call)
        assert payload["keep_audio"] is False
        # free retention = 3 天，寬限期約 now + 3d
        assert abs(payload["audio_expires_at"] - (now + 3 * 86400)) < 120
    mock_email.send_audio_grace_period_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_downgrade_keeps_newest_n():
    now = int(time.time())
    # t0 最新、t4 最舊
    pinned = [_pinned_task(f"t{i}", now - i * 86400) for i in range(5)]
    db = _make_db(pinned)
    mock_email = MagicMock()
    mock_email.send_audio_grace_period_email = AsyncMock(return_value=True)

    with patch("src.utils.storage.backend.is_aws", return_value=False), \
         patch("src.utils.email_service.get_email_service", return_value=mock_email):
        # basic: max_keep_audio = 10 → 不會超額；用 pro=30 也不超額。
        # 要測部分超額，直接驗證「保留最新 2 個」需 max_keep=2。
        # QUOTA_TIERS 沒有 max_keep=2 的 tier，故改測 free(0) 已覆蓋全釋放；
        # 這裡驗證排序：釋放的是最舊的（t2,t3,t4），用 monkeypatched tier。
        from src.models import quota as quota_mod
        original = quota_mod.QUOTA_TIERS[quota_mod.QuotaTier.BASIC]["max_keep_audio"]
        quota_mod.QUOTA_TIERS[quota_mod.QuotaTier.BASIC]["max_keep_audio"] = 2
        try:
            released = await reconcile_pinned_audio(db, "507f1f77bcf86cd799439011", "basic")
        finally:
            quota_mod.QUOTA_TIERS[quota_mod.QuotaTier.BASIC]["max_keep_audio"] = original

    assert released == 3
    released_ids = {_set_payload(c) and c.args[0]["_id"] for c in db.tasks.update_one.await_args_list}
    assert released_ids == {"t2", "t3", "t4"}  # 最舊的 3 個


@pytest.mark.asyncio
async def test_no_op_when_within_quota():
    now = int(time.time())
    pinned = [_pinned_task("t0", now)]  # 1 個釘選
    db = _make_db(pinned)

    with patch("src.utils.storage.backend.is_aws", return_value=False):
        # pro max_keep=30 > 1 → no-op
        released = await reconcile_pinned_audio(db, "507f1f77bcf86cd799439011", "pro")

    assert released == 0
    db.tasks.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_tier_is_noop():
    db = _make_db([_pinned_task("t0", 1)])
    released = await reconcile_pinned_audio(db, "507f1f77bcf86cd799439011", "bogus")
    assert released == 0
    db.tasks.find.assert_not_called()
