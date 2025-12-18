#!/usr/bin/env python3
"""
自動重構腳本：將 whisper_server.py 中的記憶體字典改為使用 MongoDB
"""

import re
from pathlib import Path

WHISPER_SERVER_FILE = Path(__file__).parent / "src" / "whisper_server.py"
BACKUP_FILE = WHISPER_SERVER_FILE.with_suffix('.py.backup_before_mongo_refactor')

def main():
    print("🔄 開始重構 whisper_server.py...")
    print("=" * 70)

    # 讀取原始檔案
    print(f"📂 讀取檔案: {WHISPER_SERVER_FILE}")
    with open(WHISPER_SERVER_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # 備份原始檔案
    print(f"💾 備份原始檔案: {BACKUP_FILE}")
    with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
        f.write(content)

    original_content = content
    modifications = []

    # ========== 第一步：移除 save_tasks_to_disk() 調用 ========== #
    print("\n🔧 步驟 1: 移除 save_tasks_to_disk() 調用...")
    pattern = r'\s*save_tasks_to_disk\(\)\s*'
    matches = len(re.findall(pattern, content))
    if matches > 0:
        content = re.sub(pattern, '\n', content)
        modifications.append(f"移除 {matches} 個 save_tasks_to_disk() 調用")
        print(f"   ✅ 移除 {matches} 處")

    # ========== 第二步：處理 with tasks_lock 中的 transcription_tasks 訪問 ========== #
    print("\n🔧 步驟 2: 移除不必要的 tasks_lock（MongoDB 自帶鎖）...")
    # 注意：這一步比較複雜，需要手動檢查

    # ========== 第三步：移除讀取操作 with tasks_lock ========== #
    print("\n🔧 步驟 3: 標記需要改為 async 的函數...")
    # 列出需要改為 async 的函數（這需要手動處理）
    print("""
   ⚠️  以下函數需要改為 async 並使用 task_repo：
   - process_transcription_task()  # 背景任務處理
   - update_task_progress()  # 更新進度
   - 所有使用 transcription_tasks 的端點
    """)

    # ========== 第四步：提供重構指南 ========== #
    print("\n📋 重構模式指南:")
    print("=" * 70)

    patterns = [
        {
            "舊模式": "with tasks_lock:\n    task = transcription_tasks.get(task_id)",
            "新模式": "task = await task_repo.get_by_id(task_id)",
            "說明": "獲取單個任務"
        },
        {
            "舊模式": "with tasks_lock:\n    transcription_tasks[task_id] = {...}",
            "新模式": "await task_repo.create({\"_id\": task_id, ...})",
            "說明": "創建任務"
        },
        {
            "舊模式": "transcription_tasks[task_id].update(updates)",
            "新模式": "await task_repo.update(task_id, updates)",
            "說明": "更新任務"
        },
        {
            "舊模式": "del transcription_tasks[task_id]",
            "新模式": "await task_repo.delete(task_id, user_id)",
            "說明": "刪除任務"
        },
        {
            "舊模式": "[t for t in transcription_tasks.values() if ...]",
            "新模式": "await task_repo.find_by_user(user_id, ...)",
            "說明": "查詢任務列表"
        },
    ]

    for i, pattern in enumerate(patterns, 1):
        print(f"\n{i}. {pattern['說明']}")
        print(f"   舊: {pattern['舊模式']}")
        print(f"   新: {pattern['新模式']}")

    # ========== 第五步：統計需要修改的位置 ========== #
    print("\n\n📊 需要修改的位置統計:")
    print("=" * 70)

    # 統計 transcription_tasks 使用次數
    transcription_tasks_count = len(re.findall(r'\btranscription_tasks\b', content))
    print(f"❗ transcription_tasks 引用: {transcription_tasks_count} 處")

    # 統計 with tasks_lock
    tasks_lock_count = len(re.findall(r'with tasks_lock:', content))
    print(f"❗ with tasks_lock: {tasks_lock_count} 處")

    # 列出所有包含 transcription_tasks 的行號
    print("\n📍 transcription_tasks 出現位置（前 20 個）:")
    lines = content.split('\n')
    occurrences = []
    for line_num, line in enumerate(lines, 1):
        if 'transcription_tasks' in line and not line.strip().startswith('#'):
            occurrences.append((line_num, line.strip()[:80]))

    for line_num, line_text in occurrences[:20]:
        print(f"   Line {line_num}: {line_text}")

    if len(occurrences) > 20:
        print(f"   ... 還有 {len(occurrences) - 20} 處")

    # ========== 保存修改後的內容（如果有自動修改） ========== #
    if modifications:
        print(f"\n💾 保存修改後的檔案...")
        with open(WHISPER_SERVER_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ 已保存")

        print(f"\n📋 已完成的修改:")
        for mod in modifications:
            print(f"   ✅ {mod}")
    else:
        print(f"\n⚠️  沒有進行自動修改")

    print("\n" + "=" * 70)
    print("🎯 下一步操作:")
    print("=" * 70)
    print("""
1. 手動重構關鍵函數（需要改為 async）:
   - process_transcription_task()
   - update_task_progress()

2. 重構所有 API 端點:
   - 所有端點都應該已經是 async
   - 將 transcription_tasks 訪問改為 task_repo 調用

3. 移除 with tasks_lock（MongoDB 操作不需要）

4. 測試：
   - 啟動服務測試是否正常
   - 測試創建、查詢、更新、刪除任務

5. 還原（如需要）:
   cp {BACKUP_FILE} {WHISPER_SERVER_FILE}
    """)

    print(f"\n💡 提示：由於改動較大，建議分階段進行:")
    print(f"   1. 先修改查詢端點（GET）")
    print(f"   2. 再修改創建端點（POST）")
    print(f"   3. 最後修改更新/刪除端點（PUT/DELETE）")
    print(f"   4. 每個階段完成後都進行測試")

if __name__ == "__main__":
    main()
