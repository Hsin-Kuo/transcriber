"""一次性 migration：把存量 FREE 使用者過時的每月分鐘額度補到目前的方案設定。

背景：免費方案的 max_duration_minutes 曾調整過（舊值可能為 60），但使用者
quota.max_duration_minutes 是註冊當下從 QUOTA_TIERS 複製的快照，不會自動跟著
方案調整更新。於是早期註冊的 free 使用者 DB 裡可能仍存著舊值，實際被低估額度。

本 script 把「FREE tier 且 max_duration_minutes 低於目前設定（或缺漏）」的使用者
補齊到 QUOTA_TIERS[FREE] 的權威值。只會「補上去」，永不調降，避免動到任何
被特別放寬額度的帳號。

用法（在 web server 機器或本機）：
    # 先 dry-run（預設，只統計不寫入）
    MONGODB_URL='mongodb+srv://...' python scripts/backfill_free_tier_minutes.py
    # 確認數量無誤後實際寫入
    MONGODB_URL='mongodb+srv://...' python scripts/backfill_free_tier_minutes.py --apply

Idempotent：重複跑沒副作用（補齊後就不再符合條件）。
"""

import argparse
import os
import sys
from pathlib import Path

from pymongo import MongoClient

# 讓 script 能 import src 套件，取得唯一真實來源 QUOTA_TIERS
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.models.quota import QUOTA_TIERS, QuotaTier  # noqa: E402

FREE_MINUTES = QUOTA_TIERS[QuotaTier.FREE]["max_duration_minutes"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="實際寫入；不加此旗標時為 dry-run（只統計不更新）",
    )
    parser.add_argument("--db", default=os.getenv("MONGODB_DB_NAME", "whisper_transcriber"))
    args = parser.parse_args()

    mongo_url = os.getenv("MONGODB_URL")
    if not mongo_url:
        print("❌ MONGODB_URL 未設定")
        sys.exit(1)

    client = MongoClient(mongo_url)
    users = client[args.db].users

    # FREE tier 且分鐘額度缺漏或低於目前設定（永不調降）
    stale_filter = {
        "quota.tier": QuotaTier.FREE.value,
        "$or": [
            {"quota.max_duration_minutes": {"$exists": False}},
            {"quota.max_duration_minutes": {"$lt": FREE_MINUTES}},
        ],
    }

    total_free = users.count_documents({"quota.tier": QuotaTier.FREE.value})
    affected = users.count_documents(stale_filter)
    print(f"📊 FREE 使用者共 {total_free} 位；其中 {affected} 位額度過時（< {FREE_MINUTES} 或缺漏）")

    if affected:
        # 列出目前過時值的分佈，方便確認是不是預期中的舊值（例如 60）
        pipeline = [
            {"$match": stale_filter},
            {"$group": {"_id": "$quota.max_duration_minutes", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        print("   目前過時值分佈：")
        for row in users.aggregate(pipeline):
            print(f"     max_duration_minutes={row['_id']}: {row['count']} 位")

    if not args.apply:
        print(f"🔍 dry-run：未寫入。確認無誤後加 --apply 才會把這 {affected} 位補到 {FREE_MINUTES} 分鐘")
        return

    if affected == 0:
        print("✅ 無過時資料，無需更新")
        return

    result = users.update_many(stale_filter, {"$set": {"quota.max_duration_minutes": FREE_MINUTES}})
    print(f"✅ 已把 {result.modified_count} 位 FREE 使用者補到 {FREE_MINUTES} 分鐘")


if __name__ == "__main__":
    main()
