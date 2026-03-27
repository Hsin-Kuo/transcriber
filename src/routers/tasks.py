"""任務管理路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import json
import os

from ..auth.dependencies import get_current_user, get_current_user_sse
from ..database.mongodb import get_database
from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.tag_repo import TagRepository
from ..services.task_service import TaskService
from ..services.tag_service import TagService
from ..services.utils.async_utils import get_current_time
from ..utils.storage_service import is_aws, delete_audio_by_path as storage_delete_audio_by_path, move_audio, extract_tier_from_path

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


router = APIRouter(prefix="/tasks", tags=["Tasks"])


# 允許刪除的目錄白名單（相對於工作目錄的絕對路徑）
_ALLOWED_OUTPUT_DIR = Path("output").resolve()
_ALLOWED_UPLOADS_DIR = Path("uploads").resolve()


def _validate_file_path(file_path: str, allowed_dir: Path) -> Path:
    """驗證檔案路徑在允許的目錄內，防止路徑穿越攻擊

    Args:
        file_path: 要驗證的檔案路徑
        allowed_dir: 允許的目錄（絕對路徑）

    Returns:
        驗證通過的 Path 物件

    Raises:
        ValueError: 路徑不在允許的目錄內
    """
    resolved = Path(file_path).resolve()

    # 檢查是否在允許的目錄下
    try:
        resolved.relative_to(allowed_dir)
    except ValueError:
        raise ValueError(f"路徑不在允許的目錄內: {file_path}")

    return resolved


def get_task_service(db=Depends(get_database)) -> TaskService:
    """依賴注入：獲取 TaskService 實例

    Args:
        db: 資料庫實例

    Returns:
        TaskService 單例實例（確保記憶體狀態共享）
    """
    # ✅ 返回單例而不是創建新實例
    return get_task_service_singleton()


def get_tag_service(db=Depends(get_database)) -> TagService:
    """依賴注入：獲取 TagService 實例

    Args:
        db: 資料庫實例

    Returns:
        TagService 實例
    """
    tag_repo = TagRepository(db)
    task_repo = TaskRepository(db)
    return TagService(tag_repo, task_repo)


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


@router.get("/tags")
async def get_user_tags(
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取使用者所有使用過的標籤

    Args:
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        標籤列表
    """
    tags = await task_service.task_repo.get_all_user_tags(str(current_user["_id"]))

    return {
        "tags": tags
    }


@router.get("")
async def get_tasks(
    status: str = None,
    task_type: str = None,
    tags: str = None,
    has_audio: bool = None,
    limit: int = 100,
    skip: int = 0,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取任務列表（需認證，只能查看自己的任務）

    Args:
        status: 過濾狀態（可選：pending, processing, completed, failed, cancelled, active）
        task_type: 過濾任務類型（可選：paragraph, subtitle）
        tags: 過濾標籤（逗號分隔，例如：tag1,tag2）
        has_audio: 過濾是否有音檔（可選：true 只顯示有音檔的任務）
        limit: 限制數量（預設 100）
        skip: 跳過數量（預設 0）
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        任務列表
    """
    # 取得用戶 tier 的音檔保留天數（JWT 不含 quota，需查 DB）
    from ..models.quota import QUOTA_TIERS, QuotaTier
    from ..database.repositories.user_repo import UserRepository
    user_repo = UserRepository(task_service.task_repo.db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    user_tier = full_user.get("quota", {}).get("tier", "free") if full_user else "free"
    tier_config = QUOTA_TIERS.get(QuotaTier(user_tier), QUOTA_TIERS[QuotaTier.FREE])
    retention_days = tier_config.get("audio_retention_days", 7)

    # 解析標籤參數
    tags_list = None
    if tags:
        tags_list = [tag.strip() for tag in tags.split(',') if tag.strip()]
    # 如果 status 是 'active'，轉換為 pending 和 processing
    if status == 'active':
        # 獲取所有任務並在記憶體中過濾
        all_tasks = await task_service.task_repo.find_by_user(
            str(current_user["_id"]),
            skip=skip,
            limit=limit,
            task_type=task_type,
            tags=tags_list,
            include_deleted=False,
            has_audio=has_audio
        )

        # 過濾出進行中的任務
        active_tasks = []
        for task in all_tasks:
            # 合併記憶體狀態
            task_id = str(task.get("_id") or task.get("task_id"))
            enriched_task = await task_service.get_task(task_id, str(current_user["_id"]))
            if enriched_task and enriched_task.get("status") in ["pending", "processing"]:
                enriched = enrich_task_data(enriched_task)
                filtered = filter_task_for_list(enriched, retention_days)
                active_tasks.append(filtered)

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
            task_type=task_type,
            tags=tags_list,
            include_deleted=False,
            has_audio=has_audio
        )

        # 合併記憶體狀態並過濾數據
        enriched_tasks = []
        for task in tasks:
            task_id = str(task.get("_id") or task.get("task_id"))
            enriched_task = await task_service.get_task(task_id, str(current_user["_id"]))
            if enriched_task:
                enriched = enrich_task_data(enriched_task)
                filtered = filter_task_for_list(enriched, retention_days)
                enriched_tasks.append(filtered)

        # 計算總數（包含 task_type 和 tags 篩選）
        total = await task_service.task_repo.count_by_user(
            str(current_user["_id"]),
            status=status,
            task_type=task_type,
            tags=tags_list,
            include_deleted=False,
            has_audio=has_audio
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


def _is_audio_expired(task: Dict[str, Any], retention_days: int) -> bool:
    """判斷音檔是否已被 S3 Lifecycle 自動刪除

    根據完成時間 + tier 保留天數計算，不需要呼叫 S3。
    keep_audio 的音檔存在 kept/ 資料夾，不受 lifecycle 影響。

    Args:
        task: 任務數據
        retention_days: 該 tier 的保留天數

    Returns:
        True 表示音檔已過期
    """
    if task.get("keep_audio"):
        return False  # 釘選的音檔不會被 lifecycle 刪除

    completed_at = task.get("timestamps", {}).get("completed_at")
    if not completed_at:
        return False

    if isinstance(completed_at, (int, float)):
        completed_at = datetime.fromtimestamp(completed_at, tz=timezone.utc)
    elif isinstance(completed_at, str):
        completed_at = datetime.fromisoformat(completed_at)

    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)

    from datetime import timedelta
    expiry_time = completed_at + timedelta(days=retention_days)
    return datetime.now(timezone.utc) > expiry_time


def filter_task_for_list(task: Dict[str, Any], retention_days: int = 7) -> Dict[str, Any]:
    """過濾任務數據，只返回前端列表需要的字段

    Args:
        task: 完整的任務數據
        retention_days: 用戶 tier 的音檔保留天數

    Returns:
        過濾後的任務數據（只包含前端需要的字段）
    """
    # 只保留前端需要的字段
    filtered = {
        "_id": task.get("_id"),
        "task_id": task.get("_id"),  # 保留以便向後兼容
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "progress_percentage": task.get("progress_percentage"),
        "custom_name": task.get("custom_name"),
        "tags": task.get("tags", []),
        "keep_audio": task.get("keep_audio", False),
        "speaker_names": task.get("speaker_names", {}),
        "subtitle_settings": task.get("subtitle_settings", {}),
        "timestamps": task.get("timestamps", {}),
    }

    # file 信息
    if task.get("file"):
        filtered["file"] = {
            "filename": task["file"].get("filename"),
            "size_mb": task["file"].get("size_mb")
        }

    # result 信息（只保留前端需要的）
    if task.get("result"):
        audio_file = task["result"].get("audio_file")
        audio_filename = task["result"].get("audio_filename")

        # 音檔已被 S3 Lifecycle 自動刪除時，不回傳 audio_file
        if audio_file and _is_audio_expired(task, retention_days):
            audio_file = None
            audio_filename = None

        filtered["result"] = {
            "text_length": task["result"].get("text_length"),
            "word_count": task["result"].get("word_count"),
            "audio_file": audio_file,
            "audio_filename": audio_filename
        }

    # error 信息（失敗時需要）
    if task.get("error"):
        filtered["error"] = task.get("error")

    # cancelling 狀態（取消中時需要）
    if task.get("cancelling"):
        filtered["cancelling"] = task.get("cancelling")

    return filtered


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
        # AWS 模式下 Worker 更新 MongoDB，Web Server 輪詢 DB；
        # 本地模式使用 in-memory state
        poll_interval = 2 if is_aws() else 1

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
                if is_aws():
                    # AWS 模式：直接從 MongoDB 讀取（Worker 寫入 DB）
                    task_data = await task_service.task_repo.get_by_id(task_id)
                    if task_data:
                        # 驗證用戶權限
                        task_user_id = task_data.get("user", {}).get("user_id")
                        if task_user_id != str(current_user["_id"]):
                            task_data = None
                else:
                    # 本地模式：使用 in-memory state（現有行為）
                    task_data = await task_service.get_task(task_id, str(current_user["_id"]))

                if not task_data:
                    yield f"event: error\ndata: {json.dumps({'error': '任務不存在'})}\n\n"
                    break

                # 豐富任務數據
                enriched_data = enrich_task_data(task_data)
                current_status = enriched_data.get("status")
                current_progress = enriched_data.get("progress")

                # 調試：輸出當前進度
                print(f"📡 [SSE {task_id}] status={current_status}, progress={current_progress}", flush=True)

                # 只在狀態或進度改變時推送
                if current_status != previous_status or current_progress != previous_progress:
                    print(f"📤 [SSE {task_id}] 推送更新: {current_progress}", flush=True)
                    # 序列化數據（處理 datetime 等特殊類型）
                    serialized_data = serialize_for_json(enriched_data)
                    yield f"data: {json.dumps(serialized_data)}\n\n"
                    previous_status = current_status
                    previous_progress = current_progress

                # 如果任務已完成或失敗，結束推送
                if current_status in ["completed", "failed", "cancelled"]:
                    yield f"event: end\ndata: {json.dumps({'status': current_status})}\n\n"
                    break

                # 等待再檢查（AWS 間隔較長因為是 DB polling）
                await asyncio.sleep(poll_interval)

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

    # 1. 立即更新資料庫狀態為「取消中」，避免刷新頁面時誤判任務仍在進行
    await task_service.update_task_status(task_id, {
        "status": "canceling",
        "progress": "正在取消任務..."
    })
    print(f"🔄 任務 {task_id} 狀態已更新為 canceling")

    # 2. 標記任務為已取消（運行時狀態）
    task_service.cancel_task(task_id)

    # 3. 立即終止 diarization 進程（如果正在運行）
    diarization_process = task_service.get_diarization_process(task_id)
    if diarization_process:
        print(f"🛑 正在強制終止說話者辨識進程...")
        try:
            diarization_process.shutdown(wait=False, cancel_futures=True)
            print(f"✅ 說話者辨識進程已終止")
        except Exception as e:
            print(f"⚠️ 終止 diarization 進程失敗：{e}")

    # 4. 清理臨時目錄
    temp_dir = task_service.get_temp_dir(task_id)
    if temp_dir:
        try:
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                print(f"🗑️ 已清理臨時目錄：{temp_dir.name}")
        except Exception as e:
            print(f"⚠️ 清理臨時目錄失敗：{e}")

    # 5. 更新資料庫中的任務狀態為「已取消」
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
    request: Request,
    task_id: str,
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """軟刪除任務（標記為已刪除但保留記錄供統計），物理刪除相關檔案

    Args:
        request: Request 對象
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

    # 物理刪除結果檔案（僅本地模式，AWS 模式結果存在 MongoDB）
    if not is_aws():
        result_file_path = get_task_field(task, "result_file")
        if result_file_path:
            try:
                result_file = _validate_file_path(result_file_path, _ALLOWED_OUTPUT_DIR)
                if result_file.exists():
                    result_file.unlink()
                    deleted_files.append(result_file.name)
                    print(f"🗑️ 已刪除轉錄檔案：{result_file.name}")
            except ValueError as e:
                print(f"⚠️ 路徑驗證失敗，跳過刪除：{e}")
            except Exception as e:
                print(f"⚠️ 刪除轉錄檔案失敗：{e}")

        # 物理刪除 segments 檔案
        segments_file_path = get_task_field(task, "segments_file")
        if segments_file_path:
            try:
                segments_file = _validate_file_path(segments_file_path, _ALLOWED_OUTPUT_DIR)
                if segments_file.exists():
                    segments_file.unlink()
                    deleted_files.append(segments_file.name)
                    print(f"🗑️ 已刪除 segments 檔案：{segments_file.name}")
            except ValueError as e:
                print(f"⚠️ 路徑驗證失敗，跳過刪除：{e}")
            except Exception as e:
                print(f"⚠️ 刪除 segments 檔案失敗：{e}")

    # 物理刪除音檔（如果存在）
    # ⚠️ 手動刪除任務時，應刪除所有相關檔案（包括音檔）
    # keep_audio 只控制「自動清理機制」，不影響「用戶手動刪除」
    try:
        audio_file_path = task.get("result", {}).get("audio_file") if task else None
        if audio_file_path:
            storage_delete_audio_by_path(audio_file_path)
        deleted_files.append(f"{task_id}.mp3")
        print(f"🗑️ 已刪除音檔：{task_id}.mp3")
    except Exception as e:
        print(f"⚠️ 刪除音檔失敗：{e}")

    # 清理記憶體狀態
    task_service.cleanup_task_memory(task_id)

    # 物理刪除 MongoDB 中的 transcription 文檔
    from src.database.repositories.transcription_repo import TranscriptionRepository
    transcription_repo = TranscriptionRepository(task_service.task_repo.db)
    try:
        deleted_transcription = await transcription_repo.delete(task_id)
        if deleted_transcription:
            print(f"🗑️ 已刪除 MongoDB transcription 文檔：{task_id}")
    except Exception as e:
        print(f"⚠️ 刪除 transcription 文檔失敗：{e}")

    # 物理刪除 MongoDB 中的 segment 文檔
    from src.database.repositories.segment_repo import SegmentRepository
    segment_repo = SegmentRepository(task_service.task_repo.db)
    try:
        deleted_segment = await segment_repo.delete(task_id)
        if deleted_segment:
            print(f"🗑️ 已刪除 MongoDB segment 文檔：{task_id}")
    except Exception as e:
        print(f"⚠️ 刪除 segment 文檔失敗：{e}")

    # 在資料庫中標記為已刪除（軟刪除 tasks）
    from datetime import datetime
    await task_service.update_task_status(task_id, {
        "deleted": True,
        "deleted_at": datetime.utcnow()
    })

    print(f"🗑️ 任務 {task_id} 已被標記為已刪除")

    # 記錄 audit log（刪除任務）- 詳細記錄
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()

        # 取得任務詳細資訊
        original_filename = task.get("custom_name") or get_task_field(task, "original_filename") or "未知"
        audio_duration = get_task_field(task, "audio_duration") or 0
        audio_size = get_task_field(task, "audio_size") or 0
        task_status = task.get("status", "unknown")

        await audit_logger.log_task_operation(
            request=request,
            action="delete",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"刪除任務：{original_filename}",
            request_body={
                "original_filename": original_filename,
                "audio_duration_seconds": audio_duration,
                "audio_size_bytes": audio_size,
                "task_status": task_status,
                "deleted_files_count": len(deleted_files),
                "deleted_files": deleted_files
            }
        )
    except Exception as e:
        print(f"⚠️ 記錄 audit log 失敗：{e}")

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
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """更新任務標籤

    Args:
        task_id: 任務 ID
        tags_data: 標籤數據 {"tags": ["tag1", "tag2"]}
        task_service: TaskService 實例
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在或無權訪問
    """
    try:
        # 獲取任務（含權限驗證）
        task = await task_service.get_task(task_id, str(current_user["_id"]))

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任務不存在或無權訪問"
            )

        # 更新標籤
        tags = tags_data.get("tags", [])
        user_id = str(current_user["_id"])

        # 自動為新標籤創建記錄到 tags 表
        try:
            existing_tags = await tag_service.get_all_tags(user_id)
            existing_tag_names = {tag["name"] for tag in existing_tags}

            # 創建不存在的標籤
            for tag_name in tags:
                if tag_name and tag_name not in existing_tag_names:
                    try:
                        await tag_service.create_tag(user_id=user_id, name=tag_name)
                        print(f"🏷️ 自動創建標籤記錄：{tag_name}")
                    except ValueError as e:
                        # 標籤可能已存在（並發情況），忽略錯誤
                        print(f"⚠️ 創建標籤 {tag_name} 時出現警告：{e}")
        except Exception as tag_error:
            # 自動創建標籤失敗不應該阻止標籤更新
            print(f"⚠️ 自動創建標籤時出錯（不影響標籤更新）：{tag_error}")

        await task_service.update_task_status(task_id, {"tags": tags})

        print(f"🏷️ 已更新任務 {task_id} 的標籤：{tags}")

        return {
            "message": "標籤已更新",
            "task_id": task_id,
            "tags": tags
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 更新標籤時發生錯誤：{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新標籤失敗：{str(e)}"
        )


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
            detail={
                "error_code": "TASK_NOT_FOUND",
                "message": "任務不存在或無權訪問"
            }
        )

    new_keep_audio = keep_audio_data.get("keep_audio", False)

    user_id = str(current_user["_id"])
    from src.database.mongodb import MongoDB
    db = MongoDB.get_db()

    # 取得用戶方案的保留額度
    from src.database.repositories.user_repo import UserRepository
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(user_id)
    user_tier = full_user.get("quota", {}).get("tier", "free") if full_user else "free"

    from src.models.quota import QUOTA_TIERS, QuotaTier
    tier_config = QUOTA_TIERS.get(QuotaTier(user_tier), QUOTA_TIERS[QuotaTier.FREE])
    max_keep = tier_config.get("max_keep_audio", 0)

    if new_keep_audio:
        # 免費方案不能手動保留
        if max_keep <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "KEEP_AUDIO_NOT_AVAILABLE",
                    "message": "目前方案不支援手動保留音檔，請升級方案"
                }
            )

        # 查詢已保留的音檔任務（排除當前任務和已刪除的任務）
        kept_tasks = await db.tasks.count_documents({
            "user.user_id": user_id,
            "keep_audio": True,
            "_id": {"$ne": task_id},
            "result.audio_file": {"$exists": True, "$ne": None},
            "deleted": {"$ne": True}
        })

        if kept_tasks >= max_keep:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "KEEP_AUDIO_LIMIT_EXCEEDED",
                    "message": f"最多只能保留 {max_keep} 個音檔，請先取消其他音檔的保留設定"
                }
            )

    # 在 AWS 模式下搬移音檔（tier 資料夾 ↔ kept 資料夾）
    audio_file_path = task.get("result", {}).get("audio_file")
    new_audio_path = audio_file_path
    if is_aws() and audio_file_path:
        current_tier = extract_tier_from_path(audio_file_path)
        if new_keep_audio and current_tier and current_tier != "kept":
            # 搬到 kept 資料夾（不受 Lifecycle 影響）
            new_audio_path = move_audio(task_id, current_tier, "kept")
        elif not new_keep_audio and current_tier == "kept":
            # 檢查音檔是否已超過保留期限
            if _is_audio_expired(task, tier_config.get("audio_retention_days", 7)):
                # 已過期，直接刪除
                storage_delete_audio_by_path(audio_file_path)
                new_audio_path = None
                print(f"🗑️ 音檔已超過保留期限，直接刪除: {audio_file_path}")
            else:
                # 未過期，搬回原本的 tier 資料夾（重新受 Lifecycle 管理）
                new_audio_path = move_audio(task_id, "kept", user_tier)

    # 更新設定
    update_fields = {"keep_audio": new_keep_audio}
    if new_audio_path != audio_file_path:
        update_fields["result.audio_file"] = new_audio_path
    await task_service.update_task_status(task_id, update_fields)

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

            # 檢查是否已被刪除
            if task.get("deleted", False):
                failed_count += 1
                continue

            # 不允許刪除進行中的任務
            if task["status"] in ["pending", "processing"]:
                failed_count += 1
                continue

            # 物理刪除結果檔案（僅本地模式，AWS 模式結果存在 MongoDB）
            if not is_aws():
                result_file_path = get_task_field(task, "result_file")
                if result_file_path:
                    try:
                        result_file = _validate_file_path(result_file_path, _ALLOWED_OUTPUT_DIR)
                        if result_file.exists():
                            result_file.unlink()
                            print(f"🗑️ [批次] 已刪除轉錄檔案：{result_file.name}")
                    except ValueError as e:
                        print(f"⚠️ [批次] 路徑驗證失敗，跳過刪除：{e}")
                    except Exception as e:
                        print(f"⚠️ [批次] 刪除轉錄檔案失敗：{e}")

                # 物理刪除 segments 檔案
                segments_file_path = get_task_field(task, "segments_file")
                if segments_file_path:
                    try:
                        segments_file = _validate_file_path(segments_file_path, _ALLOWED_OUTPUT_DIR)
                        if segments_file.exists():
                            segments_file.unlink()
                            print(f"🗑️ [批次] 已刪除 segments 檔案：{segments_file.name}")
                    except ValueError as e:
                        print(f"⚠️ [批次] 路徑驗證失敗，跳過刪除：{e}")
                    except Exception as e:
                        print(f"⚠️ [批次] 刪除 segments 檔案失敗：{e}")

            # 物理刪除音檔（使用 storage_service）
            try:
                batch_audio_path = task.get("result", {}).get("audio_file") if task else None
                if batch_audio_path:
                    storage_delete_audio_by_path(batch_audio_path)
                print(f"🗑️ [批次] 已刪除音檔：{task_id}.mp3")
            except Exception as e:
                print(f"⚠️ [批次] 刪除音檔失敗：{e}")

            # 清理記憶體
            task_service.cleanup_task_memory(task_id)

            # 物理刪除 MongoDB 中的 transcription 文檔
            from src.database.repositories.transcription_repo import TranscriptionRepository
            transcription_repo = TranscriptionRepository(task_service.task_repo.db)
            try:
                deleted_transcription = await transcription_repo.delete(task_id)
                if deleted_transcription:
                    print(f"🗑️ [批次] 已刪除 MongoDB transcription 文檔：{task_id}")
            except Exception as e:
                print(f"⚠️ [批次] 刪除 transcription 文檔失敗：{e}")

            # 物理刪除 MongoDB 中的 segment 文檔
            from src.database.repositories.segment_repo import SegmentRepository
            segment_repo = SegmentRepository(task_service.task_repo.db)
            try:
                deleted_segment = await segment_repo.delete(task_id)
                if deleted_segment:
                    print(f"🗑️ [批次] 已刪除 MongoDB segment 文檔：{task_id}")
            except Exception as e:
                print(f"⚠️ [批次] 刪除 segment 文檔失敗：{e}")

            # 在資料庫中標記為已刪除（軟刪除 tasks）
            from datetime import datetime
            await task_service.update_task_status(task_id, {
                "deleted": True,
                "deleted_at": datetime.utcnow()
            })

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
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """批次添加標籤到任務

    Args:
        tags_data: 標籤數據 {"task_ids": ["id1"], "tags": ["tag1"]}
        task_service: TaskService 實例
        tag_service: TagService 實例
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

    # 自動為新標籤創建記錄到 tags 表
    user_id = str(current_user["_id"])

    # 獲取現有標籤
    existing_tags = await tag_service.get_all_tags(user_id)
    existing_tag_names = {tag["name"] for tag in existing_tags}

    # 創建不存在的標籤
    for tag_name in tags_to_add:
        if tag_name and tag_name not in existing_tag_names:
            try:
                await tag_service.create_tag(user_id=user_id, name=tag_name)
                print(f"🏷️ 自動創建標籤記錄：{tag_name}")
            except ValueError as e:
                # 標籤可能已存在（並發情況），忽略錯誤
                print(f"⚠️ 創建標籤 {tag_name} 時出現警告：{e}")

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


@router.get("/system/health/processes")
async def check_system_processes(
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """檢查系統進程健康狀態

    檢測是否有孤立的 worker 進程，並返回詳細資訊

    Args:
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        系統進程健康狀態
    """
    if not PSUTIL_AVAILABLE:
        return {
            "status": "unavailable",
            "message": "psutil 未安裝，無法檢查進程狀態"
        }

    try:
        current_pid = os.getpid()
        current_process = psutil.Process(current_pid)

        # 查找所有子進程
        children = current_process.children(recursive=True)

        # 找出 multiprocessing worker 進程
        multiprocessing_workers = []
        for child in children:
            try:
                cmdline = " ".join(child.cmdline())
                if "multiprocessing" in cmdline and "spawn_main" in cmdline:
                    worker_info = {
                        "pid": child.pid,
                        "cpu_percent": round(child.cpu_percent(), 1),
                        "memory_mb": round(child.memory_info().rss / 1024 / 1024, 1),
                        "status": child.status(),
                        "create_time": child.create_time()
                    }
                    multiprocessing_workers.append(worker_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # 查找活動任務
        active_tasks = await task_service.task_repo.collection.find(
            {"status": {"$in": ["pending", "processing"]}},
            {"task_id": 1, "status": 1}
        ).to_list(length=100)

        active_task_count = len(active_tasks)
        worker_count = len(multiprocessing_workers)

        # 判斷是否有異常
        has_orphaned = worker_count > 0 and active_task_count == 0
        warning = None

        if has_orphaned:
            warning = f"發現 {worker_count} 個孤立 worker 進程（無活動任務）"
        elif worker_count > active_task_count * 3:
            warning = f"Worker 進程數量異常（{worker_count} workers vs {active_task_count} tasks）"

        return {
            "status": "healthy" if not warning else "warning",
            "timestamp": get_current_time().isoformat(),
            "active_tasks": active_task_count,
            "worker_processes": worker_count,
            "workers": multiprocessing_workers,
            "warning": warning,
            "process_info": {
                "main_pid": current_pid,
                "main_cpu_percent": round(current_process.cpu_percent(), 1),
                "main_memory_mb": round(current_process.memory_info().rss / 1024 / 1024, 1)
            }
        }

    except Exception as e:
        print(f"❌ 檢查進程健康狀態失敗：{e}")
        return {
            "status": "error",
            "message": f"檢查失敗: {str(e)}"
        }


@router.post("/system/cleanup/orphaned-processes")
async def cleanup_orphaned_processes_endpoint(
    task_service: TaskService = Depends(get_task_service),
    current_user: dict = Depends(get_current_user)
):
    """手動清理孤立的 worker 進程

    終止所有沒有對應活動任務的 worker 進程

    Args:
        task_service: TaskService 實例
        current_user: 當前用戶

    Returns:
        清理結果
    """
    if not PSUTIL_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="psutil 未安裝，無法執行進程清理"
        )

    try:
        print(f"🧹 使用者 {current_user.get('email', 'unknown')} 手動觸發孤立進程清理")
        await task_service.cleanup_orphaned_processes()

        return {
            "status": "success",
            "message": "孤立進程清理完成",
            "timestamp": get_current_time().isoformat()
        }

    except Exception as e:
        print(f"❌ 手動清理孤立進程失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清理失敗: {str(e)}"
        )
