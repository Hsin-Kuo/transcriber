"""任務管理路由"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from typing import Dict, Any
from datetime import datetime, timezone
import asyncio
import json
import os

from ..auth.dependencies import get_current_user, get_current_user_sse
from ..database.repositories.task_repo import TaskRepository
from ..services.task_service import TaskService
from ..services.tag_service import TagService
from ..services.task_query_helpers import (
    enrich_task_data,
    filter_task_for_list,
    get_task_field,
    is_audio_expired,
    serialize_for_json,
    get_user_retention_days,
)
from ..dependencies import get_task_service, get_tag_service
from ..services.utils.async_utils import get_current_time
from ..utils.storage_service import is_aws, delete_audio_by_path as storage_delete_audio_by_path, move_audio, extract_tier_from_path
from ..utils.logger import get_logger

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


router = APIRouter(prefix="/tasks", tags=["Tasks"])
log = get_logger(__name__)



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
    # 從資料庫獲取最近的任務（排除終止狀態：nav 只顯示可用任務）
    tasks = await task_service.task_repo.find_by_user(
        str(current_user["_id"]),
        skip=0,
        limit=limit,
        status_nin=["failed", "cancelled"],
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
    background_tasks: BackgroundTasks = None,
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
    retention_days = await get_user_retention_days(task_service.task_repo.db, str(current_user["_id"]))

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
                had_audio = bool(enriched.get("result", {}).get("audio_file"))
                filtered = filter_task_for_list(enriched, retention_days)
                if had_audio and not filtered.get("result", {}).get("audio_file"):
                    if background_tasks:
                        background_tasks.add_task(
                            _clear_expired_audio_in_db,
                            task_service.task_repo,
                            task_id
                        )
                    continue
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
                had_audio = bool(enriched.get("result", {}).get("audio_file"))
                filtered = filter_task_for_list(enriched, retention_days)
                if had_audio and not filtered.get("result", {}).get("audio_file"):
                    if background_tasks:
                        background_tasks.add_task(
                            _clear_expired_audio_in_db,
                            task_service.task_repo,
                            task_id
                        )
                    continue
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


async def _clear_expired_audio_in_db(task_repo: TaskRepository, task_id: str) -> None:
    """S3 Lifecycle 已刪除音檔後，同步清除 MongoDB 裡的路徑，
    讓 has_audio=true 篩選在後續查詢中能正確排除這些任務。"""
    await task_repo.update(task_id, {
        "result.audio_file": None,
        "result.audio_filename": None
    })


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

    retention_days = await get_user_retention_days(task_service.task_repo.db, str(current_user["_id"]))
    enriched_task["audio_retention_days"] = retention_days

    # 若音檔已過期，清除 audio_file 並標記
    audio_file = enriched_task.get("result", {}).get("audio_file")
    if audio_file and is_audio_expired(enriched_task, retention_days):
        enriched_task["audio_expired"] = True
        enriched_task["result"]["audio_file"] = None
        enriched_task["result"]["audio_filename"] = None
    else:
        enriched_task["audio_expired"] = False

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
        """生成 SSE 事件流（兩種部署模式統一走 task_service.get_task → ProgressStore）"""
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
            heartbeat_counter = 0

            while True:
                task_data = await task_service.get_task(task_id, str(current_user["_id"]))

                if not task_data:
                    yield f"event: error\ndata: {json.dumps({'error': '任務不存在'})}\n\n"
                    break

                # 豐富任務數據
                enriched_data = enrich_task_data(task_data)
                current_status = enriched_data.get("status")
                current_progress = enriched_data.get("progress")

                # 調試：輸出當前進度
                log.debug("sse.poll.tick", task_id=task_id, status=current_status, progress=current_progress)

                # 只在狀態或進度改變時推送
                if current_status != previous_status or current_progress != previous_progress:
                    log.debug("sse.progress.pushed", task_id=task_id, progress=current_progress)
                    # 序列化數據（處理 datetime 等特殊類型）
                    serialized_data = serialize_for_json(enriched_data)
                    yield f"data: {json.dumps(serialized_data)}\n\n"
                    previous_status = current_status
                    previous_progress = current_progress
                    heartbeat_counter = 0
                else:
                    # 每 25 秒送一次 heartbeat comment，防止 ALB / proxy 因 idle timeout 斷線
                    heartbeat_counter += 1
                    if heartbeat_counter >= (25 // poll_interval):
                        yield ": heartbeat\n\n"
                        heartbeat_counter = 0

                # 如果任務已完成或失敗，結束推送
                if current_status in ["completed", "failed", "cancelled"]:
                    yield f"event: end\ndata: {json.dumps({'status': current_status})}\n\n"
                    break

                # 等待再檢查（AWS 間隔較長因為是 DB polling）
                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            # 客戶端斷開連接
            log.debug("sse.stream.closed", task_id=task_id)
            raise
        except Exception as e:
            log.error("sse.stream.error", task_id=task_id, error=str(e), exc_info=True)
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
    log.info("task.cancel.requested", task_id=task_id)

    # 2. 標記任務為已取消（運行時狀態）
    task_service.cancel_task(task_id)

    # 3. 立即終止 diarization 進程（如果正在運行）
    diarization_process = task_service.get_diarization_process(task_id)
    if diarization_process:
        try:
            diarization_process.shutdown(wait=False, cancel_futures=True)
            log.debug("task.cancel.diarization_terminated", task_id=task_id)
        except Exception as e:
            log.warning("task.cancel.diarization_terminate_failed", task_id=task_id, error=str(e))

    # 4. 清理臨時目錄
    temp_dir = task_service.get_temp_dir(task_id)
    if temp_dir:
        try:
            import shutil
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                log.debug("task.cancel.temp_dir_cleaned", task_id=task_id, temp_dir=temp_dir.name)
        except Exception as e:
            log.warning("task.cancel.temp_dir_cleanup_failed", task_id=task_id, error=str(e))

    # 5. 更新資料庫中的任務狀態為「已取消」
    await task_service.update_task_status(task_id, {
        "status": "cancelled",
        "error": {"code": "USER_CANCELLED", "message": "用戶取消"}
    })

    log.info("task.cancelled", task_id=task_id)

    # 6. 釋放預扣配額（idempotent）
    try:
        from ..database.repositories.reservation_repo import ReservationRepository
        db = task_service.task_repo.db
        reservation_repo = ReservationRepository(db)
        released = await reservation_repo.release_by_task_id(task_id)
        if released:
            log.debug("task.cancel.reservation_released", task_id=task_id)
    except Exception as e:
        log.warning("task.cancel.reservation_release_failed", task_id=task_id, error=str(e))

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
        log.warning("task.cancel.audit_log_failed", task_id=task_id, error=str(e))

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
    """軟刪除任務（標記為已刪除但保留記錄供統計），物理刪除相關檔案"""
    task = await task_service.get_task(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    if task.get("deleted", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任務已被刪除"
        )

    if task["status"] in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法刪除進行中的任務（當前狀態：{task['status']}），請先取消任務"
        )

    deleted_files = await task_service.soft_delete_full(task, task_id)

    # 記錄 audit log
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()

        original_filename = task.get("custom_name") or get_task_field(task, "original_filename") or "未知"

        await audit_logger.log_task_operation(
            request=request,
            action="delete",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"刪除任務：{original_filename}",
            request_body={
                "original_filename": original_filename,
                "task_status": task.get("status", "unknown"),
                "deleted_files_count": len(deleted_files),
                "deleted_files": deleted_files
            }
        )
    except Exception as e:
        log.warning("task.delete.audit_log_failed", task_id=task_id, error=str(e))

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
                        log.debug("tag.auto_created", tag_name=tag_name)
                    except ValueError as e:
                        # 標籤可能已存在（並發情況），忽略錯誤
                        log.warning("tag.auto_create_conflict", tag_name=tag_name, error=str(e))
        except Exception as tag_error:
            # 自動創建標籤失敗不應該阻止標籤更新
            log.warning("tag.auto_create_failed", error=str(tag_error))

        await task_service.update_task_status(task_id, {"tags": tags})

        log.info("task.tags.updated", task_id=task_id, tags=tags)

        return {
            "message": "標籤已更新",
            "task_id": task_id,
            "tags": tags
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("task.tags.update_failed", error_type=type(e).__name__, error=str(e), exc_info=True)
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
            if is_audio_expired(task, tier_config.get("audio_retention_days", 7)):
                # 已過期，直接刪除
                storage_delete_audio_by_path(audio_file_path)
                new_audio_path = None
                log.debug("task.keep_audio.expired_deleted", task_id=task_id, audio_file=audio_file_path)
            else:
                # 未過期，搬回原本的 tier 資料夾（重新受 Lifecycle 管理）
                new_audio_path = move_audio(task_id, "kept", user_tier)

    # 更新設定
    update_fields = {"keep_audio": new_keep_audio}
    if new_audio_path != audio_file_path:
        update_fields["result.audio_file"] = new_audio_path
    await task_service.update_task_status(task_id, update_fields)

    log.info("task.keep_audio.updated", task_id=task_id, keep_audio=new_keep_audio)

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
    """批次刪除任務"""
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
            task = await task_service.get_task(task_id, str(current_user["_id"]))

            if not task or task.get("deleted", False) or task["status"] in ["pending", "processing"]:
                failed_count += 1
                continue

            await task_service.soft_delete_full(task, task_id)
            deleted_count += 1

        except Exception as e:
            log.error("task.batch_delete.task_failed", task_id=task_id, error=str(e))
            failed_count += 1

    log.info("task.batch_delete.completed", deleted_count=deleted_count, failed_count=failed_count)

    return {
        "message": "批次刪除完成",
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
                log.debug("tag.auto_created", tag_name=tag_name)
            except ValueError as e:
                # 標籤可能已存在（並發情況），忽略錯誤
                log.warning("tag.auto_create_conflict", tag_name=tag_name, error=str(e))

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
            log.error("task.batch_add_tags.task_failed", task_id=task_id, error=str(e))

    log.info("task.batch_add_tags.completed", updated_count=updated_count)

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
            log.error("task.batch_remove_tags.task_failed", task_id=task_id, error=str(e))

    log.info("task.batch_remove_tags.completed", updated_count=updated_count)

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
        log.error("task.system.health_check_failed", error=str(e), exc_info=True)
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
        log.info("task.system.cleanup.requested", user_email=current_user.get('email', 'unknown'))
        await task_service.cleanup_orphaned_processes()

        return {
            "status": "success",
            "message": "孤立進程清理完成",
            "timestamp": get_current_time().isoformat()
        }

    except Exception as e:
        log.error("task.system.cleanup.failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清理失敗: {str(e)}"
        )
