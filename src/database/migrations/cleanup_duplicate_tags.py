"""清理 tags collection 內 (user_id, name) 重複的 tag record

配合 fix(tags) commit 579c614 的 race fix。歷史 bug 期間，frontend rename
會對多個 task 並行打 PUT /tasks/{id}/tags，後端 auto-create 在 unique index
缺失時 race 出多筆同名 tag。這個 script 把歷史殘留清乾淨，讓
(user_id, name) unique index 能順利建立。

使用方式：
    # 1) 預覽（強烈建議先跑這個）
    python -m src.database.migrations.cleanup_duplicate_tags --dry-run

    # 2) 實際執行
    python -m src.database.migrations.cleanup_duplicate_tags

    # 3) 清完後順手嘗試建立 unique index 驗證乾淨
    python -m src.database.migrations.cleanup_duplicate_tags --ensure-index

    # 限定單一 user（除錯用）
    python -m src.database.migrations.cleanup_duplicate_tags --user-id <user_id>

    # 同時清掉「沒被任何 task 引用」的孤兒 tag（rename 後遺留的舊名 record）
    python -m src.database.migrations.cleanup_duplicate_tags --remove-orphans

策略：
- Dedup：每組 (user_id, name) 保留 created_at 最早的一筆，其餘刪除。
  task.tags 用 name 引用（不是 tag_id），所以刪重複不影響 task 連結。
- 孤兒清理（opt-in）：tag record 的 name 沒有任何 task.tags 引用 → 刪除。
- Ensure index（opt-in）：清完後 create_index unique；若仍失敗代表還有殘留。

安全性：
- 預設不刪 production 上的孤兒（--remove-orphans 才會啟用），避免把
  user 刻意保留待用的空 tag 也清掉。
- --dry-run 完整列出每筆會被刪掉的 record，可以人工 review。
- 整個流程 idempotent，重複執行不會出錯。
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 添加專案根目錄到 Python 路徑（讓 src.* import 可用）
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# 必須在 import config_loader 之前載入 .env，因為 DEPLOY_ENV 在模組層級讀取
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError, OperationFailure

from src.utils.config_loader import get_parameter

MONGODB_URL = get_parameter(
    "/transcriber/mongodb-url",
    fallback_env="MONGODB_URL",
    default="mongodb://localhost:27017",
)
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")


def _sort_key(doc: dict) -> tuple:
    """duplicate group 的排序 key：created_at 升冪，ties 用 _id（ObjectId 含時間順序）。

    防呆：created_at 若非數字（legacy datetime / 缺值）退回 0，避免跨類型比較炸掉。
    """
    ca = doc.get("created_at")
    if isinstance(ca, (int, float)):
        return (ca, str(doc.get("_id")))
    return (0, str(doc.get("_id")))


def _short_uid(user_id: str) -> str:
    """user_id 縮寫顯示（避免 log 過長）"""
    s = str(user_id)
    return f"{s[:8]}…" if len(s) > 12 else s


async def find_duplicates(db, user_id_filter: Optional[str]) -> list[dict]:
    """找出 (user_id, name) 重複的 tag group。

    Returns:
        [{user_id, name, count, docs (sorted by created_at asc)}, ...]
    """
    pipeline = []
    if user_id_filter:
        pipeline.append({"$match": {"user_id": user_id_filter}})

    pipeline.extend([
        {
            "$group": {
                "_id": {"user_id": "$user_id", "name": "$name"},
                "count": {"$sum": 1},
                "ids": {"$push": "$_id"},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ])

    duplicates = []
    async for group in db.tags.aggregate(pipeline):
        # 撈完整 docs 以便依 created_at 排序
        docs = await db.tags.find(
            {"_id": {"$in": group["ids"]}}
        ).to_list(length=None)
        docs.sort(key=_sort_key)
        duplicates.append({
            "user_id": group["_id"]["user_id"],
            "name": group["_id"]["name"],
            "count": group["count"],
            "docs": docs,
        })
    return duplicates


async def find_orphan_tags(db, user_id_filter: Optional[str]) -> list[dict]:
    """找出沒被任何 task 引用的 tag record。

    Returns:
        orphan tag docs
    """
    query = {}
    if user_id_filter:
        query["user_id"] = user_id_filter

    all_tags = await db.tags.find(query).to_list(length=None)
    if not all_tags:
        return []

    # 收集所有相關 user 「正在被 task 引用」的 (user_id, tag_name)
    user_ids = list({t["user_id"] for t in all_tags})
    referenced: dict[str, set[str]] = defaultdict(set)
    async for task in db.tasks.find(
        {"user_id": {"$in": user_ids}, "tags": {"$exists": True, "$ne": []}},
        {"user_id": 1, "tags": 1},
    ):
        uid = task["user_id"]
        for name in task.get("tags") or []:
            referenced[uid].add(name)

    return [
        t for t in all_tags
        if t["name"] not in referenced.get(t["user_id"], set())
    ]


async def dedup_tags(db, dry_run: bool, user_id_filter: Optional[str]) -> int:
    """執行 dedup。Returns: 刪除的 record 數量。"""
    duplicates = await find_duplicates(db, user_id_filter)

    if not duplicates:
        print("✅ 沒有重複的 (user_id, name) tag record")
        return 0

    print(f"發現 {len(duplicates)} 組 (user_id, name) 重複：\n")
    total_to_delete = 0
    ids_to_delete = []

    for group in duplicates:
        docs = group["docs"]
        keep = docs[0]
        drop = docs[1:]
        total_to_delete += len(drop)
        ids_to_delete.extend(d["_id"] for d in drop)

        print(
            f"  user={_short_uid(group['user_id'])} "
            f"name='{group['name']}' (共 {group['count']} 筆)"
        )
        print(
            f"    保留 tag_id={keep.get('tag_id')} "
            f"created_at={keep.get('created_at')}"
        )
        for d in drop:
            print(
                f"    刪除 tag_id={d.get('tag_id')} "
                f"created_at={d.get('created_at')}"
            )
        print()

    if dry_run:
        print(
            f"[DRY-RUN] 將刪除 {total_to_delete} 筆重複 tag record（未實際執行）"
        )
        return 0

    result = await db.tags.delete_many({"_id": {"$in": ids_to_delete}})
    print(f"✅ 已刪除 {result.deleted_count} 筆重複 tag record")
    return result.deleted_count


async def remove_orphans(db, dry_run: bool, user_id_filter: Optional[str]) -> int:
    """執行孤兒清理。Returns: 刪除的 record 數量。"""
    orphans = await find_orphan_tags(db, user_id_filter)

    if not orphans:
        print("✅ 沒有孤兒 tag record")
        return 0

    print(f"發現 {len(orphans)} 筆孤兒 tag（沒被任何 task 引用）：\n")
    for o in orphans:
        print(
            f"  user={_short_uid(o['user_id'])} "
            f"name='{o['name']}' tag_id={o.get('tag_id')} "
            f"created_at={o.get('created_at')}"
        )

    if dry_run:
        print(f"\n[DRY-RUN] 將刪除 {len(orphans)} 筆孤兒 tag（未實際執行）")
        return 0

    ids = [o["_id"] for o in orphans]
    result = await db.tags.delete_many({"_id": {"$in": ids}})
    print(f"\n✅ 已刪除 {result.deleted_count} 筆孤兒 tag")
    return result.deleted_count


async def ensure_unique_index(db) -> bool:
    """嘗試建立 (user_id, name) unique index。Returns: 是否成功。"""
    try:
        await db.tags.create_index(
            [("user_id", 1), ("name", 1)],
            unique=True,
            name="user_id_1_name_1_unique",
        )
        print("✅ (user_id, name) unique index 建立成功（或已存在）")
        return True
    except (DuplicateKeyError, OperationFailure) as e:
        print(f"❌ unique index 建立失敗：{e}")
        print("   tags collection 仍有重複資料，請檢查上面的 dedup 輸出")
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="清理 tags collection 內重複 / 孤兒 tag record"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只顯示會刪除的資料，不實際執行",
    )
    parser.add_argument(
        "--user-id", type=str, default=None,
        help="限定單一 user_id（除錯用，預設清掃所有 user）",
    )
    parser.add_argument(
        "--remove-orphans", action="store_true",
        help="同時清掉沒被任何 task 引用的孤兒 tag（rename 遺留物）",
    )
    parser.add_argument(
        "--ensure-index", action="store_true",
        help="清完後嘗試建立 (user_id, name) unique index",
    )
    args = parser.parse_args()

    # 摘要顯示連線資訊（隱去密碼）
    display_url = MONGODB_URL.split("@")[-1] if "@" in MONGODB_URL else MONGODB_URL
    print(f"連線 MongoDB: {display_url}")
    print(f"DB: {DB_NAME}")
    if args.user_id:
        print(f"限定 user_id: {args.user_id}")
    if args.dry_run:
        print("模式: DRY-RUN（不實際刪除）")
    print()

    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    try:
        print("=" * 60)
        print("Step 1: Dedup 重複的 (user_id, name) tag record")
        print("=" * 60)
        await dedup_tags(db, args.dry_run, args.user_id)

        if args.remove_orphans:
            print()
            print("=" * 60)
            print("Step 2: 清理孤兒 tag record")
            print("=" * 60)
            await remove_orphans(db, args.dry_run, args.user_id)

        if args.ensure_index:
            print()
            print("=" * 60)
            print("Step 3: 建立 (user_id, name) unique index")
            print("=" * 60)
            if args.dry_run:
                print("[DRY-RUN] 略過（dry-run 模式不建 index）")
            else:
                await ensure_unique_index(db)

        print("\n完成")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
