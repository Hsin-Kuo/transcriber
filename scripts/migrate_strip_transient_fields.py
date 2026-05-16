"""一次性 migration：把舊的 transient 進度欄位從 tasks document 中移除。

Stage 2 之後，transient 進度欄位（progress、progress_percentage、chunks 等）
搬到 task_progress collection 並由 TTL 自動清。但 Stage 2 部署前產生的
tasks documents 仍殘留這些欄位，跑這個 script 一次性清掉。

用法（在 web server 機器或本機）：
    MONGODB_URL='mongodb+srv://...' python scripts/migrate_strip_transient_fields.py [--dry-run]

Idempotent：重複跑沒副作用。
"""

import argparse
import os
import sys

from pymongo import MongoClient


# Stage 1/2 前的 task document 上可能存在的 transient 欄位 — 一次性 unset
TRANSIENT_FIELDS = [
    "progress",
    "progress_percentage",
    "chunks",
    "total_chunks",
    "completed_chunks",
    "processing_chunks",
    "chunks_created",
    "estimated_completion_time",
    "punctuation_started",
    "punctuation_current_chunk",
    "punctuation_total_chunks",
    "punctuation_completed",
    "diarization_started",
    "diarization_completed",
    "diarization_status",
    "audio_converted",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只統計受影響數量不實際 unset")
    parser.add_argument("--db", default=os.getenv("MONGODB_DB_NAME", "whisper_transcriber"))
    args = parser.parse_args()

    mongo_url = os.getenv("MONGODB_URL")
    if not mongo_url:
        print("❌ MONGODB_URL 未設定")
        sys.exit(1)

    client = MongoClient(mongo_url)
    coll = client[args.db].tasks

    # 統計受影響數量
    or_clauses = [{f: {"$exists": True}} for f in TRANSIENT_FIELDS]
    affected = coll.count_documents({"$or": or_clauses})
    total = coll.count_documents({})
    print(f"📊 tasks collection 共 {total} 個 document，其中 {affected} 個含 transient 欄位")

    if args.dry_run:
        print("🔍 dry-run：不實際更新")
        return

    if affected == 0:
        print("✅ 已乾淨，無需更新")
        return

    unset_doc = {f: "" for f in TRANSIENT_FIELDS}
    result = coll.update_many({"$or": or_clauses}, {"$unset": unset_doc})
    print(f"✅ 已更新 {result.modified_count} 個 document，移除 transient 欄位")


if __name__ == "__main__":
    main()
