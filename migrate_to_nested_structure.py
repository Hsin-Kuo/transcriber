#!/usr/bin/env python3
"""
MongoDB 資料結構遷移腳本
將扁平結構的任務資料轉換為巢狀結構

使用方法：
  python migrate_to_nested_structure.py --dry-run  # 預覽變更（不實際更新）
  python migrate_to_nested_structure.py            # 執行遷移
"""

import os
import sys
import argparse
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from datetime import datetime


# MongoDB 連接配置
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27020")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")


def convert_flat_to_nested(flat_task):
    """將扁平格式的任務轉換為巢狀格式"""

    # 檢查是否已經是巢狀格式
    if "user" in flat_task and isinstance(flat_task["user"], dict):
        print(f"  ⏭️  任務 {flat_task.get('task_id')} 已經是巢狀格式，跳過")
        return None

    # 建立巢狀結構
    nested_task = {
        "_id": flat_task["_id"],
        "task_id": flat_task["task_id"],
        "status": flat_task.get("status", "pending"),
    }

    # user 資訊
    if "user_id" in flat_task or "user_email" in flat_task:
        nested_task["user"] = {
            "user_id": flat_task.get("user_id"),
            "user_email": flat_task.get("user_email")
        }

    # file 資訊
    if "filename" in flat_task or "file_size_mb" in flat_task:
        nested_task["file"] = {
            "filename": flat_task.get("filename"),
            "size_mb": flat_task.get("file_size_mb")
        }

    # config 資訊
    nested_task["config"] = {
        "punct_provider": flat_task.get("punct_provider", "gemini"),
        "chunk_audio": flat_task.get("chunk_audio", False),
        "chunk_minutes": flat_task.get("chunk_minutes", 10),
        "diarize": flat_task.get("diarize", False),
        "max_speakers": flat_task.get("max_speakers"),
        "language": flat_task.get("language")
    }

    # result 資訊（只在有結果時建立）
    result = {}
    if flat_task.get("audio_file"):
        result["audio_file"] = flat_task["audio_file"]
    if flat_task.get("audio_filename"):
        result["audio_filename"] = flat_task["audio_filename"]
    if flat_task.get("result_file"):
        result["transcription_file"] = flat_task["result_file"]
    if flat_task.get("result_filename"):
        result["transcription_filename"] = flat_task["result_filename"]
    if flat_task.get("segments_file"):
        result["segments_file"] = flat_task["segments_file"]
    if flat_task.get("text_length"):
        result["text_length"] = flat_task["text_length"]

    if result:
        nested_task["result"] = result

    # stats 資訊
    stats = {}

    # duration_seconds
    if flat_task.get("duration_seconds"):
        stats["duration_seconds"] = flat_task["duration_seconds"]

    # token_usage
    token_usage = {}
    if flat_task.get("total_tokens_used"):
        token_usage["total"] = flat_task["total_tokens_used"]
    if flat_task.get("prompt_tokens_used"):
        token_usage["prompt"] = flat_task["prompt_tokens_used"]
    if flat_task.get("completion_tokens_used"):
        token_usage["completion"] = flat_task["completion_tokens_used"]
    if flat_task.get("llm_model_used"):
        token_usage["model"] = flat_task["llm_model_used"]

    if token_usage:
        stats["token_usage"] = token_usage

    # diarization
    diarization = {}
    if flat_task.get("diarization_num_speakers"):
        diarization["num_speakers"] = flat_task["diarization_num_speakers"]
    if flat_task.get("diarization_duration_seconds"):
        diarization["duration_seconds"] = flat_task["diarization_duration_seconds"]

    if diarization:
        stats["diarization"] = diarization

    if stats:
        nested_task["stats"] = stats

    # progress（只在最終狀態時保留）
    if flat_task.get("status") in ["completed", "failed", "cancelled"]:
        if flat_task.get("progress"):
            nested_task["progress"] = flat_task["progress"]

    # timestamps
    nested_task["timestamps"] = {
        "created_at": flat_task.get("created_at"),
        "updated_at": flat_task.get("updated_at"),
        "started_at": flat_task.get("started_at"),
        "completed_at": flat_task.get("completed_at")
    }

    # 其他頂層欄位
    nested_task["tags"] = flat_task.get("tags", [])
    nested_task["custom_name"] = flat_task.get("custom_name")
    nested_task["keep_audio"] = flat_task.get("keep_audio", False)

    return nested_task


async def migrate_tasks(dry_run=False):
    """遷移所有任務資料"""

    print(f"\n{'=' * 60}")
    print(f"MongoDB 資料結構遷移工具")
    print(f"{'=' * 60}")
    print(f"資料庫: {MONGODB_URL}")
    print(f"Database: {MONGODB_DB_NAME}")
    print(f"模式: {'🔍 預覽模式（不會實際更新）' if dry_run else '✍️  執行模式（會實際更新資料庫）'}")
    print(f"{'=' * 60}\n")

    # 連接 MongoDB
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[MONGODB_DB_NAME]

    try:
        # 測試連接
        await client.admin.command('ping')
        print("✅ 成功連接到 MongoDB\n")
    except Exception as e:
        print(f"❌ MongoDB 連接失敗: {e}")
        return

    # 獲取所有任務
    tasks_collection = db.tasks
    total_tasks = await tasks_collection.count_documents({})

    print(f"📊 找到 {total_tasks} 個任務\n")

    if total_tasks == 0:
        print("⚠️  沒有任務需要遷移")
        return

    # 統計
    migrated_count = 0
    skipped_count = 0
    error_count = 0

    # 遍歷所有任務
    cursor = tasks_collection.find({})

    async for task in cursor:
        task_id = task.get("task_id", "unknown")

        try:
            # 轉換格式
            nested_task = convert_flat_to_nested(task)

            if nested_task is None:
                skipped_count += 1
                continue

            if dry_run:
                # 預覽模式：只顯示變更
                print(f"  📝 任務 {task_id}:")
                print(f"     扁平欄位: user_id={task.get('user_id')}, filename={task.get('filename')}")
                print(f"     巢狀格式: user.user_id={nested_task['user']['user_id']}, file.filename={nested_task['file']['filename']}")
                migrated_count += 1
            else:
                # 執行模式：實際更新
                await tasks_collection.replace_one(
                    {"_id": task["_id"]},
                    nested_task
                )
                print(f"  ✅ 任務 {task_id} 已遷移")
                migrated_count += 1

        except Exception as e:
            print(f"  ❌ 任務 {task_id} 遷移失敗: {e}")
            error_count += 1

    # 顯示統計
    print(f"\n{'=' * 60}")
    print(f"遷移完成統計")
    print(f"{'=' * 60}")
    print(f"總任務數: {total_tasks}")
    print(f"✅ {'預覽' if dry_run else '已遷移'}: {migrated_count}")
    print(f"⏭️  跳過（已是巢狀格式）: {skipped_count}")
    print(f"❌ 錯誤: {error_count}")
    print(f"{'=' * 60}\n")

    if dry_run:
        print("💡 這是預覽模式，沒有實際更新資料庫")
        print("💡 要執行實際遷移，請執行: python migrate_to_nested_structure.py")
    else:
        print("🎉 資料庫遷移完成！")

    client.close()


def main():
    parser = argparse.ArgumentParser(
        description="將 MongoDB 中的任務資料從扁平結構遷移到巢狀結構"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="預覽模式，不會實際更新資料庫"
    )

    args = parser.parse_args()

    # 執行遷移
    asyncio.run(migrate_tasks(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
