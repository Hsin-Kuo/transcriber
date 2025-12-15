"""將現有 tasks.json 資料遷移到 MongoDB

使用方式:
    python -m src.database.migrations.migrate_json_to_mongo
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# 添加專案根目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
import os

# 從環境變數讀取配置
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
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
                print(f"⏭️  跳過已存在的任務: {task_id}")
                skipped += 1
                continue

            # 資料轉換
            task_doc = {
                "_id": task_id,  # 保留原 ID
                "user_id": admin_id,  # 分配給管理員（或 None）
                "filename": task.get("filename", "unknown"),
                "custom_name": task.get("custom_name"),
                "status": task.get("status", "unknown"),
                "progress": task.get("progress", ""),
                "audio_duration": task.get("audio_duration"),
                "audio_path": task.get("audio_path"),
                "keep_audio": task.get("keep_audio", False),
                "transcript": task.get("transcript"),
                "segments": task.get("segments", []),
                "options": {
                    "model": task.get("model", "medium"),
                    "language": task.get("language", "zh"),
                    "enable_diarization": task.get("enable_diarization", False),
                    "max_speakers": task.get("max_speakers"),
                    "enable_punctuation": task.get("enable_punctuation", True),
                    "punct_provider": task.get("punct_provider", "gemini")
                },
                "chunks": task.get("chunks", []),
                "tags": task.get("tags", []),
                "created_at": _parse_timestamp(task.get("created_at")),
                "updated_at": _parse_timestamp(task.get("updated_at")),
                "completed_at": _parse_timestamp(task.get("completed_at"))
            }

            await db.tasks.insert_one(task_doc)
            migrated += 1
            print(f"✅ 遷移任務: {task_id} - {task.get('filename', 'unknown')}")

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

    # 建立索引
    print(f"\n📊 正在建立索引...")
    await db.tasks.create_index([("user_id", 1), ("created_at", -1)])
    await db.tasks.create_index([("status", 1)])
    await db.tasks.create_index([("tags", 1)])
    print(f"✅ 索引建立完成")

    # 關閉連接
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
