"""
資料庫遷移腳本：將時間字串轉換為 UTC Unix timestamp

支援的舊格式：
    1. "YYYY-MM-DD HH:MM:SS"（假設 UTC+8 時區）
    2. "YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM"（ISO 8601 帶時區）
    3. "YYYY-MM-DDTHH:MM:SSZ"（ISO 8601 UTC）
    4. datetime 物件（MongoDB ISODate）

新格式：整數 Unix timestamp（UTC 秒）

使用方式：
    python -m src.database.migrations.migrate_timestamps_to_unix

選項：
    --dry-run    只顯示會修改的資料，不實際執行
    --collection 只遷移指定的 collection（可選）
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

# UTC+8 時區
TZ_UTC8 = timezone(timedelta(hours=8))


def parse_datetime_string(dt_str: str) -> int:
    """將時間字串轉換為 UTC Unix timestamp

    支援格式：
    1. "YYYY-MM-DD HH:MM:SS" (假設為 UTC+8)
    2. "YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM" (ISO 8601 帶時區)
    3. "YYYY-MM-DDTHH:MM:SS.ffffffZ" (ISO 8601 UTC)
    4. "YYYY-MM-DDTHH:MM:SS+HH:MM" (ISO 8601 無毫秒)

    Args:
        dt_str: 時間字串

    Returns:
        UTC Unix timestamp（整數秒）
    """
    if not dt_str or not isinstance(dt_str, str):
        return None

    try:
        # 格式 1: "YYYY-MM-DD HH:MM:SS" (假設為 UTC+8)
        if " " in dt_str and "T" not in dt_str:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            dt_utc8 = dt.replace(tzinfo=TZ_UTC8)
            return int(dt_utc8.timestamp())

        # 格式 2-4: ISO 8601 格式
        if "T" in dt_str:
            # 移除毫秒部分的過多精度（Python 只支援 6 位）
            import re
            # 匹配 .123456789 這種超過 6 位的毫秒
            dt_str = re.sub(r'\.(\d{6})\d+', r'.\1', dt_str)

            # 處理 Z 結尾（UTC）
            if dt_str.endswith('Z'):
                dt_str = dt_str[:-1] + '+00:00'

            # Python 3.7+ 支援 fromisoformat
            try:
                dt = datetime.fromisoformat(dt_str)
                return int(dt.timestamp())
            except ValueError:
                pass

            # 備用：手動解析常見格式
            formats = [
                "%Y-%m-%dT%H:%M:%S.%f%z",  # 帶毫秒和時區
                "%Y-%m-%dT%H:%M:%S%z",      # 無毫秒有時區
                "%Y-%m-%dT%H:%M:%S.%f",     # 帶毫秒無時區（假設 UTC）
                "%Y-%m-%dT%H:%M:%S",        # 無毫秒無時區（假設 UTC）
            ]

            for fmt in formats:
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
                except ValueError:
                    continue

        return None
    except (ValueError, TypeError) as e:
        print(f"    ⚠️ 無法解析時間字串: {dt_str} - {e}")
        return None


def is_timestamp_string(value) -> bool:
    """檢查值是否為時間字串格式（需要遷移）"""
    if not isinstance(value, str):
        return False

    # 格式 1: "YYYY-MM-DD HH:MM:SS"
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return True
    except ValueError:
        pass

    # 格式 2: ISO 8601 (包含 T)
    if "T" in value:
        return True

    return False


async def migrate_tasks(db, dry_run: bool = False) -> dict:
    """遷移 tasks collection"""
    collection = db.tasks
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    # 時間欄位路徑
    timestamp_fields = [
        "timestamps.created_at",
        "timestamps.updated_at",
        "timestamps.started_at",
        "timestamps.completed_at",
        "updated_at",
        "deleted_at"
    ]

    cursor = collection.find({})
    async for doc in cursor:
        stats["total"] += 1
        task_id = doc.get("_id", "unknown")

        updates = {}
        for field in timestamp_fields:
            # 處理巢狀欄位
            parts = field.split(".")
            value = doc
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break

            if is_timestamp_string(value):
                new_value = parse_datetime_string(value)
                if new_value:
                    updates[field] = new_value

        # 額外處理根層級的 datetime 欄位
        for field in ["updated_at", "deleted_at"]:
            value = doc.get(field)
            if isinstance(value, datetime):
                updates[field] = int(value.timestamp())

        if updates:
            if dry_run:
                print(f"  [tasks] {task_id}: 會更新 {list(updates.keys())}")
            else:
                try:
                    await collection.update_one(
                        {"_id": task_id},
                        {"$set": updates}
                    )
                    stats["migrated"] += 1
                except Exception as e:
                    print(f"  [tasks] {task_id}: 更新失敗 - {e}")
                    stats["errors"] += 1
        else:
            stats["skipped"] += 1

    return stats


async def migrate_transcriptions(db, dry_run: bool = False) -> dict:
    """遷移 transcriptions collection"""
    collection = db.transcriptions
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    timestamp_fields = ["created_at", "updated_at"]

    cursor = collection.find({})
    async for doc in cursor:
        stats["total"] += 1
        doc_id = doc.get("_id", "unknown")

        updates = {}
        for field in timestamp_fields:
            value = doc.get(field)
            if is_timestamp_string(value):
                new_value = parse_datetime_string(value)
                if new_value:
                    updates[field] = new_value
            # 也處理 datetime 對象
            elif isinstance(value, datetime):
                updates[field] = int(value.timestamp())

        if updates:
            if dry_run:
                print(f"  [transcriptions] {doc_id}: 會更新 {list(updates.keys())}")
            else:
                try:
                    await collection.update_one(
                        {"_id": doc_id},
                        {"$set": updates}
                    )
                    stats["migrated"] += 1
                except Exception as e:
                    print(f"  [transcriptions] {doc_id}: 更新失敗 - {e}")
                    stats["errors"] += 1
        else:
            stats["skipped"] += 1

    return stats


async def migrate_segments(db, dry_run: bool = False) -> dict:
    """遷移 segments collection"""
    collection = db.segments
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    timestamp_fields = ["created_at", "updated_at"]

    cursor = collection.find({})
    async for doc in cursor:
        stats["total"] += 1
        doc_id = doc.get("_id", "unknown")

        updates = {}
        for field in timestamp_fields:
            value = doc.get(field)
            if is_timestamp_string(value):
                new_value = parse_datetime_string(value)
                if new_value:
                    updates[field] = new_value
            elif isinstance(value, datetime):
                updates[field] = int(value.timestamp())

        if updates:
            if dry_run:
                print(f"  [segments] {doc_id}: 會更新 {list(updates.keys())}")
            else:
                try:
                    await collection.update_one(
                        {"_id": doc_id},
                        {"$set": updates}
                    )
                    stats["migrated"] += 1
                except Exception as e:
                    print(f"  [segments] {doc_id}: 更新失敗 - {e}")
                    stats["errors"] += 1
        else:
            stats["skipped"] += 1

    return stats


async def migrate_tags(db, dry_run: bool = False) -> dict:
    """遷移 tags collection"""
    collection = db.tags
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    timestamp_fields = ["created_at", "updated_at"]

    cursor = collection.find({})
    async for doc in cursor:
        stats["total"] += 1
        doc_id = doc.get("_id", "unknown")

        updates = {}
        for field in timestamp_fields:
            value = doc.get(field)
            if is_timestamp_string(value):
                new_value = parse_datetime_string(value)
                if new_value:
                    updates[field] = new_value
            elif isinstance(value, datetime):
                updates[field] = int(value.timestamp())

        if updates:
            if dry_run:
                print(f"  [tags] {doc_id}: 會更新 {list(updates.keys())}")
            else:
                try:
                    await collection.update_one(
                        {"_id": doc_id},
                        {"$set": updates}
                    )
                    stats["migrated"] += 1
                except Exception as e:
                    print(f"  [tags] {doc_id}: 更新失敗 - {e}")
                    stats["errors"] += 1
        else:
            stats["skipped"] += 1

    return stats


async def migrate_users(db, dry_run: bool = False) -> dict:
    """遷移 users collection"""
    collection = db.users
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    cursor = collection.find({})
    async for doc in cursor:
        stats["total"] += 1
        doc_id = doc.get("_id", "unknown")

        updates = {}

        # 處理頂層時間欄位
        for field in ["created_at", "updated_at"]:
            value = doc.get(field)
            if is_timestamp_string(value):
                new_value = parse_datetime_string(value)
                if new_value:
                    updates[field] = new_value
            elif isinstance(value, datetime):
                updates[field] = int(value.timestamp())

        # 處理 refresh_tokens 陣列中的時間
        refresh_tokens = doc.get("refresh_tokens", [])
        if refresh_tokens:
            updated_tokens = []
            tokens_changed = False

            for token in refresh_tokens:
                new_token = token.copy()
                for field in ["created_at", "expires_at"]:
                    value = token.get(field)
                    if is_timestamp_string(value):
                        new_token[field] = parse_datetime_string(value)
                        tokens_changed = True
                    elif isinstance(value, datetime):
                        new_token[field] = int(value.timestamp())
                        tokens_changed = True
                updated_tokens.append(new_token)

            if tokens_changed:
                updates["refresh_tokens"] = updated_tokens

        if updates:
            if dry_run:
                print(f"  [users] {doc_id}: 會更新 {list(updates.keys())}")
            else:
                try:
                    await collection.update_one(
                        {"_id": doc_id},
                        {"$set": updates}
                    )
                    stats["migrated"] += 1
                except Exception as e:
                    print(f"  [users] {doc_id}: 更新失敗 - {e}")
                    stats["errors"] += 1
        else:
            stats["skipped"] += 1

    return stats


async def migrate_audit_logs(db, dry_run: bool = False) -> dict:
    """遷移 audit_logs collection"""
    collection = db.audit_logs
    stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    cursor = collection.find({})
    async for doc in cursor:
        stats["total"] += 1
        doc_id = doc.get("_id", "unknown")

        updates = {}
        value = doc.get("timestamp")
        if is_timestamp_string(value):
            new_value = parse_datetime_string(value)
            if new_value:
                updates["timestamp"] = new_value
        elif isinstance(value, datetime):
            updates["timestamp"] = int(value.timestamp())

        if updates:
            if dry_run:
                print(f"  [audit_logs] {doc_id}: 會更新 timestamp")
            else:
                try:
                    await collection.update_one(
                        {"_id": doc_id},
                        {"$set": updates}
                    )
                    stats["migrated"] += 1
                except Exception as e:
                    print(f"  [audit_logs] {doc_id}: 更新失敗 - {e}")
                    stats["errors"] += 1
        else:
            stats["skipped"] += 1

    return stats


async def run_migration(dry_run: bool = False, collection: str = None):
    """執行遷移"""
    # 連接資料庫
    mongo_uri = os.getenv("MONGODB_URL", os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    db_name = os.getenv("MONGODB_DB_NAME", "transcriber")

    print(f"📦 連接資料庫: {db_name}")
    print(f"🔧 模式: {'Dry Run（模擬）' if dry_run else '實際執行'}")
    print("-" * 50)

    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]

    # 遷移函數映射
    migrations = {
        "tasks": migrate_tasks,
        "transcriptions": migrate_transcriptions,
        "segments": migrate_segments,
        "tags": migrate_tags,
        "users": migrate_users,
        "audit_logs": migrate_audit_logs
    }

    # 如果指定了 collection，只遷移該 collection
    if collection:
        if collection not in migrations:
            print(f"❌ 未知的 collection: {collection}")
            print(f"   可用的 collections: {', '.join(migrations.keys())}")
            return
        migrations = {collection: migrations[collection]}

    # 執行遷移
    total_stats = {"total": 0, "migrated": 0, "skipped": 0, "errors": 0}

    for name, migrate_func in migrations.items():
        print(f"\n🔄 遷移 {name}...")
        stats = await migrate_func(db, dry_run)

        print(f"   總數: {stats['total']}, 遷移: {stats['migrated']}, "
              f"跳過: {stats['skipped']}, 錯誤: {stats['errors']}")

        for key in total_stats:
            total_stats[key] += stats[key]

    # 總結
    print("\n" + "=" * 50)
    print("📊 遷移總結")
    print(f"   總文檔數: {total_stats['total']}")
    print(f"   已遷移: {total_stats['migrated']}")
    print(f"   已跳過（無需遷移）: {total_stats['skipped']}")
    print(f"   錯誤: {total_stats['errors']}")

    if dry_run:
        print("\n⚠️  這是 Dry Run 模式，沒有實際修改資料")
        print("   移除 --dry-run 參數以執行實際遷移")
    else:
        print("\n✅ 遷移完成！")

    client.close()


def main():
    """主函數"""
    import argparse

    parser = argparse.ArgumentParser(
        description="將時間字串遷移為 UTC Unix timestamp"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示會修改的資料，不實際執行"
    )
    parser.add_argument(
        "--collection",
        type=str,
        help="只遷移指定的 collection（tasks, transcriptions, segments, tags, users, audit_logs）"
    )

    args = parser.parse_args()

    print("=" * 50)
    print("🚀 時間格式遷移工具")
    print("   舊格式:")
    print("     - 'YYYY-MM-DD HH:MM:SS' (UTC+8)")
    print("     - 'YYYY-MM-DDTHH:MM:SS.fff+00:00' (ISO 8601)")
    print("     - datetime 物件")
    print("   新格式: Unix timestamp (UTC 秒)")
    print("=" * 50)

    asyncio.run(run_migration(dry_run=args.dry_run, collection=args.collection))


if __name__ == "__main__":
    main()
