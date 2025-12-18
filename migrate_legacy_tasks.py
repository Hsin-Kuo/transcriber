#!/usr/bin/env python3
"""
遷移腳本：將舊任務分配給管理員帳號
將所有沒有 user_id 的歷史任務分配給 admin@example.com
"""

import asyncio
import json
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import os
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27020/")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
TASKS_FILE = Path(__file__).parent / "output" / "tasks.json"


async def migrate_legacy_tasks():
    """將舊任務遷移到管理員帳號"""

    print("🔄 開始遷移歷史任務...")
    print("=" * 60)

    # 連接 MongoDB
    print(f"\n📡 連接 MongoDB: {MONGODB_URL}")
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[MONGODB_DB_NAME]

    try:
        # 獲取管理員用戶
        print("🔍 查找管理員帳號...")
        admin_user = await db.users.find_one({"email": "admin@example.com"})

        if not admin_user:
            print("❌ 找不到管理員帳號 (admin@example.com)")
            print("   請先執行 seed_admin.py 建立管理員帳號")
            return

        admin_id = str(admin_user["_id"])
        admin_email = admin_user["email"]
        print(f"✅ 找到管理員: {admin_email}")
        print(f"   User ID: {admin_id}")

        # 讀取 tasks.json
        print(f"\n📂 讀取任務檔案: {TASKS_FILE}")
        if not TASKS_FILE.exists():
            print("❌ tasks.json 不存在")
            return

        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)

        print(f"✅ 載入 {len(tasks_data)} 個任務")

        # 統計需要遷移的任務
        legacy_tasks = []
        already_assigned = []

        for task_id, task in tasks_data.items():
            if "user_id" not in task or not task.get("user_id"):
                legacy_tasks.append(task_id)
            else:
                already_assigned.append(task_id)

        print(f"\n📊 任務統計:")
        print(f"   需要遷移: {len(legacy_tasks)} 個")
        print(f"   已分配用戶: {len(already_assigned)} 個")

        if len(legacy_tasks) == 0:
            print("\n✅ 所有任務都已有用戶，無需遷移")
            return

        # 更新任務
        print(f"\n🔧 開始更新任務...")
        updated_count = 0

        for task_id in legacy_tasks:
            task = tasks_data[task_id]
            task["user_id"] = admin_id
            task["user_email"] = admin_email

            # 如果有 updated_at，更新它
            if "updated_at" in task:
                from datetime import datetime
                task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            updated_count += 1

            # 顯示進度
            if updated_count % 5 == 0:
                print(f"   已更新 {updated_count}/{len(legacy_tasks)} 個任務...")

        print(f"✅ 已更新 {updated_count} 個任務")

        # 備份原始檔案
        backup_file = TASKS_FILE.parent / "tasks.json.backup_before_migration"
        print(f"\n💾 備份原始檔案: {backup_file.name}")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, ensure_ascii=False, indent=2)

        # 儲存更新後的檔案
        print(f"💾 儲存更新後的任務檔案...")
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, ensure_ascii=False, indent=2)

        print(f"✅ 任務檔案已更新")

        # 顯示遷移摘要
        print("\n" + "=" * 60)
        print("📋 遷移摘要:")
        print("=" * 60)
        print(f"✅ 成功遷移 {updated_count} 個歷史任務")
        print(f"👤 所有任務已分配給: {admin_email}")
        print(f"📁 備份檔案: {backup_file.name}")
        print("")
        print("⚠️  注意:")
        print("   1. 請重啟後端服務以載入更新後的任務")
        print("   2. 使用管理員帳號登入即可查看這些歷史任務")
        print("   3. 備份檔案已保存，如需還原可以手動恢復")
        print("")

        # 列出前 5 個已遷移的任務
        print("📝 已遷移的任務範例（前5個）:")
        for i, task_id in enumerate(legacy_tasks[:5], 1):
            task = tasks_data[task_id]
            filename = task.get("filename", task.get("custom_name", "未命名"))
            status = task.get("status", "unknown")
            created = task.get("created_at", "未知")
            print(f"   {i}. [{status}] {filename}")
            print(f"      ID: {task_id}")
            print(f"      建立時間: {created}")

        if len(legacy_tasks) > 5:
            print(f"   ... 還有 {len(legacy_tasks) - 5} 個任務")

        print("\n🎉 遷移完成！")

    except Exception as e:
        print(f"\n❌ 遷移失敗: {e}")
        import traceback
        traceback.print_exc()

    finally:
        client.close()
        print("\n🔌 已關閉 MongoDB 連接")


if __name__ == "__main__":
    asyncio.run(migrate_legacy_tasks())
