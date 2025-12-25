"""任務管理路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any
from pathlib import Path
import asyncio
import json

from ..auth.dependencies import get_current_user, get_current_user_sse
from ..database.mongodb import get_database
from ..database.repositories.task_repo import TaskRepository
from ..services.task_service import TaskService


router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_task_service(db=Depends(get_database)) -> TaskService:
    """依賴注入：獲取 TaskService 實例

    Args:
        db: 資料庫實例

    Returns:
        TaskService 實例
    """
    task_repo = TaskRepository(db)
    return TaskService(task_repo)


@router.get("/recent")
async def get_recent_tasks(
    limit: int = 10,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取最近任務預覽（精簡數據）

    Args:
        limit: 限制數量（預設 10）
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        精簡的任務列表（僅包含 task_id, display_name, created_at）
    """
    # 從資料庫獲取最近的任務
    tasks = await task_service.task_repo.find_by_user(
        str(current_user["_id"]),
        skip=0,
        limit=limit,
        include_deleted=False
    )

    # 只返回需要的欄位
    recent_tasks = []
    for task in tasks:
        task_id = str(task.get("_id") or task.get("task_id"))

        # 獲取顯示名稱：優先使用 custom_name，否則使用 file.filename
        display_name = task.get("custom_name")
        if not display_name:
            file_info = task.get("file", {})
            display_name = file_info.get("filename") if isinstance(file_info, dict) else None
        if not display_name:
            display_name = task_id

        # 獲取建立時間
        timestamps = task.get("timestamps", {})
        created_at = timestamps.get("created_at") if isinstance(timestamps, dict) else None

        recent_tasks.append({
            "task_id": task_id,
            "display_name": display_name,
            "created_at": created_at
        })

    return {
        "tasks": recent_tasks
    }


@router.get("")
async def get_tasks(
    status: str = None,
    limit: int = 100,
    skip: int = 0,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取任務列表（需認證，只能查看自己的任務）

    Args:
        status: 過濾狀態（可選：pending, processing, completed, failed, cancelled, active）
        limit: 限制數量（預設 100）
        skip: 跳過數量（預設 0）
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        任務列表
    """
    # 如果 status 是 'active'，轉換為 pending 和 processing
    if status == 'active':
        # 獲取所有任務並在記憶體中過濾
        all_tasks = await task_service.task_repo.find_by_user(
            str(current_user["_id"]),
            skip=skip,
            limit=limit,
            include_deleted=False
        )

        # 過濾出進行中的任務
        active_tasks = []
        for task in all_tasks:
            # 合併記憶體狀態
            task_id = str(task.get("_id") or task.get("task_id"))
            enriched_task = await task_service.get_task(task_id, str(current_user["_id"]))
            if enriched_task and enriched_task.get("status") in ["pending", "processing"]:
                active_tasks.append(enrich_task_data(enriched_task))

        return {
            "tasks": active_tasks,
            "total": len(active_tasks),
            "limit": limit,
            "skip": skip
        }
    else:
        # 從資料庫獲取任務
        tasks = await task_service.task_repo.find_by_user(
            str(current_user["_id"]),
            skip=skip,
            limit=limit,
            status=status,
            include_deleted=False
        )

        # 合併記憶體狀態
        enriched_tasks = []
        for task in tasks:
            task_id = str(task.get("_id") or task.get("task_id"))
            enriched_task = await task_service.get_task(task_id, str(current_user["_id"]))
            if enriched_task:
                enriched_tasks.append(enrich_task_data(enriched_task))

        # 計算總數
        total = await task_service.task_repo.count_by_user(
            str(current_user["_id"]),
            status=status,
            include_deleted=False
        )

        return {
            "tasks": enriched_tasks,
            "total": total,
            "limit": limit,
            "skip": skip
        }


# 全域 TaskService 單例（用於在非路由上下文中訪問）
_task_service_singleton: TaskService = None


def init_task_service(
    db,
    memory_tasks=None,
    cancelled_tasks=None,
    temp_dirs=None,
    diarization_processes=None,
    lock=None
):
    """初始化全域 TaskService 單例

    Args:
        db: 資料庫實例
        memory_tasks: 共享的記憶體任務字典（與 whisper_server.py 共享）
        cancelled_tasks: 共享的取消標記字典
        temp_dirs: 共享的臨時目錄字典
        diarization_processes: 共享的 diarization 進程字典
        lock: 共享的線程鎖
    """
    global _task_service_singleton
    task_repo = TaskRepository(db)
    _task_service_singleton = TaskService(
        task_repo,
        memory_tasks=memory_tasks,
        cancelled_tasks=cancelled_tasks,
        temp_dirs=temp_dirs,
        diarization_processes=diarization_processes,
        lock=lock
    )
    return _task_service_singleton


def get_task_service_singleton() -> TaskService:
    """獲取全域 TaskService 單例

    Returns:
        TaskService 實例

    Raises:
        RuntimeError: 如果 TaskService 尚未初始化
    """
    if _task_service_singleton is None:
        raise RuntimeError("TaskService 尚未初始化，請先調用 init_task_service()")
    return _task_service_singleton


def get_task_field(task: Dict[str, Any], field: str) -> Any:
    """安全獲取任務欄位（支援巢狀與扁平格式）

    Args:
        task: 任務資料
        field: 欄位名稱（扁平格式，如 'result_file', 'user_id'）

    Returns:
        欄位值，如果不存在則返回 None
    """
    # 欄位映射：扁平名稱 -> 巢狀路徑
    FIELD_PATHS = {
        # user 相關
        "user_id": ("user", "user_id"),
        "user_email": ("user", "user_email"),

        # file 相關
        "filename": ("file", "filename"),
        "file_size_mb": ("file", "size_mb"),

        # config 相關
        "punct_provider": ("config", "punct_provider"),
        "chunk_audio": ("config", "chunk_audio"),
        "diarize": ("config", "diarize"),
        "language": ("config", "language"),

        # result 相關
        "result_file": ("result", "transcription_file"),
        "result_filename": ("result", "transcription_filename"),
        "audio_file": ("result", "audio_file"),
        "audio_filename": ("result", "audio_filename"),
        "segments_file": ("result", "segments_file"),
        "text_length": ("result", "text_length"),

        # stats 相關
        "duration_seconds": ("stats", "duration_seconds"),

        # timestamps 相關
        "created_at": ("timestamps", "created_at"),
        "updated_at": ("timestamps", "updated_at"),
        "completed_at": ("timestamps", "completed_at"),
    }

    # 如果是頂層欄位（status, progress, tags, keep_audio, custom_name 等）
    if field not in FIELD_PATHS:
        return task.get(field)

    # 嘗試從巢狀路徑獲取
    nested_path = FIELD_PATHS[field]
    value = task
    for key in nested_path:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None

    return value


def enrich_task_data(task: Dict[str, Any]) -> Dict[str, Any]:
    """豐富任務數據，添加計算欄位

    Args:
        task: 原始任務數據

    Returns:
        豐富後的任務數據
    """
    # 創建副本避免修改原始數據
    enriched = task.copy()

    # 確保進行中的任務總是有進度信息
    status = enriched.get("status")

    # 如果沒有進度信息，根據狀態添加默認值
    if "progress" not in enriched or not enriched["progress"]:
        if status == "pending":
            enriched["progress"] = "等待處理中..."
            enriched["progress_percentage"] = 0
        elif status == "processing":
            # 如果是處理中但沒有具體進度，提供一個默認進度
            enriched["progress"] = enriched.get("progress", "轉錄處理中...")
            if "progress_percentage" not in enriched or enriched["progress_percentage"] is None:
                enriched["progress_percentage"] = 5  # 給一個小的進度值表示已開始

    # 確保 progress_percentage 總是數字
    if "progress_percentage" in enriched and enriched["progress_percentage"] is not None:
        try:
            enriched["progress_percentage"] = float(enriched["progress_percentage"])
        except (TypeError, ValueError):
            enriched["progress_percentage"] = 0

    return enriched


def serialize_for_json(obj):
    """將包含 datetime 等特殊類型的對象轉換為可 JSON 序列化的格式

    Args:
        obj: 要序列化的對象

    Returns:
        可 JSON 序列化的對象
    """
    from datetime import datetime
    from bson import ObjectId

    if isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, ObjectId):
        return str(obj)
    else:
        return obj


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取任務狀態（需認證，只能查看自己的任務）

    Args:
        task_id: 任務 ID
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        任務資料

    Raises:
        HTTPException: 任務不存在或無權訪問
    """
    # 獲取任務（含權限驗證）
    task = await task_service.get_task(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 豐富任務數據
    enriched_task = enrich_task_data(task)

    return enriched_task


@router.get("/{task_id}/events")
async def task_status_events(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user_sse)
):
    """SSE (Server-Sent Events) endpoint for real-time task status updates

    Args:
        task_id: 任務 ID
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        SSE 事件流
    """
    async def event_generator():
        """生成 SSE 事件流"""
        try:
            # 首先驗證權限
            task = await task_service.get_task(task_id, str(current_user["_id"]))

            if not task:
                yield f"event: error\ndata: {json.dumps({'error': '任務不存在或無權訪問'})}\n\n"
                return

            # 持續推送狀態更新
            previous_status = None
            previous_progress = None

            while True:
                # 獲取任務狀態
                task_data = await task_service.get_task(task_id, str(current_user["_id"]))

                if not task_data:
                    yield f"event: error\ndata: {json.dumps({'error': '任務不存在'})}\n\n"
                    break

                # 豐富任務數據
                enriched_data = enrich_task_data(task_data)
                current_status = enriched_data.get("status")
                current_progress = enriched_data.get("progress")

                # 只在狀態或進度改變時推送
                if current_status != previous_status or current_progress != previous_progress:
                    # 序列化數據（處理 datetime 等特殊類型）
                    serialized_data = serialize_for_json(enriched_data)
                    yield f"data: {json.dumps(serialized_data)}\n\n"
                    previous_status = current_status
                    previous_progress = current_progress

                # 如果任務已完成或失敗，結束推送
                if current_status in ["completed", "failed", "cancelled"]:
                    yield f"event: end\ndata: {json.dumps({'status': current_status})}\n\n"
                    break

                # 等待 1 秒再檢查
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            # 客戶端斷開連接
            print(f"🔌 [{task_id}] SSE 連接已關閉")
            raise
        except Exception as e:
            print(f"❌ [{task_id}] SSE 錯誤：{e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 nginx 緩衝
        }
    )


@router.post("/{task_id}/cancel")
async def cancel_task(
    request: Request,
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """取消正在執行的任務（需認證，只能取消自己的任務）

    Args:
        task_id: 任務 ID
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        取消結果

    Raises:
        HTTPException: 任務不存在、無權訪問或無法取消
    """
    # 獲取任務（含權限驗證）
    task = await task_service.get_task(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 只能取消進行中或等待中的任務
    if task["status"] not in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法取消已結束的任務（當前狀態：{task['status']}）"
        )

    # 標記任務為已取消（運行時狀態）
    task_service.cancel_task(task_id)

    # 立即終止 diarization 進程（如果正在運行）
    diarization_process = task_service.get_diarization_process(task_id)
    if diarization_process:
        print(f"🛑 正在強制終止說話者辨識進程...")
        try:
            diarization_process.shutdown(wait=False, cancel_futures=True)
            print(f"✅ 說話者辨識進程已終止")
        except Exception as e:
            print(f"⚠️ 終止 diarization 進程失敗：{e}")

    # 清理臨時目錄
    temp_dir = task_service.get_temp_dir(task_id)
    if temp_dir:
        try:
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                print(f"🗑️ 已清理臨時目錄：{temp_dir.name}")
        except Exception as e:
            print(f"⚠️ 清理臨時目錄失敗：{e}")

    # 更新資料庫中的任務狀態
    await task_service.update_task_status(task_id, {
        "status": "cancelled",
        "error": "用戶取消"
    })

    print(f"🛑 任務 {task_id} 已被標記為取消")

    # 記錄 audit log（取消任務）
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_task_operation(
            request=request,
            action="cancel",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message="取消任務"
        )
    except Exception as e:
        print(f"⚠️ 記錄 audit log 失敗：{e}")

    return {
        "message": "任務取消指令已發送",
        "task_id": task_id,
        "note": "任務將在當前步驟完成後停止"
    }


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """軟刪除任務（標記為已刪除但保留記錄供統計），物理刪除相關檔案

    Args:
        task_id: 任務 ID
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        刪除結果

    Raises:
        HTTPException: 任務不存在、無權訪問或無法刪除
    """
    # 獲取任務（含權限驗證）
    task = await task_service.get_task(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 檢查是否已被刪除
    if task.get("deleted", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任務已被刪除"
        )

    # 不允許刪除進行中的任務
    if task["status"] in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法刪除進行中的任務（當前狀態：{task['status']}），請先取消任務"
        )

    deleted_files = []

    # 物理刪除結果檔案（如果存在）
    result_file_path = get_task_field(task, "result_file")
    if result_file_path:
        result_file = Path(result_file_path)
        try:
            if result_file.exists():
                result_file.unlink()
                deleted_files.append(result_file.name)
                print(f"🗑️ 已刪除轉錄檔案：{result_file.name}")
        except Exception as e:
            print(f"⚠️ 刪除轉錄檔案失敗：{e}")

    # 物理刪除 segments 檔案（如果存在）
    segments_file_path = get_task_field(task, "segments_file")
    if segments_file_path:
        segments_file = Path(segments_file_path)
        try:
            if segments_file.exists():
                segments_file.unlink()
                deleted_files.append(segments_file.name)
                print(f"🗑️ 已刪除 segments 檔案：{segments_file.name}")
        except Exception as e:
            print(f"⚠️ 刪除 segments 檔案失敗：{e}")

    # 物理刪除音檔（如果存在）
    # ⚠️ 手動刪除任務時，應刪除所有相關檔案（包括音檔）
    # keep_audio 只控制「自動清理機制」，不影響「用戶手動刪除」
    audio_file_path = get_task_field(task, "audio_file")
    if audio_file_path:
        audio_file = Path(audio_file_path)
        try:
            if audio_file.exists():
                audio_file.unlink()
                deleted_files.append(audio_file.name)
                print(f"🗑️ 已刪除音檔：{audio_file.name}")
        except Exception as e:
            print(f"⚠️ 刪除音檔失敗：{e}")

    # 清理記憶體狀態
    task_service.cleanup_task_memory(task_id)

    # 在資料庫中標記為已刪除（軟刪除）
    from datetime import datetime
    await task_service.update_task_status(task_id, {
        "deleted": True,
        "deleted_at": datetime.utcnow()
    })

    print(f"🗑️ 任務 {task_id} 已被標記為已刪除")

    return {
        "message": "任務已刪除",
        "task_id": task_id,
        "deleted_files": deleted_files
    }


@router.put("/{task_id}/tags")
async def update_task_tags(
    task_id: str,
    tags_data: dict,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """更新任務標籤

    Args:
        task_id: 任務 ID
        tags_data: 標籤數據 {"tags": ["tag1", "tag2"]}
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在或無權訪問
    """
    # 獲取任務（含權限驗證）
    task = await task_service.get_task(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 更新標籤
    tags = tags_data.get("tags", [])
    await task_service.update_task_status(task_id, {"tags": tags})

    print(f"🏷️ 已更新任務 {task_id} 的標籤：{tags}")

    return {
        "message": "標籤已更新",
        "task_id": task_id,
        "tags": tags
    }


@router.put("/{task_id}/keep-audio")
async def update_keep_audio(
    task_id: str,
    keep_audio_data: dict,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """更新是否保留音檔設定

    Args:
        task_id: 任務 ID
        keep_audio_data: 設定 {"keep_audio": true/false}
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在或無權訪問
    """
    # 獲取任務（含權限驗證）
    task = await task_service.get_task(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    new_keep_audio = keep_audio_data.get("keep_audio", False)

    # 如果要設為 True，檢查保留數量限制
    if new_keep_audio:
        # 查詢該用戶目前有多少個已保留的音檔
        user_id = str(current_user["_id"])
        from src.database.mongodb import MongoDB
        db = MongoDB.get_db()

        # 查詢已保留的音檔任務（排除當前任務和已刪除的任務）
        kept_tasks = await db.tasks.count_documents({
            "user.user_id": user_id,
            "keep_audio": True,
            "_id": {"$ne": task_id},
            "result.audio_file": {"$exists": True, "$ne": None},
            "deleted": {"$ne": True}  # 排除已刪除的任務
        })

        if kept_tasks >= 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="最多只能保留 3 個音檔，請先取消其他音檔的保留設定"
            )

    # 更新設定
    await task_service.update_task_status(task_id, {"keep_audio": new_keep_audio})

    print(f"🎵 已更新任務 {task_id} 的保留音檔設定：{new_keep_audio}")

    return {
        "message": "保留音檔設定已更新",
        "task_id": task_id,
        "keep_audio": new_keep_audio
    }


@router.post("/batch/delete")
async def batch_delete_tasks(
    delete_data: dict,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """批次刪除任務

    Args:
        delete_data: 刪除數據 {"task_ids": ["id1", "id2"]}
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        刪除結果

    Raises:
        HTTPException: 參數錯誤
    """
    task_ids = delete_data.get("task_ids", [])

    if not task_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未提供要刪除的任務 ID"
        )

    deleted_count = 0
    failed_count = 0

    for task_id in task_ids:
        try:
            # 獲取任務（含權限驗證）
            task = await task_service.get_task(task_id, str(current_user["_id"]))

            if not task:
                failed_count += 1
                continue

            # 不允許刪除進行中的任務
            if task["status"] in ["pending", "processing"]:
                failed_count += 1
                continue

            # 刪除檔案和記錄
            from datetime import datetime
            await task_service.update_task_status(task_id, {
                "deleted": True,
                "deleted_at": datetime.utcnow()
            })

            # 清理記憶體
            task_service.cleanup_task_memory(task_id)

            deleted_count += 1

        except Exception as e:
            print(f"❌ 刪除任務 {task_id} 失敗：{e}")
            failed_count += 1

    print(f"🗑️ 批次刪除完成：成功 {deleted_count} 個，失敗 {failed_count} 個")

    return {
        "message": f"批次刪除完成",
        "deleted": deleted_count,
        "failed": failed_count,
        "total": len(task_ids)
    }


@router.post("/batch/tags/add")
async def batch_add_tags(
    tags_data: dict,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """批次添加標籤到任務

    Args:
        tags_data: 標籤數據 {"task_ids": ["id1"], "tags": ["tag1"]}
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        更新結果

    Raises:
        HTTPException: 參數錯誤
    """
    task_ids = tags_data.get("task_ids", [])
    tags_to_add = tags_data.get("tags", [])

    if not task_ids or not tags_to_add:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未提供任務 ID 或標籤"
        )

    updated_count = 0

    for task_id in task_ids:
        try:
            # 獲取任務（含權限驗證）
            task = await task_service.get_task(task_id, str(current_user["_id"]))

            if not task:
                continue

            # 獲取現有標籤
            current_tags = task.get("tags", [])

            # 添加新標籤（去重）
            new_tags = list(set(current_tags + tags_to_add))

            # 更新任務
            await task_service.update_task_status(task_id, {"tags": new_tags})
            updated_count += 1

        except Exception as e:
            print(f"❌ 更新任務 {task_id} 標籤失敗：{e}")

    print(f"🏷️ 批次添加標籤完成：成功 {updated_count} 個")

    return {
        "message": "批次添加標籤完成",
        "updated": updated_count,
        "total": len(task_ids)
    }


@router.post("/batch/tags/remove")
async def batch_remove_tags(
    tags_data: dict,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """批次從任務移除標籤

    Args:
        tags_data: 標籤數據 {"task_ids": ["id1"], "tags": ["tag1"]}
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        更新結果

    Raises:
        HTTPException: 參數錯誤
    """
    task_ids = tags_data.get("task_ids", [])
    tags_to_remove = tags_data.get("tags", [])

    if not task_ids or not tags_to_remove:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未提供任務 ID 或標籤"
        )

    updated_count = 0

    for task_id in task_ids:
        try:
            # 獲取任務（含權限驗證）
            task = await task_service.get_task(task_id, str(current_user["_id"]))

            if not task:
                continue

            # 獲取現有標籤
            current_tags = task.get("tags", [])

            # 移除指定標籤
            new_tags = [tag for tag in current_tags if tag not in tags_to_remove]

            # 更新任務
            await task_service.update_task_status(task_id, {"tags": new_tags})
            updated_count += 1

        except Exception as e:
            print(f"❌ 更新任務 {task_id} 標籤失敗：{e}")

    print(f"🏷️ 批次移除標籤完成：成功 {updated_count} 個")

    return {
        "message": "批次移除標籤完成",
        "updated": updated_count,
        "total": len(task_ids)
    }
