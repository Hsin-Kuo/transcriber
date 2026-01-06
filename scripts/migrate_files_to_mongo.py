"""
資料遷移腳本：將 txt 和 segments 從檔案系統遷移到 MongoDB

使用方式：
    python scripts/migrate_files_to_mongo.py [--dry-run] [--backup]

參數：
    --dry-run: 只顯示會執行的操作，不實際修改資料庫
    --backup: 遷移前先備份資料庫
"""

import os
import json
import argparse
from pathlib import Path
from pymongo import MongoClient
from datetime import datetime

# 設定
MONGODB_URI = os.getenv("MONGODB_URL", "mongodb://127.0.0.1:27020")
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
OUTPUT_DIR = Path(__file__).parent.parent / "output"

# 統計資訊
stats = {
    "total_tasks": 0,
    "migrated_transcriptions": 0,
    "migrated_segments": 0,
    "skipped_tasks": 0,
    "failed_tasks": 0,
    "errors": []
}


def migrate_task(task_id, db, dry_run=False):
    """遷移單一任務到獨立的 collections"""

    # 讀取 txt 檔案
    txt_file = OUTPUT_DIR / f"{task_id}.txt"
    if txt_file.exists():
        with open(txt_file, 'r', encoding='utf-8') as f:
            txt_content = f.read()
        print(f"  ✅ 讀取 txt: {len(txt_content)} 字元")

        # 檢查 transcriptions collection 是否已存在
        existing = db.transcriptions.find_one({"_id": task_id})
        if existing:
            print(f"  ⏭️  轉錄內容已存在，跳過")
            stats["skipped_tasks"] += 1
        elif dry_run:
            print(f"  🔍 [DRY-RUN] 將插入 transcriptions collection")
            stats["migrated_transcriptions"] += 1
        else:
            # 插入到 transcriptions collection
            now = datetime.utcnow()
            db.transcriptions.insert_one({
                "_id": task_id,
                "content": txt_content,
                "text_length": len(txt_content),
                "created_at": now,
                "updated_at": now
            })
            print(f"  ✅ 已插入 transcriptions collection")
            stats["migrated_transcriptions"] += 1

    # 讀取 segments 檔案
    segments_file = OUTPUT_DIR / f"{task_id}_segments.json"
    if segments_file.exists():
        with open(segments_file, 'r', encoding='utf-8') as f:
            segments_data = json.load(f)
        print(f"  ✅ 讀取 segments: {len(segments_data)} 個")

        # 檢查 segments collection 是否已存在
        existing = db.segments.find_one({"_id": task_id})
        if existing:
            print(f"  ⏭️  Segments 已存在，跳過")
        elif dry_run:
            print(f"  🔍 [DRY-RUN] 將插入 segments collection")
            stats["migrated_segments"] += 1
        else:
            # 插入到 segments collection
            now = datetime.utcnow()
            db.segments.insert_one({
                "_id": task_id,
                "segments": segments_data,
                "segment_count": len(segments_data),
                "created_at": now,
                "updated_at": now
            })
            print(f"  ✅ 已插入 segments collection")
            stats["migrated_segments"] += 1

    return True


def backup_database(client, db_name):
    """備份資料庫（導出為 JSON）"""
    backup_dir = Path(__file__).parent.parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"tasks_backup_{timestamp}.json"

    db = client[db_name]
    tasks = list(db.tasks.find({}))

    # 轉換特殊類型為字串
    for task in tasks:
        for key, value in task.items():
            if hasattr(value, "__class__") and value.__class__.__name__ == "ObjectId":
                task[key] = str(value)

    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2, default=str)

    print(f"✅ 已備份資料庫到 {backup_file} ({len(tasks)} 筆任務)")
    return backup_file


def main():
    parser = argparse.ArgumentParser(description="遷移檔案到 MongoDB")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會執行的操作")
    parser.add_argument("--backup", action="store_true", help="遷移前備份資料庫")
    args = parser.parse_args()

    print("=" * 60)
    print("檔案系統 → MongoDB 資料遷移工具")
    print("=" * 60)

    if args.dry_run:
        print("⚠️  DRY-RUN 模式：不會實際修改資料庫\n")

    # 連接資料庫
    print(f"正在連接資料庫 {MONGODB_URI}...")
    try:
        client = MongoClient(MONGODB_URI)
        db = client[DB_NAME]
        # 測試連接
        client.admin.command('ping')
        print("✅ MongoDB 連接成功\n")
    except Exception as e:
        print(f"❌ MongoDB 連接失敗：{e}")
        return

    # 備份（如果需要）
    if args.backup:
        print("開始備份資料庫...")
        backup_database(client, DB_NAME)
        print()

    # 掃描 output 目錄中的所有檔案
    if not OUTPUT_DIR.exists():
        print(f"❌ output 目錄不存在：{OUTPUT_DIR}")
        return

    all_txt_files = list(OUTPUT_DIR.glob("*.txt"))
    all_task_ids = {f.stem for f in all_txt_files}

    stats["total_tasks"] = len(all_task_ids)
    print(f"找到 {len(all_task_ids)} 個任務的檔案")
    print("-" * 60)

    # 遷移每個任務
    for i, task_id in enumerate(sorted(all_task_ids), 1):
        print(f"\n[{i}/{len(all_task_ids)}] 處理任務 {task_id}")

        try:
            migrate_task(task_id, db, dry_run=args.dry_run)
        except Exception as e:
            print(f"  ❌ 遷移失敗：{e}")
            stats["failed_tasks"] += 1
            stats["errors"].append({"task_id": task_id, "error": str(e)})

    # 顯示統計
    print("\n" + "=" * 60)
    print("遷移完成！")
    print("=" * 60)
    print(f"總任務數：{stats['total_tasks']}")
    print(f"已遷移轉錄內容：{stats['migrated_transcriptions']}")
    print(f"已遷移 segments：{stats['migrated_segments']}")
    print(f"已跳過：{stats['skipped_tasks']}")
    print(f"失敗：{stats['failed_tasks']}")

    if stats["errors"]:
        print("\n錯誤詳情：")
        for error in stats["errors"]:
            print(f"  - {error['task_id']}: {error['error']}")

    client.close()


if __name__ == "__main__":
    main()
