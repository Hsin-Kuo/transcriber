"""將現有 tasks.json 資料遷移到 MongoDB

使用方式:
    python -m src.database.migrations.migrate_json_to_mongo
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

# 添加專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
import os

# 載入環境變數
load_dotenv()

# 從環境變數讀取配置
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27020/")
DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
TASKS_JSON_PATH = Path(__file__).parent.parent.parent.parent / "output" / "tasks.json"


def _parse_timestamp(ts_str):
    """解析時間戳字串"""
    if not ts_str:
        return None
    try:
        # 嘗試多種格式
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f"
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(ts_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        # 如果都失敗，返回當前時間
        return datetime.utcnow()
    except:
        return datetime.utcnow()


async def migrate():
    """執行遷移"""
    # 連接 MongoDB
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    print(f"📂 讀取任務資料: {TASKS_JSON_PATH}")

    if not TASKS_JSON_PATH.exists():
        print("⚠️  tasks.json 不存在，跳過遷移")
        client.close()
        return

    with open(TASKS_JSON_PATH, 'r', encoding='utf-8') as f:
        tasks_data = json.load(f)

    print(f"📊 共 {len(tasks_data)} 個任務需要遷移")

    # 遷移任務
    migrated = 0
    skipped = 0
    failed = 0

    # 獲取管理員 ID（將未分配用戶的任務分配給管理員）
    admin_user = await db.users.find_one({"role": "admin"})
    if not admin_user:
        print("⚠️  未找到管理員帳號，請先執行 seed_admin.py")
        print("   未分配用戶的任務將使用 None 作為 user_id")
        admin_id = None
    else:
        admin_id = admin_user["_id"]
        print(f"✅ 找到管理員帳號: {admin_user['email']} ({admin_id})")

    for task_id, task in tasks_data.items():
        try:
            # 檢查是否已存在
            existing = await db.tasks.find_one({"_id": task_id})
            if existing:
                print(f"⏭️  跳過已存在的任務: {task_id[:8]}...")
                skipped += 1
                continue

            # 檢查是否有 user_id（已經在前面的步驟中添加）
            if "user_id" not in task or not task.get("user_id"):
                # 如果沒有 user_id，分配給管理員
                if admin_id:
                    task["user_id"] = str(admin_id)
                    task["user_email"] = admin_user["email"]
                else:
                    print(f"⚠️  跳過沒有 user_id 的任務: {task_id[:8]}...")
                    skipped += 1
                    continue

            # 直接使用任務資料（保留所有原始欄位）
            task_doc = task.copy()
            task_doc["_id"] = task_id  # 使用 task_id 作為 MongoDB 的 _id

            # 確保必要欄位存在
            if "tags" not in task_doc:
                task_doc["tags"] = []
            if "keep_audio" not in task_doc:
                task_doc["keep_audio"] = False

            await db.tasks.insert_one(task_doc)
            migrated += 1

            filename = task.get("custom_name") or task.get("filename", "unknown")
            if migrated % 5 == 0:
                print(f"   已遷移 {migrated}/{len(tasks_data)} 個任務...")

        except Exception as e:
            failed += 1
            print(f"❌ 遷移失敗 {task_id}: {e}")

    # 備份原檔案
    if migrated > 0:
        backup_path = TASKS_JSON_PATH.with_suffix('.json.backup')
        import shutil
        shutil.copy2(TASKS_JSON_PATH, backup_path)
        print(f"💾 原檔案已備份至: {backup_path}")

    print(f"\n🎉 遷移完成!")
    print(f"  - 成功: {migrated}")
    print(f"  - 跳過: {skipped}")
    print(f"  - 失敗: {failed}")

    if migrated > 0:
        # 建立索引
        print(f"\n📊 正在建立索引...")
        await db.tasks.create_index([("user_id", 1), ("created_at", -1)])
        await db.tasks.create_index([("user_id", 1), ("status", 1)])
        await db.tasks.create_index([("status", 1)])
        await db.tasks.create_index([("tags", 1)])
        print(f"✅ 索引建立完成")

        # 顯示統計
        print(f"\n📊 任務狀態統計:")
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        status_stats = await db.tasks.aggregate(pipeline).to_list(None)
        for stat in status_stats:
            print(f"   {stat['_id']}: {stat['count']} 個")

        print(f"\n📊 用戶任務統計:")
        pipeline = [
            {"$group": {
                "_id": {"user_email": "$user_email"},
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}}
        ]
        user_stats = await db.tasks.aggregate(pipeline).to_list(None)
        for stat in user_stats:
            print(f"   {stat['_id']['user_email']}: {stat['count']} 個")

        # 顯示範例任務
        print(f"\n📝 已遷移的任務範例（前3個）:")
        sample_tasks = await db.tasks.find({}).sort("created_at", -1).limit(3).to_list(3)
        for i, task in enumerate(sample_tasks, 1):
            filename = task.get("custom_name") or task.get("filename", "未命名")
            status = task.get("status", "unknown")
            created = task.get("created_at", "未知")
            print(f"   {i}. [{status}] {filename}")
            print(f"      ID: {task['_id'][:8]}...")
            print(f"      建立: {created}")
            print(f"      用戶: {task.get('user_email', '未知')}")

        print("\n⚠️  重要提示:")
        print("   1. 任務已成功遷移到 MongoDB")
        print("   2. 請重啟後端服務以使用 MongoDB 資料")
        print("   3. 原始 tasks.json 已備份")
        print("")

    # 關閉連接
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
