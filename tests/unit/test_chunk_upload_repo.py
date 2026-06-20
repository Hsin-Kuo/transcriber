"""ChunkUploadRepository 測試。

需要連得到的 MongoDB（MONGODB_URL 或 localhost:27020），連不上整組 skip。

覆蓋重點：
- sweep_expired 邊界 race（refactor 時自己引入過的 bug）
- consume 的 atomic 行為（findOneAndDelete）
- add_chunk 的 $addToSet 原子性
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from src.database.repositories.chunk_upload_repo import ChunkUploadRepository  # noqa: E402

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = "transcriber_test"


def _mongo_available() -> bool:
    if MongoClient is None:
        return False
    try:
        c = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=1000)
        c.admin.command("ping")
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}"
)


@pytest.fixture
async def repo():
    client = AsyncIOMotorClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    db = client[_TEST_DB]
    await db.chunk_uploads.delete_many({})
    yield ChunkUploadRepository(db)
    await db.chunk_uploads.delete_many({})
    client.close()


async def _init(repo, *, user_id="u1", total_chunks=3, filename="a.mp3") -> str:
    upload_id = str(uuid.uuid4())
    await repo.init_upload(
        upload_id=upload_id,
        user_id=user_id,
        filename=filename,
        total_size=total_chunks * 1024,
        total_chunks=total_chunks,
        temp_dir=Path("/tmp/test"),
    )
    return upload_id


# ── add_chunk 原子性 ────────────────────────────────────


async def test_add_chunk_concurrent_same_index_no_duplication(repo):
    """同一 chunk_index 被並發呼叫多次，received 只記一次（$addToSet）"""
    uid = await _init(repo)
    await asyncio.gather(*[repo.add_chunk(uid, "u1", 0) for _ in range(5)])
    doc = await repo.get(uid)
    assert doc["received"] == [0]


async def test_add_chunk_concurrent_different_indices_all_recorded(repo):
    """不同 chunk_index 並發寫入全部都記錄"""
    uid = await _init(repo, total_chunks=5)
    await asyncio.gather(*[repo.add_chunk(uid, "u1", i) for i in range(5)])
    doc = await repo.get(uid)
    assert sorted(doc["received"]) == [0, 1, 2, 3, 4]


async def test_add_chunk_rejects_wrong_user(repo):
    """user_id 不符 → 回 None、不更新 doc"""
    uid = await _init(repo, user_id="u1")
    result = await repo.add_chunk(uid, "attacker", 0)
    assert result is None
    doc = await repo.get(uid)
    assert doc["received"] == []


async def test_add_chunk_on_deleted_doc_returns_none(repo):
    """doc 被刪後 add_chunk 回 None — uploads.upload_chunk 用這個訊號回 409"""
    uid = await _init(repo)
    await repo.delete(uid)
    result = await repo.add_chunk(uid, "u1", 0)
    assert result is None


# ── consume atomic ──────────────────────────────────────


async def test_consume_only_succeeds_once_under_concurrent_calls(repo):
    """並發 consume 同一 completed upload，只有一個拿到 doc"""
    uid = await _init(repo)
    await repo.mark_completed(uid, Path("/tmp/test/a.mp3"))

    results = await asyncio.gather(*[repo.consume(uid, "u1") for _ in range(10)])
    won = [r for r in results if r is not None]
    assert len(won) == 1, f"expected exactly 1 winner, got {len(won)}"


async def test_consume_skips_uploading_status(repo):
    """status=uploading（未完成）不能被 consume"""
    uid = await _init(repo)
    result = await repo.consume(uid, "u1")
    assert result is None
    # doc 仍應存在
    assert await repo.get(uid) is not None


async def test_consume_rejects_wrong_user(repo):
    """user_id 不符 → 回 None、doc 仍在"""
    uid = await _init(repo, user_id="u1")
    await repo.mark_completed(uid, Path("/tmp/test/a.mp3"))
    result = await repo.consume(uid, "attacker")
    assert result is None
    assert await repo.get(uid) is not None


# ── sweep_expired 邊界 race ─────────────────────────────


async def test_sweep_expired_does_not_delete_recently_active(repo):
    """關鍵 race 測試：sweep find 抓到的 doc 在 delete 之前若被 add_chunk
    更新 last_activity_at，不該被誤刪。"""
    uid = await _init(repo)

    # 人為把 last_activity_at 拉到 1 小時前（grace=1800s 下會被 find 抓到）
    old_time = datetime.now(timezone.utc) - timedelta(seconds=3600)
    await repo.collection.update_one(
        {"_id": uid}, {"$set": {"last_activity_at": old_time}}
    )

    # 模擬 sweep find 跟 delete 之間有 add_chunk 跑進來：先把 doc 拉回現代
    await repo.add_chunk(uid, "u1", 0)  # 這會把 last_activity_at 更新為 now

    # sweep 應該不刪這個 doc（last_activity_at 已被更新到 < grace_seconds 內）
    deleted = await repo.sweep_expired(grace_seconds=1800)
    assert deleted == []
    assert await repo.get(uid) is not None, "doc 不該被誤刪"


async def test_sweep_expired_deletes_truly_old_doc(repo):
    """真的過期的 doc 該被刪掉。"""
    uid = await _init(repo)
    old_time = datetime.now(timezone.utc) - timedelta(seconds=7200)
    await repo.collection.update_one(
        {"_id": uid}, {"$set": {"last_activity_at": old_time}}
    )

    deleted = await repo.sweep_expired(grace_seconds=3600)
    assert len(deleted) == 1
    assert deleted[0]["_id"] == uid
    assert await repo.get(uid) is None


async def test_sweep_expired_returns_only_actually_deleted(repo):
    """sweep_expired 只回傳真的被刪掉的 doc — caller rmtree temp_dir 才不會出錯。

    場景：find 抓到 N 個 doc，但其中部分在 delete 前被更新（race），
    回傳 list 必須只含真的被 delete_one 移除的，不能含被 race 救起來的。
    """
    # 3 個過期 doc
    uids = [await _init(repo) for _ in range(3)]
    old_time = datetime.now(timezone.utc) - timedelta(seconds=7200)
    await repo.collection.update_many(
        {"_id": {"$in": uids}}, {"$set": {"last_activity_at": old_time}}
    )

    # 救活其中一個
    await repo.add_chunk(uids[1], "u1", 0)

    deleted = await repo.sweep_expired(grace_seconds=3600)
    deleted_ids = {d["_id"] for d in deleted}
    assert deleted_ids == {uids[0], uids[2]}, "只有真的被刪的才該回傳"
    assert await repo.get(uids[1]) is not None, "活著的 doc 不該被刪"
    assert await repo.get(uids[0]) is None
    assert await repo.get(uids[2]) is None


# ── take_incomplete_for_retry（init 重試覆蓋）─────────────


async def test_take_incomplete_evicts_same_signature(repo):
    """同 user、同檔名同大小、status=uploading 的舊 session 被取走並回傳。"""
    uid = await _init(repo, user_id="u1", total_chunks=3, filename="a.mp3")
    total_size = 3 * 1024  # 對齊 _init 的 total_size 算法

    deleted = await repo.take_incomplete_for_retry("u1", "a.mp3", total_size)

    assert [d["_id"] for d in deleted] == [uid]
    assert "temp_dir" in deleted[0], "回傳須含 temp_dir 供 caller rmtree"
    assert await repo.get(uid) is None, "舊 session 應已被刪"


async def test_take_incomplete_ignores_different_filename(repo):
    """不同檔名不視為同一次重試 → 不清。"""
    uid = await _init(repo, user_id="u1", total_chunks=3, filename="other.mp3")
    deleted = await repo.take_incomplete_for_retry("u1", "a.mp3", 3 * 1024)
    assert deleted == []
    assert await repo.get(uid) is not None


async def test_take_incomplete_ignores_different_total_size(repo):
    """同檔名但大小不同（內容已換）→ 不清。"""
    uid = await _init(repo, user_id="u1", total_chunks=3, filename="a.mp3")  # size=3072
    deleted = await repo.take_incomplete_for_retry("u1", "a.mp3", 9999)
    assert deleted == []
    assert await repo.get(uid) is not None


async def test_take_incomplete_ignores_other_user(repo):
    """別的 user 的同名上傳不可被清（隔離）。"""
    uid = await _init(repo, user_id="u2", total_chunks=3, filename="a.mp3")
    deleted = await repo.take_incomplete_for_retry("u1", "a.mp3", 3 * 1024)
    assert deleted == []
    assert await repo.get(uid) is not None


async def test_take_incomplete_skips_completed(repo):
    """completed-but-not-consumed 的成品不該被清（交給 consume / sweep）。"""
    uid = await _init(repo, user_id="u1", total_chunks=3, filename="a.mp3")
    await repo.mark_completed(uid, Path("/tmp/test/a.mp3"))
    deleted = await repo.take_incomplete_for_retry("u1", "a.mp3", 3 * 1024)
    assert deleted == []
    assert await repo.get(uid) is not None


async def test_sweep_expired_protects_against_find_then_delete_race(repo, monkeypatch):
    """關鍵 race：find() 回傳 doc 後、find_one_and_delete 前，add_chunk 跑進來
    更新 last_activity_at。原始實作（delete_many 不二次驗證）會誤刪此 doc；
    現在實作（find_one_and_delete 帶 last_activity_at 條件）必須保護它。
    """
    uid = await _init(repo)
    old_time = datetime.now(timezone.utc) - timedelta(seconds=7200)
    await repo.collection.update_one(
        {"_id": uid}, {"$set": {"last_activity_at": old_time}}
    )

    # Monkeypatch：第一次 find_one_and_delete 被呼叫前，先 race-update 把 doc
    # 拉回現代。模擬 sweep find 完了、要刪之前突然有 chunk 進來。
    original = repo.collection.find_one_and_delete
    raced = {"done": False}

    async def racy_delete(query, **kwargs):
        if not raced["done"]:
            raced["done"] = True
            await repo.add_chunk(uid, "u1", 0)
        return await original(query, **kwargs)

    monkeypatch.setattr(repo.collection, "find_one_and_delete", racy_delete)

    deleted = await repo.sweep_expired(grace_seconds=3600)
    assert deleted == [], "race-update 後的 doc 不該被誤刪"
    assert await repo.get(uid) is not None, "doc 必須仍在"
