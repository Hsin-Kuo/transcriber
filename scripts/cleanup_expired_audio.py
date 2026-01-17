#!/usr/bin/env python3
"""
音檔到期清理腳本

功能：
- 檢查所有 keep_audio != True 的已完成任務
- 刪除轉錄完成日期超過7天的音檔
- 更新資料庫記錄

使用方法：
    python scripts/cleanup_expired_audio.py [--dry-run]

參數：
    --dry-run: 模擬執行，不實際刪除檔案（僅顯示將要刪除的內容）
    --help: 顯示此幫助訊息
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import argparse

# 添加專案根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pymongo import MongoClient
from dotenv import load_dotenv


def parse_args():
    """解析命令列參數"""
    parser = argparse.ArgumentParser(
        description="清理超過7天的音檔",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python scripts/cleanup_expired_audio.py              # 執行清理
  python scripts/cleanup_expired_audio.py --dry-run    # 模擬執行（不實際刪除）
        """
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模擬執行，不實際刪除檔案"
    )
    return parser.parse_args()


def load_config():
    """載入環境變數配置"""
    # 載入 .env 檔案
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已載入環境變數：{env_path}")
    else:
        print(f"⚠️  未找到 .env 檔案：{env_path}")

    # 取得 MongoDB 連接資訊
    mongo_uri = os.getenv("MONGODB_URL") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017"
    db_name = os.getenv("MONGODB_DB_NAME", "transcriber")

    return {
        "mongo_uri": mongo_uri,
        "db_name": db_name
    }


def connect_mongodb(config: dict):
    """連接到 MongoDB"""
    try:
        client = MongoClient(
            config["mongo_uri"],
            serverSelectionTimeoutMS=5000
        )
        # 測試連接
        client.server_info()
        db = client[config["db_name"]]
        print(f"✅ 成功連接到 MongoDB：{config['db_name']}")
        return client, db
    except Exception as e:
        print(f"❌ 連接 MongoDB 失敗：{e}")
        sys.exit(1)


def parse_iso_datetime(date_str: str) -> datetime:
    """解析 ISO 格式的日期時間字串

    支援格式：
    - 2024-01-16T10:30:00Z
    - 2024-01-16T10:30:00.123Z
    - 2024-01-16T10:30:00+00:00
    """
    if not date_str:
        return None

    try:
        # 移除尾部的 'Z' 並替換為 +00:00
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'

        # Python 3.7+ 支援 fromisoformat
        return datetime.fromisoformat(date_str)
    except ValueError:
        try:
            # 備用方案：使用 strptime
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f+00:00")
        except ValueError:
            try:
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S+00:00")
            except ValueError:
                print(f"⚠️  無法解析日期格式：{date_str}")
                return None


def find_expired_audio_tasks(db, cutoff_date: datetime) -> List[Dict[str, Any]]:
    """查詢需要刪除音檔的任務

    條件：
    1. status = "completed"
    2. keep_audio != True
    3. timestamps.completed_at < cutoff_date（超過7天）
    4. result.audio_file 存在且不為空
    5. deleted != True（排除已刪除的任務）
    """
    query = {
        "status": "completed",
        "keep_audio": {"$ne": True},
        "timestamps.completed_at": {"$exists": True, "$ne": None},
        "result.audio_file": {"$exists": True, "$ne": None},
        "deleted": {"$ne": True}
    }

    # 只查詢必要的欄位
    projection = {
        "_id": 1,
        "task_id": 1,
        "user.user_id": 1,
        "user.user_email": 1,
        "timestamps.completed_at": 1,
        "result.audio_file": 1,
        "result.audio_filename": 1,
        "keep_audio": 1
    }

    tasks = list(db.tasks.find(query, projection))

    # 篩選出真正超過7天的任務
    expired_tasks = []
    for task in tasks:
        completed_at_str = task.get("timestamps", {}).get("completed_at")
        if not completed_at_str:
            continue

        completed_at = parse_iso_datetime(completed_at_str)
        if completed_at and completed_at < cutoff_date:
            task["_parsed_completed_at"] = completed_at
            expired_tasks.append(task)

    return expired_tasks


def delete_audio_file(audio_path: str, dry_run: bool = False) -> bool:
    """刪除音檔檔案

    Args:
        audio_path: 音檔路徑
        dry_run: 是否為模擬執行

    Returns:
        是否成功刪除（或檔案不存在）
    """
    audio_file = Path(audio_path)

    if not audio_file.exists():
        print(f"    ⚠️  音檔不存在：{audio_path}")
        return True  # 檔案不存在也算成功

    if dry_run:
        file_size = audio_file.stat().st_size / (1024 * 1024)  # MB
        print(f"    [DRY-RUN] 將刪除：{audio_path} ({file_size:.2f} MB)")
        return True

    try:
        audio_file.unlink()
        file_size = audio_file.stat().st_size / (1024 * 1024) if audio_file.exists() else 0
        print(f"    ✅ 已刪除：{audio_path}")
        return True
    except Exception as e:
        print(f"    ❌ 刪除失敗：{audio_path} - {e}")
        return False


def update_task_audio_record(db, task_id: str, dry_run: bool = False) -> bool:
    """更新資料庫記錄，清除音檔路徑

    Args:
        db: MongoDB 資料庫實例
        task_id: 任務 ID
        dry_run: 是否為模擬執行

    Returns:
        是否成功更新
    """
    if dry_run:
        print(f"    [DRY-RUN] 將更新資料庫：清除 task {task_id} 的音檔記錄")
        return True

    try:
        result = db.tasks.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "result.audio_file": None,
                    "result.audio_filename": None
                }
            }
        )

        if result.modified_count > 0:
            print(f"    ✅ 已更新資料庫記錄")
            return True
        else:
            print(f"    ⚠️  資料庫記錄未更新（可能已被更新）")
            return True  # 算作成功
    except Exception as e:
        print(f"    ❌ 更新資料庫失敗：{e}")
        return False


def cleanup_expired_audio(db, dry_run: bool = False):
    """執行音檔清理"""
    print("\n" + "=" * 60)
    print(f"🧹 開始清理到期音檔 {'(模擬執行)' if dry_run else ''}")
    print("=" * 60)

    # 計算7天前的日期（UTC 時間）
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    print(f"\n📅 基準日期：{seven_days_ago.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   （完成日期早於此時間的音檔將被刪除）\n")

    # 查詢需要刪除的任務
    print("🔍 正在查詢到期的音檔任務...")
    expired_tasks = find_expired_audio_tasks(db, seven_days_ago)

    if not expired_tasks:
        print("✅ 沒有找到需要清理的音檔")
        return

    print(f"📋 找到 {len(expired_tasks)} 個到期任務\n")

    # 統計資訊
    stats = {
        "total": len(expired_tasks),
        "file_deleted": 0,
        "file_not_found": 0,
        "file_delete_failed": 0,
        "db_updated": 0,
        "db_update_failed": 0
    }

    # 處理每個任務
    for i, task in enumerate(expired_tasks, 1):
        task_id = task.get("_id")
        audio_path = task.get("result", {}).get("audio_file")
        completed_at = task.get("_parsed_completed_at")
        user_email = task.get("user", {}).get("user_email", "unknown")

        days_ago = (datetime.utcnow() - completed_at).days

        print(f"\n[{i}/{len(expired_tasks)}] 任務 ID: {task_id}")
        print(f"    用戶：{user_email}")
        print(f"    完成時間：{completed_at.strftime('%Y-%m-%d %H:%M:%S')} ({days_ago} 天前)")
        print(f"    音檔路徑：{audio_path}")

        # 刪除音檔檔案
        audio_file = Path(audio_path) if audio_path else None
        if audio_file and audio_file.exists():
            if delete_audio_file(audio_path, dry_run):
                stats["file_deleted"] += 1
            else:
                stats["file_delete_failed"] += 1
        else:
            stats["file_not_found"] += 1
            print(f"    ⚠️  音檔已不存在")

        # 更新資料庫記錄
        if update_task_audio_record(db, task_id, dry_run):
            stats["db_updated"] += 1
        else:
            stats["db_update_failed"] += 1

    # 顯示統計結果
    print("\n" + "=" * 60)
    print("📊 清理統計")
    print("=" * 60)
    print(f"總任務數：        {stats['total']}")
    print(f"檔案已刪除：      {stats['file_deleted']}")
    print(f"檔案不存在：      {stats['file_not_found']}")
    print(f"檔案刪除失敗：    {stats['file_delete_failed']}")
    print(f"資料庫已更新：    {stats['db_updated']}")
    print(f"資料庫更新失敗：  {stats['db_update_failed']}")
    print("=" * 60)

    if dry_run:
        print("\n⚠️  這是模擬執行，未實際刪除檔案")
        print("   如需執行實際刪除，請移除 --dry-run 參數")
    else:
        print("\n✅ 清理完成！")


def main():
    """主函數"""
    args = parse_args()

    print("🚀 音檔到期清理腳本")
    print(f"📁 專案目錄：{project_root}")

    # 載入配置
    config = load_config()

    # 連接資料庫
    client, db = connect_mongodb(config)

    try:
        # 執行清理
        cleanup_expired_audio(db, dry_run=args.dry_run)
    finally:
        # 關閉資料庫連接
        client.close()
        print("\n🔒 已關閉資料庫連接")


if __name__ == "__main__":
    main()
