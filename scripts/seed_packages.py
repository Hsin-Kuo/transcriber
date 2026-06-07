#!/usr/bin/env python3
"""
額外額度套餐（packages collection）Seed 腳本

`/subscriptions/purchase-extra` 會從 `packages` collection 撈可購買的加購套餐
（subscriptions.py 讀 label / type / amount / price_twd / active / sort_order）。
這個 collection 沒有預設資料，未 seed 時前端「購買額外額度」會 404。

使用方法：
    python scripts/seed_packages.py            # upsert（依 sku 更新或新增，不重複）
    python scripts/seed_packages.py --dry-run  # 只印出將寫入的內容，不寫 DB
    python scripts/seed_packages.py --list     # 列出目前 DB 內的套餐

說明：
- 以 `sku` 作為唯一鍵做 upsert，重跑不會產生重複資料、可安全用於正式環境。
- DB 名稱預設對齊 app（src/database/mongodb.py 的 MONGODB_DB_NAME，預設 whisper_transcriber）。
"""

import os
import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pymongo import MongoClient
from dotenv import load_dotenv


# ── 套餐定義（要改價格/品項就改這裡）────────────────────────────────────────
# type: "duration"（加購分鐘數）/ "ai_summaries"（加購 AI 摘要次數）
# amount: 該套餐增加的額度數量；price_twd: 售價（整數，TWD）
PACKAGES = [
    {
        "sku": "dur_60",
        "label": "加購 60 分鐘轉錄額度",
        "type": "duration",
        "amount": 60,
        "price_twd": 99,
        "active": True,
        "sort_order": 1,
    },
    {
        "sku": "dur_300",
        "label": "加購 300 分鐘轉錄額度",
        "type": "duration",
        "amount": 300,
        "price_twd": 399,
        "active": True,
        "sort_order": 2,
    },
    {
        "sku": "ai_10",
        "label": "加購 10 次 AI 摘要",
        "type": "ai_summaries",
        "amount": 10,
        "price_twd": 59,
        "active": True,
        "sort_order": 3,
    },
]


def parse_args():
    p = argparse.ArgumentParser(description="Seed packages collection")
    p.add_argument("--dry-run", action="store_true", help="只印出，不寫入 DB")
    p.add_argument("--list", action="store_true", help="列出目前 DB 內的套餐後結束")
    return p.parse_args()


def connect():
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已載入環境變數：{env_path}")
    mongo_uri = os.getenv("MONGODB_URL") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017"
    # 對齊 app 的預設（src/database/mongodb.py），避免寫錯 DB
    db_name = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    print(f"✅ 已連線 MongoDB，DB = {db_name}")
    return client[db_name]


def main():
    args = parse_args()
    db = connect()
    col = db["packages"]

    if args.list:
        existing = list(col.find().sort("sort_order", 1))
        print(f"\n目前 packages 共 {len(existing)} 筆：")
        for p in existing:
            print(f"  [{p.get('sku','?')}] {p.get('label')} — "
                  f"{p.get('type')} x{p.get('amount')} = NT${p.get('price_twd')} "
                  f"(active={p.get('active')})")
        return

    print(f"\n準備 upsert {len(PACKAGES)} 筆套餐（key=sku）：")
    for p in PACKAGES:
        print(f"  [{p['sku']}] {p['label']} — {p['type']} x{p['amount']} = NT${p['price_twd']}")

    if args.dry_run:
        print("\n[dry-run] 未寫入 DB。")
        return

    inserted = updated = 0
    for p in PACKAGES:
        res = col.update_one({"sku": p["sku"]}, {"$set": p}, upsert=True)
        if res.upserted_id is not None:
            inserted += 1
        elif res.modified_count:
            updated += 1
    print(f"\n✅ 完成：新增 {inserted} 筆、更新 {updated} 筆。")


if __name__ == "__main__":
    main()
