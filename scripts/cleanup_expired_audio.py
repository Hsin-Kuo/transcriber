#!/usr/bin/env python3
"""
音檔到期清理腳本（DB 收斂 sweep）

定位：prod 真正刪音檔的是 **S3 Lifecycle**（依 uploads/{tier}/ 前綴的物件年齡，
free=3d / paid=7d / kept=永不刪）。本腳本是它的「DB 收斂」搭檔——把 lifecycle
已（或即將）刪除的音檔，在 DB 把 result.audio_file 清成 None 並標記 audio_expired，
讓列表/詳情頁不再露出失效的下載連結。

到期判斷**完全複用** src.services.task_query_helpers.is_audio_expired()，與線上
列表/詳情頁同一套邏輯，因此自動具備：
  - keep_audio（kept/）永不過期
  - 降級釋放的 audio_expires_at 寬限期優先（與 S3 Lifecycle 對齊）
  - 否則依音檔路徑 tier 推導保留天數（free=3 / paid=7），而非寫死 7 天
  - 支援 int Unix timestamp 與 ISO 字串兩種 completed_at

刪檔走 storage 層 delete_audio_by_path()，local / S3 自動切換（S3 物件多半已被
lifecycle 刪掉，這裡是 belt-and-suspenders）。

使用方法：
    python scripts/cleanup_expired_audio.py [--dry-run]

參數：
    --dry-run: 模擬執行，不實際刪除檔案 / 不改 DB（僅顯示將處理的內容）
    --help:    顯示此幫助訊息
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import argparse

# 添加專案根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bson import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv

# 與線上列表/詳情頁同一套到期判斷（含 audio_expires_at 寬限期、path-tier 推導）
from src.services.task_query_helpers import is_audio_expired
from src.utils.storage.compact import audio_exists_by_path, delete_audio_by_path

# 找不到 user tier 時的 fallback 保留天數（與 get_user_retention_days 預設一致）。
# 注意：prod 的 audio_file 是 s3://.../uploads/{tier}/...，is_audio_expired 會優先用
# path-tier 推導，故此 fallback 僅在 local（無 tier 分區）或路徑異常時才生效。
DEFAULT_RETENTION_DAYS = 7


def parse_args():
    """解析命令列參數"""
    parser = argparse.ArgumentParser(
        description="清理已到期的音檔（依 tier 保留天數 / 寬限期，非寫死 7 天）",
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
        help="模擬執行，不實際刪除檔案 / 不改 DB"
    )
    return parser.parse_args()


def load_config():
    """載入環境變數配置"""
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ 已載入環境變數：{env_path}")
    else:
        print(f"⚠️  未找到 .env 檔案：{env_path}")

    mongo_uri = os.getenv("MONGODB_URL") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017"
    db_name = os.getenv("MONGODB_DB_NAME", "transcriber")

    return {"mongo_uri": mongo_uri, "db_name": db_name}


def connect_mongodb(config: dict):
    """連接到 MongoDB"""
    try:
        client = MongoClient(config["mongo_uri"], serverSelectionTimeoutMS=5000)
        client.server_info()  # 測試連接
        db = client[config["db_name"]]
        print(f"✅ 成功連接到 MongoDB：{config['db_name']}")
        return client, db
    except Exception as e:
        print(f"❌ 連接 MongoDB 失敗：{e}")
        sys.exit(1)


def _tier_retention_days(tier: str) -> int:
    """tier → audio_retention_days（無法辨識時退回預設）。"""
    from src.models.quota import QUOTA_TIERS, QuotaTier
    try:
        return QUOTA_TIERS[QuotaTier(tier)].get("audio_retention_days", DEFAULT_RETENTION_DAYS)
    except (KeyError, ValueError):
        return DEFAULT_RETENTION_DAYS


def _user_retention_days(db, user_id: str, cache: Dict[str, int]) -> int:
    """取得任務所屬使用者 tier 的保留天數（帶 cache，避免每筆都查 users）。

    這只是 is_audio_expired 的 fallback；有 audio_expires_at 或 S3 path-tier 時不會用到。
    """
    if not user_id:
        return DEFAULT_RETENTION_DAYS
    if user_id in cache:
        return cache[user_id]
    retention = DEFAULT_RETENTION_DAYS
    try:
        user = db.users.find_one({"_id": ObjectId(user_id)}, {"quota.tier": 1})
        if user:
            retention = _tier_retention_days((user.get("quota") or {}).get("tier", "free"))
    except Exception:
        pass
    cache[user_id] = retention
    return retention


def find_expired_audio_tasks(db) -> List[Dict[str, Any]]:
    """查詢需要清理音檔的已完成任務。

    粗篩（DB 端）：completed / 未刪除 / 仍有 result.audio_file / 非 keep_audio；
    細判（Python 端）：交給 is_audio_expired()（含寬限期、path-tier、timestamp 型別處理）。
    """
    query = {
        "status": "completed",
        "keep_audio": {"$ne": True},
        "result.audio_file": {"$exists": True, "$ne": None},
        "deleted": {"$ne": True},
    }
    projection = {
        "_id": 1,
        "user.user_id": 1,
        "user.user_email": 1,
        "timestamps.completed_at": 1,
        "result.audio_file": 1,
        "result.audio_filename": 1,
        "keep_audio": 1,
        "audio_expires_at": 1,
    }

    retention_cache: Dict[str, int] = {}
    expired_tasks: List[Dict[str, Any]] = []
    for task in db.tasks.find(query, projection):
        user_id = (task.get("user") or {}).get("user_id")
        retention_days = _user_retention_days(db, user_id, retention_cache)
        if is_audio_expired(task, retention_days):
            expired_tasks.append(task)

    return expired_tasks


def delete_audio_file(audio_path: str, dry_run: bool = False) -> str:
    """刪除音檔（local / S3 自動切換）。回傳狀態：deleted / not_found / failed。"""
    if not audio_path:
        return "not_found"

    if not audio_exists_by_path(audio_path):
        # S3 物件通常已被 lifecycle 刪除 → 視為已清理，只需收斂 DB
        print(f"    ⚠️  音檔已不存在（lifecycle 可能已刪）：{audio_path}")
        return "not_found"

    if dry_run:
        print(f"    [DRY-RUN] 將刪除：{audio_path}")
        return "deleted"

    try:
        delete_audio_by_path(audio_path)
        print(f"    ✅ 已刪除：{audio_path}")
        return "deleted"
    except Exception as e:
        print(f"    ❌ 刪除失敗：{audio_path} - {e}")
        return "failed"


def update_task_audio_record(db, task_id: str, dry_run: bool = False) -> bool:
    """收斂 DB：清除音檔路徑並持久化 audio_expired 標記（供詳情頁顯示過期提示）。"""
    if dry_run:
        print(f"    [DRY-RUN] 將更新資料庫：清除 task {task_id} 的音檔記錄")
        return True

    try:
        result = db.tasks.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "result.audio_file": None,
                    "result.audio_filename": None,
                    "audio_expired": True,
                }
            }
        )
        if result.modified_count > 0:
            print(f"    ✅ 已更新資料庫記錄")
        else:
            print(f"    ⚠️  資料庫記錄未更新（可能已被更新）")
        return True
    except Exception as e:
        print(f"    ❌ 更新資料庫失敗：{e}")
        return False


def cleanup_expired_audio(db, dry_run: bool = False):
    """執行音檔清理"""
    print("\n" + "=" * 60)
    print(f"🧹 開始清理到期音檔 {'(模擬執行)' if dry_run else ''}")
    print("=" * 60)
    print("\n📐 到期判斷：複用 is_audio_expired()（keep_audio / audio_expires_at 寬限期 /")
    print("   依 path-tier 推導 free=3d、paid=7d；非寫死 7 天）\n")

    print("🔍 正在查詢到期的音檔任務...")
    expired_tasks = find_expired_audio_tasks(db)

    if not expired_tasks:
        print("✅ 沒有找到需要清理的音檔")
        return

    print(f"📋 找到 {len(expired_tasks)} 個到期任務\n")

    stats = {
        "total": len(expired_tasks),
        "file_deleted": 0,
        "file_not_found": 0,
        "file_delete_failed": 0,
        "db_updated": 0,
        "db_update_failed": 0,
    }

    for i, task in enumerate(expired_tasks, 1):
        task_id = task.get("_id")
        audio_path = (task.get("result") or {}).get("audio_file")
        user_email = (task.get("user") or {}).get("user_email", "unknown")

        print(f"\n[{i}/{len(expired_tasks)}] 任務 ID: {task_id}")
        print(f"    用戶：{user_email}")
        print(f"    音檔路徑：{audio_path}")

        status = delete_audio_file(audio_path, dry_run)
        if status == "deleted":
            stats["file_deleted"] += 1
        elif status == "not_found":
            stats["file_not_found"] += 1
        else:
            stats["file_delete_failed"] += 1

        # 即使檔案已不存在，仍要收斂 DB（清掉殘留的 audio_file pointer）；
        # 只有「刪檔明確失敗」時才不動 DB，避免 DB 說沒檔、S3 卻還在。
        if status != "failed":
            if update_task_audio_record(db, task_id, dry_run):
                stats["db_updated"] += 1
            else:
                stats["db_update_failed"] += 1

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

    print("🚀 音檔到期清理腳本（DB 收斂 sweep）")
    print(f"📁 專案目錄：{project_root}")

    config = load_config()
    client, db = connect_mongodb(config)

    try:
        cleanup_expired_audio(db, dry_run=args.dry_run)
    finally:
        client.close()
        print("\n🔒 已關閉資料庫連接")


if __name__ == "__main__":
    main()
