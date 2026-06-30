#!/usr/bin/env python3
"""
測試帳號 Seed / Reset 腳本

建立四個方案的測試帳號，usage 預設接近方案上限，方便測試邊界情境。
每個帳號附 (max_keep_audio + 1) 筆已完成的 mock 示範任務（含 transcription +
segments），讓釘選音檔可以測到「釘滿上限再多 1 筆」的邊界。
enterprise 無釘選上限，固定給 1 筆。

每筆任務都會上傳一個「真的存在」的假音檔（靜音 mp3）到儲存層（AWS 走 S3
uploads/{tier}/{task_id}.mp3、local 走 uploads/），並把路徑寫進
task.result.audio_file —— 讓下載 / 播放 / 釘選都能實測。mock task 的 _id
採 deterministic UUID（pin 時 move_audio 會驗 UUID 格式，非 UUID 會炸）。

使用方式：
    python scripts/seed_test_users.py            # upsert（新增或完整覆蓋）
    python scripts/seed_test_users.py --reset    # 重置 usage / tokens / 示範任務
    python scripts/seed_test_users.py --list     # 列出目前狀態
    python scripts/seed_test_users.py --dry-run  # 不寫入，只印出將要做的事

帳號密碼一律：TestUser@123
"""

import os
import sys
import uuid
import tempfile
import argparse
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pymongo import MongoClient, ReplaceOne, UpdateOne
from dotenv import load_dotenv

load_dotenv(project_root / ".env")

# ── 測試帳號定義 ─────────────────────────────────────────────────────────────
# near_limit_usage：接近該方案上限的 usage，讓測試時直接面對邊界情境
# FREE  : 180 min / 3 AI   → 剩 10 min / 1 AI
# BASIC : 600 min / 30 AI  → 剩 30 min / 2 AI
# PRO   : 3000 min / 100 AI → 剩 150 min / 5 AI
# ENTERPRISE : 無上限，usage 歸零（上限測試不適用）

TEST_USERS = [
    {
        "email": "test.free@soundlite.app",
        "tier": "free",
        "near_limit_usage": {"duration_minutes": 170.0, "ai_summaries": 2},
    },
    {
        "email": "test.basic@soundlite.app",
        "tier": "basic",
        "near_limit_usage": {"duration_minutes": 595.0, "ai_summaries": 29},
    },
    {
        "email": "test.pro@soundlite.app",
        "tier": "pro",
        "near_limit_usage": {"duration_minutes": 2995.0, "ai_summaries": 99},
    },
    {
        "email": "test.enterprise@soundlite.app",
        "tier": "enterprise",
        "near_limit_usage": {"duration_minutes": 0.0, "ai_summaries": 0},
    },
]

TEST_PASSWORD = "TestUser@123"

# 方案配額（對齊 src/models/quota.py QUOTA_TIERS）
QUOTA_BY_TIER = {
    "free": {
        "tier": "free",
        "max_transcriptions": 999999,
        "max_duration_minutes": 180,
        "max_concurrent_tasks": 1,
        "max_ai_summaries": 3,
        "audio_retention_days": 3,
        "max_keep_audio": 0,
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": False,
            "priority_processing": False,
        },
    },
    "basic": {
        "tier": "basic",
        "max_transcriptions": 999999,
        "max_duration_minutes": 600,
        "max_concurrent_tasks": 2,
        "max_ai_summaries": 30,
        "audio_retention_days": 7,
        "max_keep_audio": 10,
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": True,
            "priority_processing": False,
        },
    },
    "pro": {
        "tier": "pro",
        "max_transcriptions": 999999,
        "max_duration_minutes": 3000,
        "max_concurrent_tasks": 5,
        "max_ai_summaries": 100,
        "audio_retention_days": 7,
        "max_keep_audio": 30,
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": True,
            "priority_processing": True,
        },
    },
    "enterprise": {
        "tier": "enterprise",
        "max_transcriptions": 999999,
        "max_duration_minutes": 999999,
        "max_concurrent_tasks": 10,
        "max_ai_summaries": 999999,
        "audio_retention_days": 7,
        "max_keep_audio": 999999,
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": True,
            "priority_processing": True,
        },
    },
}

# ── 示範任務內容 ─────────────────────────────────────────────────────────────
# 兩人對談，含說話者辨識（SPEAKER_00 主持人 / SPEAKER_01 來賓）
# 讓前端可以看到完整的轉錄畫面：時間軸、說話者標籤、段落文字

MOCK_TASK_CONTENT = (
    "歡迎使用 SoundLite 語音轉文字服務，今天我來示範幾個主要功能。"
    "請問這個服務支援哪些語言？"
    "我們支援中文、英文、日文等多種語言，系統會自動偵測，也可以手動指定。"
    "那說話者辨識是怎麼運作的？"
    "上傳音檔後，系統會自動分析聲紋，把不同說話者的片段分開標記，就像您現在看到的這樣。"
    "轉錄完成後還可以做什麼？"
    "您可以下載純文字稿或帶時間軸的字幕檔，也可以用 AI 摘要快速掌握重點，或是加標籤做分類管理。"
    "感覺很實用，謝謝示範！"
    "歡迎使用，有任何問題都可以透過右上角的說明聯絡我們。"
)

MOCK_TASK_SEGMENTS = [
    {"start": 0.0,  "end": 6.8,  "text": "歡迎使用 SoundLite 語音轉文字服務，今天我來示範幾個主要功能。", "speaker": "SPEAKER_00"},
    {"start": 7.2,  "end": 11.0, "text": "請問這個服務支援哪些語言？",                                    "speaker": "SPEAKER_01"},
    {"start": 11.5, "end": 19.3, "text": "我們支援中文、英文、日文等多種語言，系統會自動偵測，也可以手動指定。", "speaker": "SPEAKER_00"},
    {"start": 19.8, "end": 23.5, "text": "那說話者辨識是怎麼運作的？",                                   "speaker": "SPEAKER_01"},
    {"start": 24.0, "end": 33.2, "text": "上傳音檔後，系統會自動分析聲紋，把不同說話者的片段分開標記，就像您現在看到的這樣。", "speaker": "SPEAKER_00"},
    {"start": 33.7, "end": 37.4, "text": "轉錄完成後還可以做什麼？",                                     "speaker": "SPEAKER_01"},
    {"start": 37.9, "end": 49.6, "text": "您可以下載純文字稿或帶時間軸的字幕檔，也可以用 AI 摘要快速掌握重點，或是加標籤做分類管理。", "speaker": "SPEAKER_00"},
    {"start": 50.1, "end": 53.0, "text": "感覺很實用，謝謝示範！",                                       "speaker": "SPEAKER_01"},
    {"start": 53.5, "end": 60.8, "text": "歡迎使用，有任何問題都可以透過右上角的說明聯絡我們。",           "speaker": "SPEAKER_00"},
]


# ── 假音檔（靜音 mp3）──────────────────────────────────────────────────────────
# 產生一個結構合法的 MPEG-1 Layer III 靜音 mp3（~60.8s，對齊 segments 時間軸）：
#   frame header 0xFF 0xFB 0x90 0x00 = MPEG1 L3 / 128kbps / 44.1kHz / stereo
#   → 每 frame 417 bytes（4 byte header + 413 byte 全 0 payload，解碼為靜音）。
# 這樣下載端點 head_object 查得到、瀏覽器載得進、播放軸長度也對得上字幕。

def _build_fake_mp3() -> bytes:
    id3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"          # 空 ID3v2.4 tag（size=0）
    frame = b"\xff\xfb\x90\x00" + b"\x00" * (417 - 4)
    n_frames = 2328                                    # 2328 * 1152 / 44100 ≈ 60.8s
    return id3 + frame * n_frames


_FAKE_MP3 = _build_fake_mp3()
_FAKE_MP3_SIZE_MB = round(len(_FAKE_MP3) / (1024 * 1024), 2)


def _check_storage(dry_run: bool) -> None:
    """印出儲存模式並在 AWS 模式缺 S3_BUCKET 時直接擋下（避免上傳到空 bucket）。"""
    if dry_run:
        return
    from src.utils.storage.backend import S3_BUCKET, is_aws
    if is_aws():
        if not S3_BUCKET:
            raise RuntimeError("DEPLOY_ENV=aws 但 S3_BUCKET 未設定，無法上傳假音檔")
        print(f"📦 假音檔儲存模式：AWS S3（bucket={S3_BUCKET}）")
    else:
        print("📦 假音檔儲存模式：local（uploads/ 目錄）")


def _store_fake_audio(task_id: str, tier: str) -> str:
    """上傳一份假音檔到儲存層，回傳儲存路徑（s3:// URI 或本地路徑）。

    走 app 自己的 save_audio()：與正式上傳同一條路徑（同 key 規則 / 同 env），
    並會 validate_task_id（task_id 為 UUID 才過）。
    """
    from src.utils.storage.compact import save_audio
    fd, tmp = tempfile.mkstemp(suffix=".mp3")
    with os.fdopen(fd, "wb") as f:
        f.write(_FAKE_MP3)
    tmp_path = Path(tmp)
    try:
        return save_audio(task_id, tmp_path, tier=tier)
    finally:
        tmp_path.unlink(missing_ok=True)  # save_audio 已 move/unlink；保險清殘留


# mock task 的 _id 用 deterministic UUID（uuid5）：
#   - 釘選音檔走 move_audio()，它會 validate_task_id() 強制 UUID 格式，
#     舊版字串 id（test-demo-task-*）一 pin 就 ValueError，所以必須是 UUID。
#   - 用固定 namespace + (tier, idx) 衍生 → 每次 seed 得到同一組 id，維持冪等。
_MOCK_TASK_NS = uuid.UUID("5eed0000-0000-4000-8000-5e6d11fe0000")  # 固定 namespace


def _mock_task_id(tier: str, idx: int) -> str:
    return str(uuid.uuid5(_MOCK_TASK_NS, f"soundlite-demo-{tier}-{idx}"))


def _mock_task_id_pattern(tier: str) -> dict:
    """舊版字串 id（test-demo-task-{tier}[-idx]）的 regex，用於清理 deploy 過的殘留。"""
    return {"$regex": f"^test-demo-task-{tier}(-|$)"}


def _mock_task_filter(tier: str) -> dict:
    """match 該 tier 的所有 seed mock 任務：新版 seed_mock marker + 舊版字串 id。"""
    return {"$or": [
        {"seed_mock": True, "seed_tier": tier},
        {"_id": _mock_task_id_pattern(tier)},
    ]}


def _mock_task_count(tier: str) -> int:
    """mock 任務數 = 可釘選音檔上限 (max_keep_audio) + 1。

    多給 1 筆，讓測試可以把音檔釘到上限後，再驗證「超過上限釘不上去」的邊界。
    enterprise 無上限（max_keep_audio=999999），釘選邊界測不到，固定給 1 筆。
    """
    if tier == "enterprise":
        return 1
    return QUOTA_BY_TIER[tier]["max_keep_audio"] + 1


def _build_mock_task(cfg: dict, user_id: str, now_ts: float, idx: int, audio_file: str) -> dict:
    task_id = _mock_task_id(cfg["tier"], idx)
    return {
        "_id": task_id,
        "task_id": task_id,
        "seed_mock": True,            # 標記：方便 list / 清理（id 已是不透明 UUID）
        "seed_tier": cfg["tier"],
        "task_type": "paragraph",
        "custom_name": f"示範轉錄 #{idx + 1}（SoundLite 功能展示）",
        "user": {
            "user_id": user_id,
            "user_email": cfg["email"],
            "tier": cfg["tier"],
        },
        "file": {
            "filename": f"soundlite_demo_{idx + 1}.mp3",
            "size_mb": _FAKE_MP3_SIZE_MB,
        },
        "config": {
            "punct_provider": "gemini",
            "chunk_audio": False,
            "chunk_minutes": 10,
            "diarize": True,
            "max_speakers": 2,
            "language": "zh",
            "ui_language": "zh-TW",
        },
        "status": "completed",
        "stats": {
            "audio_duration_seconds": 60.8,
            "diarization": {"num_speakers": 2},
        },
        "result": {
            "text_length": len(MOCK_TASK_CONTENT),
            "word_count": len(MOCK_TASK_CONTENT.split()),
            "audio_file": audio_file,   # 下載 / 播放 / 釘選都靠這個路徑定位 S3 物件
        },
        "models": {
            "punctuation": "gemini-2.0-flash",
        },
        "tags": [],
        "keep_audio": False,
        "speaker_names": {"SPEAKER_00": "主持人", "SPEAKER_01": "來賓"},
        "subtitle_settings": {"density_threshold": 3.0},
        "timestamps": {
            "created_at": now_ts,
            "updated_at": now_ts,
            "completed_at": now_ts,
        },
    }


def _build_mock_transcription(cfg: dict, now_ts: float, idx: int) -> dict:
    task_id = _mock_task_id(cfg["tier"], idx)
    return {
        "_id": task_id,
        "seed_mock": True,
        "seed_tier": cfg["tier"],
        "content": MOCK_TASK_CONTENT,
        "text_length": len(MOCK_TASK_CONTENT),
        "created_at": now_ts,
        "updated_at": now_ts,
    }


def _build_mock_segments(cfg: dict, now_ts: float, idx: int) -> dict:
    task_id = _mock_task_id(cfg["tier"], idx)
    return {
        "_id": task_id,
        "seed_mock": True,
        "seed_tier": cfg["tier"],
        "segments": MOCK_TASK_SEGMENTS,
        "segment_count": len(MOCK_TASK_SEGMENTS),
        "created_at": now_ts,
        "updated_at": now_ts,
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def _first_of_month_utc() -> datetime:
    """本月 1 日 00:00 UTC（防止 quota.py 月結邏輯自動歸零 usage）"""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _build_usage(near_limit: dict) -> dict:
    return {
        "transcriptions": 0,
        "duration_minutes": near_limit["duration_minutes"],
        "ai_summaries": near_limit["ai_summaries"],
        "last_reset": _first_of_month_utc(),
        "total_transcriptions": 0,
        "total_duration_minutes": near_limit["duration_minutes"],
    }


def _build_full_user(cfg: dict, now: datetime) -> dict:
    from src.auth.password import hash_password

    return {
        "email": cfg["email"],
        "password_hash": hash_password(TEST_PASSWORD),
        "auth_providers": ["password"],
        "role": "user",
        "is_active": True,
        "email_verified": True,
        "quota": QUOTA_BY_TIER[cfg["tier"]],
        "usage": _build_usage(cfg["near_limit_usage"]),
        "extra_quota": {"duration_minutes": 0.0, "ai_summaries": 0},
        "reserved_ai_summaries": 0,
        "refresh_tokens": [],
        "created_at": now,
        "updated_at": now,
    }


def _reset_fields(cfg: dict) -> dict:
    """reset 模式只更新 usage / token 相關欄位，其餘不動"""
    return {
        "usage": _build_usage(cfg["near_limit_usage"]),
        "extra_quota": {"duration_minutes": 0.0, "ai_summaries": 0},
        "reserved_ai_summaries": 0,
        "refresh_tokens": [],
        "updated_at": datetime.now(timezone.utc),
    }


def _upsert_mock_task(db, cfg: dict, user_id: str) -> int:
    """upsert 該 tier 的 mock 任務（數量 = max_keep_audio + 1），回傳筆數。"""
    ts = _now_ts()
    tier = cfg["tier"]
    count = _mock_task_count(tier)
    task_ops, trans_ops, seg_ops = [], [], []
    for idx in range(count):
        tid = _mock_task_id(tier, idx)
        audio_file = _store_fake_audio(tid, tier)   # 上傳假音檔，拿回儲存路徑
        task_doc = _build_mock_task(cfg, user_id, ts, idx, audio_file)
        trans_doc = _build_mock_transcription(cfg, ts, idx)
        seg_doc = _build_mock_segments(cfg, ts, idx)
        task_ops.append(ReplaceOne({"_id": tid}, task_doc, upsert=True))
        trans_ops.append(ReplaceOne({"_id": tid}, trans_doc, upsert=True))
        seg_ops.append(ReplaceOne({"_id": tid}, seg_doc, upsert=True))

    db.tasks.bulk_write(task_ops, ordered=False)
    db.transcriptions.bulk_write(trans_ops, ordered=False)
    db.segments.bulk_write(seg_ops, ordered=False)
    return count


def _delete_mock_task(db, cfg: dict):
    """刪掉該 tier 的所有 mock 任務 + 對應假音檔，避免重置後殘留。

    先依現有 task doc 的 result.audio_file 刪 S3/本地音檔（精準命中，pin 後搬到
    kept/ 的也一起清），再刪三個 collection 的 doc（新版 seed_mock marker + 舊版
    字串 id 都涵蓋）。
    """
    flt = _mock_task_filter(cfg["tier"])

    from src.utils.storage.compact import delete_audio_by_path
    for t in db.tasks.find(flt, {"result.audio_file": 1}):
        path = (t.get("result") or {}).get("audio_file")
        if path:
            try:
                delete_audio_by_path(path)
            except Exception as e:
                print(f"    ⚠️  刪音檔失敗（忽略）：{path} — {e}")

    db.tasks.delete_many(flt)
    db.transcriptions.delete_many(flt)
    db.segments.delete_many(flt)


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Seed / reset test users")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--reset", action="store_true", help="重置 usage / tokens / 示範任務（不重建帳號）")
    g.add_argument("--list", action="store_true", help="列出目前狀態後結束")
    p.add_argument("--dry-run", action="store_true", help="不寫入 DB，只印出將要做的事")
    return p.parse_args()


def connect():
    from src.utils.config_loader import get_parameter
    mongo_uri = get_parameter("/transcriber/mongodb-url", fallback_env="MONGODB_URL",
                              default="mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    print(f"✅ 已連線 MongoDB（{db_name}）")
    return client[db_name]


def cmd_list(db):
    print(f"\n{'email':<38} {'tier':<12} {'dur_used':>9} {'dur_max':>8} {'ai_used':>8} {'ai_max':>7} {'task':>6} {'audio':>6}")
    print("-" * 108)
    for cfg in TEST_USERS:
        user = db.users.find_one({"email": cfg["email"]})
        if not user:
            print(f"  {cfg['email']:<36} — 不存在")
            continue
        quota = user.get("quota", {})
        usage = user.get("usage", {})
        flt = _mock_task_filter(cfg["tier"])
        task_count = db.tasks.count_documents(flt)
        # 有寫入 result.audio_file 的任務數（音檔路徑就緒）
        audio_count = db.tasks.count_documents(
            {"$and": [flt, {"result.audio_file": {"$exists": True, "$ne": None}}]}
        )
        print(
            f"  {cfg['email']:<36} {quota.get('tier', '?'):<12} "
            f"{usage.get('duration_minutes', 0):>9.1f} {str(quota.get('max_duration_minutes', '?')):>8} "
            f"{usage.get('ai_summaries', 0):>8} {str(quota.get('max_ai_summaries', '?')):>7} "
            f"{task_count:>6} {audio_count:>6}"
        )


def cmd_upsert(db, dry_run: bool):
    now = datetime.now(timezone.utc)
    upserted = updated = skipped = 0
    _check_storage(dry_run)

    for cfg in TEST_USERS:
        tier = cfg["tier"]
        nl = cfg["near_limit_usage"]
        dur_max = QUOTA_BY_TIER[tier]["max_duration_minutes"]
        ai_max = QUOTA_BY_TIER[tier]["max_ai_summaries"]
        task_n = _mock_task_count(tier)
        print(
            f"  {'[dry]' if dry_run else '     '} {cfg['email']}"
            f"  tier={tier}"
            f"  dur={nl['duration_minutes']}/{dur_max}"
            f"  ai={nl['ai_summaries']}/{ai_max}"
            f"  +{task_n} mock task(s) (含假音檔)"
        )
        if dry_run:
            skipped += 1
            continue

        doc = _build_full_user(cfg, now)
        res = db.users.update_one({"email": cfg["email"]}, {"$set": doc}, upsert=True)
        user = db.users.find_one({"email": cfg["email"]})
        _delete_mock_task(db, cfg)
        _upsert_mock_task(db, cfg, str(user["_id"]))

        if res.upserted_id:
            upserted += 1
        elif res.modified_count:
            updated += 1
        else:
            skipped += 1

    if not dry_run:
        print(f"\n✅ 完成：新增 {upserted} 筆、更新 {updated} 筆、無變動 {skipped} 筆")
    else:
        print("\n[dry-run] 未寫入 DB。")


def cmd_reset(db, dry_run: bool):
    reset_ok = not_found = 0
    _check_storage(dry_run)

    for cfg in TEST_USERS:
        nl = cfg["near_limit_usage"]
        tier = cfg["tier"]
        dur_max = QUOTA_BY_TIER[tier]["max_duration_minutes"]
        ai_max = QUOTA_BY_TIER[tier]["max_ai_summaries"]
        task_n = _mock_task_count(tier)
        print(
            f"  {'[dry]' if dry_run else '     '} {cfg['email']}"
            f"  dur={nl['duration_minutes']}/{dur_max}"
            f"  ai={nl['ai_summaries']}/{ai_max}"
            f"  tokens=cleared  task=reset({task_n})"
        )
        if dry_run:
            continue

        res = db.users.update_one({"email": cfg["email"]}, {"$set": _reset_fields(cfg)})
        if res.matched_count:
            user = db.users.find_one({"email": cfg["email"]})
            _delete_mock_task(db, cfg)
            _upsert_mock_task(db, cfg, str(user["_id"]))
            reset_ok += 1
        else:
            print(f"    ⚠️  找不到帳號，請先執行 seed（不帶 --reset）")
            not_found += 1

    if not dry_run:
        print(f"\n✅ 重置完成：{reset_ok} 筆；找不到 {not_found} 筆")
    else:
        print("\n[dry-run] 未寫入 DB。")


def main():
    args = parse_args()
    db = connect()

    if args.list:
        cmd_list(db)
        return

    if args.reset:
        print("\n重置 usage / tokens / 示範任務 → 初始狀態：")
        cmd_reset(db, dry_run=args.dry_run)
    else:
        print("\nUpsert 測試帳號 + 示範任務：")
        cmd_upsert(db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
