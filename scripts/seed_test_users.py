#!/usr/bin/env python3
"""
測試帳號 Seed / Reset 腳本

建立四個方案的測試帳號，usage 預設接近方案上限，方便測試邊界情境。
每個帳號附 (max_keep_audio + 1) 筆已完成的 mock 示範任務（含假音檔 +
transcription + segments），讓釘選音檔可以測到「釘滿上限再多 1 筆」的邊界。
enterprise 無釘選上限，固定給 1 筆。

使用方式：
    python scripts/seed_test_users.py            # upsert（新增或完整覆蓋）
    python scripts/seed_test_users.py --reset    # 重置 usage / tokens / 示範任務
    python scripts/seed_test_users.py --list     # 列出目前狀態
    python scripts/seed_test_users.py --dry-run  # 不寫入，只印出將要做的事

帳號密碼一律：TestUser@123
"""

import os
import sys
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


def _mock_task_id(tier: str, idx: int) -> str:
    return f"test-demo-task-{tier}-{idx}"


def _mock_task_id_pattern(tier: str) -> dict:
    """match 該 tier 的所有 mock 任務（含舊版無索引的 test-demo-task-{tier}）"""
    return {"$regex": f"^test-demo-task-{tier}(-|$)"}


def _mock_task_count(tier: str) -> int:
    """mock 任務數 = 可釘選音檔上限 (max_keep_audio) + 1。

    多給 1 筆，讓測試可以把音檔釘到上限後，再驗證「超過上限釘不上去」的邊界。
    enterprise 無上限（max_keep_audio=999999），釘選邊界測不到，固定給 1 筆。
    """
    if tier == "enterprise":
        return 1
    return QUOTA_BY_TIER[tier]["max_keep_audio"] + 1


def _build_mock_task(cfg: dict, user_id: str, now_ts: float, idx: int) -> dict:
    task_id = _mock_task_id(cfg["tier"], idx)
    return {
        "_id": task_id,
        "task_id": task_id,
        "task_type": "paragraph",
        "custom_name": f"示範轉錄 #{idx + 1}（SoundLite 功能展示）",
        "user": {
            "user_id": user_id,
            "user_email": cfg["email"],
            "tier": cfg["tier"],
        },
        "file": {
            "filename": f"soundlite_demo_{idx + 1}.mp3",
            "size_mb": 0.97,
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
        "content": MOCK_TASK_CONTENT,
        "text_length": len(MOCK_TASK_CONTENT),
        "created_at": now_ts,
        "updated_at": now_ts,
    }


def _build_mock_segments(cfg: dict, now_ts: float, idx: int) -> dict:
    task_id = _mock_task_id(cfg["tier"], idx)
    return {
        "_id": task_id,
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
    count = _mock_task_count(cfg["tier"])
    task_ops, trans_ops, seg_ops = [], [], []
    for idx in range(count):
        task_doc = _build_mock_task(cfg, user_id, ts, idx)
        trans_doc = _build_mock_transcription(cfg, ts, idx)
        seg_doc = _build_mock_segments(cfg, ts, idx)
        tid = task_doc["_id"]
        task_ops.append(ReplaceOne({"_id": tid}, task_doc, upsert=True))
        trans_ops.append(ReplaceOne({"_id": tid}, trans_doc, upsert=True))
        seg_ops.append(ReplaceOne({"_id": tid}, seg_doc, upsert=True))

    db.tasks.bulk_write(task_ops, ordered=False)
    db.transcriptions.bulk_write(trans_ops, ordered=False)
    db.segments.bulk_write(seg_ops, ordered=False)
    return count


def _delete_mock_task(db, cfg: dict):
    """刪掉該 tier 的所有 mock 任務（含舊版無索引 id），避免重置後殘留多餘筆數。"""
    pat = _mock_task_id_pattern(cfg["tier"])
    db.tasks.delete_many({"_id": pat})
    db.transcriptions.delete_many({"_id": pat})
    db.segments.delete_many({"_id": pat})


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
    print(f"\n{'email':<38} {'tier':<12} {'dur_used':>9} {'dur_max':>8} {'ai_used':>8} {'ai_max':>7} {'task':>8}")
    print("-" * 100)
    for cfg in TEST_USERS:
        user = db.users.find_one({"email": cfg["email"]})
        if not user:
            print(f"  {cfg['email']:<36} — 不存在")
            continue
        quota = user.get("quota", {})
        usage = user.get("usage", {})
        task_count = db.tasks.count_documents({"_id": _mock_task_id_pattern(cfg["tier"])})
        print(
            f"  {cfg['email']:<36} {quota.get('tier', '?'):<12} "
            f"{usage.get('duration_minutes', 0):>9.1f} {str(quota.get('max_duration_minutes', '?')):>8} "
            f"{usage.get('ai_summaries', 0):>8} {str(quota.get('max_ai_summaries', '?')):>7} "
            f"{task_count:>8}"
        )


def cmd_upsert(db, dry_run: bool):
    now = datetime.now(timezone.utc)
    upserted = updated = skipped = 0

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
            f"  +{task_n} mock task(s)"
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
