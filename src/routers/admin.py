"""
管理後台 API - 用戶管理、任務管理、統計、審計日誌
"""
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from ..auth.dependencies import get_current_admin, get_database
from ..auth.password import hash_password
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.audit_log_repo import AuditLogRepository
from ..models.quota import QuotaTier, QUOTA_TIERS
from ..utils.time_utils import get_utc_timestamp
from ..utils.audit_logger import log_admin_action

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))


# ========== Pydantic Models ==========

class UpdateUserStatusRequest(BaseModel):
    """更新用戶狀態請求"""
    is_active: bool


class UpdateUserRoleRequest(BaseModel):
    """更新用戶角色請求"""
    role: str  # "user" or "admin"


class UpdateUserQuotaRequest(BaseModel):
    """更新用戶配額請求"""
    tier: Optional[str] = None  # QuotaTier value
    custom: Optional[dict] = None  # 自訂配額（覆蓋預設）


class BatchDeleteTasksRequest(BaseModel):
    """批次刪除任務請求"""
    task_ids: List[str]


class ResetPasswordRequest(BaseModel):
    """重設用戶密碼請求"""
    new_password: str


# ========== 用戶管理 API ==========

@router.get("/users")
async def list_users(
    search: Optional[str] = Query(None, description="搜尋 email"),
    role: Optional[str] = Query(None, description="篩選角色 (user/admin)"),
    is_active: Optional[bool] = Query(None, description="篩選狀態"),
    tier: Optional[str] = Query(None, description="篩選配額等級"),
    sort_by: str = Query("created_at", description="排序欄位"),
    sort_order: int = Query(-1, description="排序方向 (1=升序, -1=降序)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取用戶列表（管理員）"""
    user_repo = UserRepository(db)
    task_repo = TaskRepository(db)

    # 建立篩選條件
    filters = {}

    if search:
        filters["email"] = {"$regex": search, "$options": "i"}

    if role:
        filters["role"] = role

    if is_active is not None:
        filters["is_active"] = is_active

    if tier:
        filters["quota.tier"] = tier

    # 查詢用戶
    sort = [(sort_by, sort_order)]
    users = await user_repo.find(filters, skip=skip, limit=limit, sort=sort)
    total = await user_repo.count(filters)

    # 處理用戶資料（移除敏感資訊、加入統計）
    result = []
    for user in users:
        user_id = str(user["_id"])

        # 計算任務統計
        task_count = await task_repo.count_by_user(user_id)
        active_task_count = await task_repo.collection.count_documents({
            "$or": [
                {"user.user_id": user_id},
                {"user_id": user_id}
            ],
            "status": {"$in": ["pending", "processing"]}
        })

        result.append({
            "id": user_id,
            "email": user.get("email"),
            "role": user.get("role", "user"),
            "is_active": user.get("is_active", True),
            "email_verified": user.get("email_verified", False),
            "quota": user.get("quota", {}),
            "usage": user.get("usage", {}),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
            "task_count": task_count,
            "active_task_count": active_task_count
        })

    return {
        "users": result,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取用戶詳情（管理員）"""
    user_repo = UserRepository(db)
    task_repo = TaskRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 計算任務統計
    task_count = await task_repo.count_by_user(user_id)
    completed_count = await task_repo.count_by_user(user_id, status="completed")
    failed_count = await task_repo.count_by_user(user_id, status="failed")

    # 獲取最近任務
    recent_tasks = await task_repo.find_by_user(user_id, limit=10)
    recent_tasks_summary = []
    for task in recent_tasks:
        recent_tasks_summary.append({
            "task_id": task.get("_id") or task.get("task_id"),
            "filename": task.get("file", {}).get("filename") or task.get("filename"),
            "status": task.get("status"),
            "created_at": task.get("timestamps", {}).get("created_at") or task.get("created_at")
        })

    return {
        "id": str(user["_id"]),
        "email": user.get("email"),
        "role": user.get("role", "user"),
        "is_active": user.get("is_active", True),
        "email_verified": user.get("email_verified", False),
        "quota": user.get("quota", {}),
        "usage": user.get("usage", {}),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
        "stats": {
            "total_tasks": task_count,
            "completed_tasks": completed_count,
            "failed_tasks": failed_count
        },
        "recent_tasks": recent_tasks_summary
    }


@router.put("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    request: UpdateUserStatusRequest,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """停用/啟用用戶帳號（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 不能停用自己
    if str(admin["_id"]) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能停用自己的帳號"
        )

    success = await user_repo.update(user_id, {"is_active": request.is_active})

    if success:
        # 記錄操作
        action = "enable_user" if request.is_active else "disable_user"
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action=action,
            resource_type="user",
            resource_id=user_id,
            details={"email": user.get("email"), "is_active": request.is_active}
        )

    return {
        "success": success,
        "message": f"用戶已{'啟用' if request.is_active else '停用'}"
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    request: UpdateUserRoleRequest,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """修改用戶角色（管理員）"""
    if request.role not in ["user", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色只能是 'user' 或 'admin'"
        )

    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 不能修改自己的角色
    if str(admin["_id"]) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己的角色"
        )

    success = await user_repo.update(user_id, {"role": request.role})

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="change_role",
            resource_type="user",
            resource_id=user_id,
            details={"email": user.get("email"), "new_role": request.role}
        )

    return {
        "success": success,
        "message": f"用戶角色已更新為 {request.role}"
    }


@router.put("/users/{user_id}/quota")
async def update_user_quota(
    user_id: str,
    request: UpdateUserQuotaRequest,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """調整用戶配額（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    current_quota = user.get("quota", {})

    if request.tier:
        # 使用預設等級配額
        try:
            tier_enum = QuotaTier(request.tier)
            tier_quota = QUOTA_TIERS[tier_enum]
            new_quota = {
                "tier": request.tier,
                "max_transcriptions": tier_quota["max_transcriptions"],
                "max_duration_minutes": tier_quota["max_duration_minutes"],
                "max_concurrent_tasks": tier_quota["max_concurrent_tasks"],
                "features": tier_quota["features"]
            }
        except (ValueError, KeyError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"無效的配額等級: {request.tier}"
            )
    elif request.custom:
        # 自訂配額（合併現有配額）
        new_quota = {**current_quota, **request.custom}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供 tier 或 custom 配額設定"
        )

    success = await user_repo.update_quota(user_id, new_quota)

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="update_quota",
            resource_type="user",
            resource_id=user_id,
            details={"email": user.get("email"), "new_quota": new_quota}
        )

    return {
        "success": success,
        "quota": new_quota,
        "message": "配額已更新"
    }


@router.post("/users/{user_id}/reset-quota")
async def reset_user_monthly_quota(
    user_id: str,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """重置用戶月配額使用量（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 重置使用量
    usage = user.get("usage", {})
    usage["transcriptions"] = 0
    usage["duration_minutes"] = 0
    usage["last_reset"] = get_utc_timestamp()

    success = await user_repo.update(user_id, {"usage": usage})

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="reset_quota",
            resource_type="user",
            resource_id=user_id,
            details={"email": user.get("email")}
        )

    return {
        "success": success,
        "message": "月配額使用量已重置"
    }


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    request: ResetPasswordRequest,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """重設用戶密碼（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    # 驗證密碼長度
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密碼長度至少需要 8 個字元"
        )

    # 加密新密碼
    hashed_password = hash_password(request.new_password)

    # 更新密碼
    success = await user_repo.update(user_id, {"password_hash": hashed_password})

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="reset_password",
            resource_type="user",
            resource_id=user_id,
            details={"email": user.get("email")}
        )

    return {
        "success": success,
        "message": "密碼已重設"
    }


# ========== 任務管理 API ==========

@router.get("/tasks")
async def list_all_tasks(
    search: Optional[str] = Query(None, description="搜尋檔名或 task_id"),
    user_email: Optional[str] = Query(None, description="篩選用戶 email"),
    user_id: Optional[str] = Query(None, description="篩選用戶 ID"),
    status: Optional[str] = Query(None, description="篩選狀態"),
    date_from: Optional[str] = Query(None, description="開始日期 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="結束日期 (YYYY-MM-DD)"),
    sort_by: str = Query("timestamps.created_at", description="排序欄位"),
    sort_order: int = Query(-1, description="排序方向"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取全域任務列表（管理員）"""
    task_repo = TaskRepository(db)

    # 建立篩選條件
    filters = {"deleted": {"$ne": True}}

    if search:
        filters["$or"] = [
            {"_id": {"$regex": search, "$options": "i"}},
            {"file.filename": {"$regex": search, "$options": "i"}},
            {"filename": {"$regex": search, "$options": "i"}}
        ]

    if user_email:
        # 先查詢用戶 ID
        user_repo = UserRepository(db)
        user = await user_repo.get_by_email(user_email)
        if user:
            uid = str(user["_id"])
            filters["$or"] = [
                {"user.user_id": uid},
                {"user_id": uid}
            ]
        else:
            # 沒找到用戶，返回空結果
            return {"tasks": [], "total": 0, "skip": skip, "limit": limit}

    if user_id:
        filters["$or"] = [
            {"user.user_id": user_id},
            {"user_id": user_id}
        ]

    if status:
        if status == "active":
            filters["status"] = {"$in": ["pending", "processing"]}
        else:
            filters["status"] = status

    if date_from:
        filters["timestamps.created_at"] = {"$gte": f"{date_from} 00:00:00"}

    if date_to:
        if "timestamps.created_at" in filters:
            filters["timestamps.created_at"]["$lte"] = f"{date_to} 23:59:59"
        else:
            filters["timestamps.created_at"] = {"$lte": f"{date_to} 23:59:59"}

    # 查詢任務
    sort = [(sort_by, sort_order)]
    cursor = task_repo.collection.find(filters).skip(skip).limit(limit).sort(sort)
    tasks = await cursor.to_list(length=limit)
    total = await task_repo.collection.count_documents(filters)

    # 處理任務資料
    result = []
    for task in tasks:
        # 取得用戶資訊
        task_user_id = task.get("user", {}).get("user_id") or task.get("user_id")
        task_user_email = task.get("user", {}).get("user_email") or task.get("user_email")

        result.append({
            "task_id": task.get("_id") or task.get("task_id"),
            "user_id": task_user_id,
            "user_email": task_user_email,
            "filename": task.get("file", {}).get("filename") or task.get("filename"),
            "file_size_mb": task.get("file", {}).get("size_mb") or task.get("file_size_mb"),
            "status": task.get("status"),
            "progress": task.get("progress"),
            "progress_percentage": task.get("progress_percentage"),
            "audio_duration_seconds": task.get("stats", {}).get("audio_duration_seconds") or task.get("audio_duration"),
            "duration_seconds": task.get("stats", {}).get("duration_seconds"),
            "created_at": task.get("timestamps", {}).get("created_at") or task.get("created_at"),
            "completed_at": task.get("timestamps", {}).get("completed_at") or task.get("completed_at"),
            "config": task.get("config", {})
        })

    return {
        "tasks": result,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/tasks/{task_id}")
async def get_task_detail(
    task_id: str,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取任務詳情（管理員）"""
    task_repo = TaskRepository(db)

    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在"
        )

    # 取得用戶資訊
    task_user_id = task.get("user", {}).get("user_id") or task.get("user_id")
    task_user_email = task.get("user", {}).get("user_email") or task.get("user_email")

    return {
        "task_id": task.get("_id") or task.get("task_id"),
        "user": {
            "user_id": task_user_id,
            "user_email": task_user_email
        },
        "file": {
            "filename": task.get("file", {}).get("filename") or task.get("filename"),
            "size_mb": task.get("file", {}).get("size_mb") or task.get("file_size_mb")
        },
        "config": task.get("config", {}),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "progress_percentage": task.get("progress_percentage"),
        "result": {
            "audio_file": task.get("result", {}).get("audio_file") or task.get("audio_file"),
            "transcription_file": task.get("result", {}).get("transcription_file") or task.get("transcription_file"),
            "text_length": task.get("result", {}).get("text_length") or task.get("text_length")
        },
        "stats": task.get("stats", {}),
        "models": task.get("models", {}),
        "tags": task.get("tags", []),
        "custom_name": task.get("custom_name"),
        "timestamps": {
            "created_at": task.get("timestamps", {}).get("created_at") or task.get("created_at"),
            "updated_at": task.get("timestamps", {}).get("updated_at") or task.get("updated_at"),
            "started_at": task.get("timestamps", {}).get("started_at") or task.get("started_at"),
            "completed_at": task.get("timestamps", {}).get("completed_at") or task.get("completed_at")
        },
        "error_message": task.get("error_message")
    }


@router.post("/tasks/{task_id}/cancel")
async def admin_cancel_task(
    task_id: str,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """強制取消任務（管理員）"""
    task_repo = TaskRepository(db)

    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在"
        )

    current_status = task.get("status")
    if current_status not in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無法取消狀態為 '{current_status}' 的任務"
        )

    # 更新任務狀態
    now = get_utc_timestamp()
    success = await task_repo.update(task_id, {
        "status": "cancelled",
        "timestamps.completed_at": now,
        "error_message": f"由管理員 {admin['email']} 強制取消"
    })

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="cancel_task",
            resource_type="task",
            resource_id=task_id,
            details={"previous_status": current_status}
        )

    return {
        "success": success,
        "message": "任務已取消"
    }


@router.delete("/tasks/{task_id}")
async def admin_delete_task(
    task_id: str,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """強制刪除任務（管理員）"""
    task_repo = TaskRepository(db)

    task = await task_repo.get_by_id(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在"
        )

    current_status = task.get("status")
    if current_status in ["pending", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無法刪除進行中的任務，請先取消"
        )

    # 軟刪除任務
    now = get_utc_timestamp()
    success = await task_repo.collection.update_one(
        {"_id": task_id},
        {"$set": {"deleted": True, "deleted_at": now}}
    )

    if success.modified_count > 0:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="delete_task",
            resource_type="task",
            resource_id=task_id,
            details={"status": current_status}
        )

    return {
        "success": success.modified_count > 0,
        "message": "任務已刪除"
    }


@router.post("/tasks/batch/delete")
async def admin_batch_delete_tasks(
    request: BatchDeleteTasksRequest,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """批次刪除任務（管理員）"""
    task_repo = TaskRepository(db)

    # 只刪除非進行中的任務
    now = get_utc_timestamp()
    result = await task_repo.collection.update_many(
        {
            "_id": {"$in": request.task_ids},
            "status": {"$nin": ["pending", "processing"]},
            "deleted": {"$ne": True}
        },
        {"$set": {"deleted": True, "deleted_at": now}}
    )

    deleted_count = result.modified_count

    if deleted_count > 0:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="batch_delete_tasks",
            resource_type="task",
            resource_id=None,
            details={"task_ids": request.task_ids, "deleted_count": deleted_count}
        )

    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"已刪除 {deleted_count} 個任務"
    }


# ========== 統計 API ==========

@router.get("/statistics")
async def get_admin_statistics(
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取後台統計資料"""
    try:
        # 1. 總體統計
        total_tasks = await db.tasks.count_documents({})
        completed_tasks = await db.tasks.count_documents({"status": "completed"})
        processing_tasks = await db.tasks.count_documents({"status": "processing"})
        failed_tasks = await db.tasks.count_documents({"status": "failed"})

        # 2. Token 使用統計
        # 2.1 標點符號 Token 統計（從 tasks.stats.token_usage）
        punctuation_token_pipeline = [
            {
                "$match": {
                    "stats.token_usage.total": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$stats.token_usage.total"},
                    "total_prompt_tokens": {"$sum": "$stats.token_usage.prompt"},
                    "total_completion_tokens": {"$sum": "$stats.token_usage.completion"},
                    "tasks_with_tokens": {"$sum": 1}
                }
            }
        ]
        punct_token_cursor = db.tasks.aggregate(punctuation_token_pipeline)
        punct_token_list = await punct_token_cursor.to_list(length=1)
        punct_token_stats = punct_token_list[0] if punct_token_list else {
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "tasks_with_tokens": 0
        }

        # 2.2 AI 總結 Token 統計（從 summaries.metadata.token_usage）
        summary_token_pipeline = [
            {
                "$match": {
                    "metadata.token_usage.total": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$metadata.token_usage.total"},
                    "total_prompt_tokens": {"$sum": "$metadata.token_usage.prompt"},
                    "total_completion_tokens": {"$sum": "$metadata.token_usage.completion"},
                    "summaries_with_tokens": {"$sum": 1}
                }
            }
        ]
        summary_token_cursor = db.summaries.aggregate(summary_token_pipeline)
        summary_token_list = await summary_token_cursor.to_list(length=1)
        summary_token_stats = summary_token_list[0] if summary_token_list else {
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "summaries_with_tokens": 0
        }

        # 2.3 合併總計
        combined_total_tokens = punct_token_stats.get("total_tokens", 0) + summary_token_stats.get("total_tokens", 0)
        combined_prompt_tokens = punct_token_stats.get("total_prompt_tokens", 0) + summary_token_stats.get("total_prompt_tokens", 0)
        combined_completion_tokens = punct_token_stats.get("total_completion_tokens", 0) + summary_token_stats.get("total_completion_tokens", 0)

        # 3. 模型使用統計
        # 3.1 標點符號模型統計
        punctuation_model_pipeline = [
            {"$match": {"models.punctuation": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$models.punctuation", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        punct_model_cursor = db.tasks.aggregate(punctuation_model_pipeline)
        punct_model_stats = await punct_model_cursor.to_list(length=None)

        # 3.2 轉錄模型統計
        transcription_model_pipeline = [
            {"$match": {"models.transcription": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$models.transcription", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        trans_model_cursor = db.tasks.aggregate(transcription_model_pipeline)
        trans_model_stats = await trans_model_cursor.to_list(length=None)

        # 3.3 說話者辨識模型統計
        diarization_model_pipeline = [
            {"$match": {"models.diarization": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$models.diarization", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        diar_model_cursor = db.tasks.aggregate(diarization_model_pipeline)
        diar_model_stats = await diar_model_cursor.to_list(length=None)

        # 3.4 AI 總結模型統計（從 summaries.metadata.model）
        summary_model_pipeline = [
            {"$match": {"metadata.model": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$metadata.model", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        summary_model_cursor = db.summaries.aggregate(summary_model_pipeline)
        summary_model_stats = await summary_model_cursor.to_list(length=None)

        # 4. 每日統計（最近 30 天）
        # 計算 30 天前的 UTC Unix timestamp（從當天 00:00:00 UTC+8 開始）
        thirty_days_ago_dt = datetime.now(TZ_UTC8).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
        thirty_days_ago_timestamp = int(thirty_days_ago_dt.timestamp())

        # 4.1 每日任務統計（含標點符號 token）
        # timestamps.created_at 是 Unix timestamp（秒），需要轉換為日期
        daily_tasks_pipeline = [
            {"$match": {"timestamps.created_at": {"$gte": thirty_days_ago_timestamp}}},
            {
                "$group": {
                    # 將 Unix timestamp 轉換為日期字串（UTC+8 時區）
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": {"$toDate": {"$multiply": ["$timestamps.created_at", 1000]}},
                            "timezone": "+08:00"
                        }
                    },
                    "tasks_count": {"$sum": 1},
                    "punctuation_tokens": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        daily_tasks_cursor = db.tasks.aggregate(daily_tasks_pipeline)
        daily_tasks_stats = await daily_tasks_cursor.to_list(length=None)

        # 4.2 每日 AI 總結統計
        # summaries.created_at 也是 Unix timestamp（秒）
        daily_summaries_pipeline = [
            {"$match": {"created_at": {"$gte": thirty_days_ago_timestamp}}},
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": {"$toDate": {"$multiply": ["$created_at", 1000]}},
                            "timezone": "+08:00"
                        }
                    },
                    "summaries_count": {"$sum": 1},
                    "summary_tokens": {"$sum": {"$ifNull": ["$metadata.token_usage.total", 0]}}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        daily_summaries_cursor = db.summaries.aggregate(daily_summaries_pipeline)
        daily_summaries_stats = await daily_summaries_cursor.to_list(length=None)

        # 4.3 合併每日統計
        daily_summaries_map = {stat["_id"]: stat for stat in daily_summaries_stats}
        daily_stats = []
        for task_stat in daily_tasks_stats:
            date = task_stat["_id"]
            summary_stat = daily_summaries_map.get(date, {})
            daily_stats.append({
                "date": date,
                "tasks_count": task_stat["tasks_count"],
                "summaries_count": summary_stat.get("summaries_count", 0),
                "punctuation_tokens": task_stat["punctuation_tokens"],
                "summary_tokens": summary_stat.get("summary_tokens", 0),
                "total_tokens": task_stat["punctuation_tokens"] + summary_stat.get("summary_tokens", 0)
            })

        # 5. 使用者統計
        # 5.1 任務統計（含標點符號 token）
        user_tasks_pipeline = [
            {
                "$group": {
                    "_id": "$user.user_id",
                    "tasks_count": {"$sum": 1},
                    "punctuation_tokens": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}}
                }
            },
            {"$sort": {"tasks_count": -1}},
            {"$limit": 20}  # 取多一點，後面合併後再取 top 10
        ]
        user_tasks_cursor = db.tasks.aggregate(user_tasks_pipeline)
        user_tasks_stats = await user_tasks_cursor.to_list(length=None)

        # 5.2 獲取這些用戶的 summary token 使用量
        # 先建立 task_id -> user_id 的映射
        user_summary_pipeline = [
            {
                "$lookup": {
                    "from": "tasks",
                    "localField": "_id",
                    "foreignField": "_id",
                    "as": "task_info"
                }
            },
            {"$unwind": {"path": "$task_info", "preserveNullAndEmptyArrays": True}},
            {
                "$group": {
                    "_id": "$task_info.user.user_id",
                    "summaries_count": {"$sum": 1},
                    "summary_tokens": {"$sum": {"$ifNull": ["$metadata.token_usage.total", 0]}}
                }
            }
        ]
        user_summary_cursor = db.summaries.aggregate(user_summary_pipeline)
        user_summary_stats = await user_summary_cursor.to_list(length=None)

        # 5.3 合併用戶統計
        user_summary_map = {stat["_id"]: stat for stat in user_summary_stats}
        top_users = []
        for user_stat in user_tasks_stats:
            user_id = user_stat["_id"]
            summary_stat = user_summary_map.get(user_id, {})
            punctuation_tokens = user_stat["punctuation_tokens"]
            summary_tokens = summary_stat.get("summary_tokens", 0)
            top_users.append({
                "user_id": user_id,
                "tasks_count": user_stat["tasks_count"],
                "summaries_count": summary_stat.get("summaries_count", 0),
                "punctuation_tokens": punctuation_tokens,
                "summary_tokens": summary_tokens,
                "total_tokens": punctuation_tokens + summary_tokens
            })

        # 按總 token 排序，取 top 10
        top_users.sort(key=lambda x: x["total_tokens"], reverse=True)
        top_users = top_users[:10]

        # 6. 平均處理時間
        avg_duration_pipeline = [
            {
                "$match": {
                    "status": "completed",
                    "stats.duration_seconds": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "avg_duration": {"$avg": "$stats.duration_seconds"},
                    "min_duration": {"$min": "$stats.duration_seconds"},
                    "max_duration": {"$max": "$stats.duration_seconds"}
                }
            }
        ]
        duration_stats_cursor = db.tasks.aggregate(avg_duration_pipeline)
        duration_stats_list = await duration_stats_cursor.to_list(length=1)
        duration_stats = duration_stats_list[0] if duration_stats_list else {
            "avg_duration": 0,
            "min_duration": 0,
            "max_duration": 0
        }

        # 7. 標點符號服務使用統計
        punct_pipeline = [
            {"$group": {"_id": "$config.punct_provider", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        punct_stats_cursor = db.tasks.aggregate(punct_pipeline)
        punct_stats = await punct_stats_cursor.to_list(length=None)

        # 8. 用戶統計
        total_users = await db.users.count_documents({})
        active_users = await db.users.count_documents({"is_active": True})

        return {
            "overview": {
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "processing_tasks": processing_tasks,
                "failed_tasks": failed_tasks,
                "success_rate": round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0,
                "total_users": total_users,
                "active_users": active_users
            },
            "token_usage": {
                # 總計
                "total_tokens": combined_total_tokens,
                "prompt_tokens": combined_prompt_tokens,
                "completion_tokens": combined_completion_tokens,
                # 標點符號（Punctuation）
                "punctuation": {
                    "total_tokens": punct_token_stats.get("total_tokens", 0),
                    "prompt_tokens": punct_token_stats.get("total_prompt_tokens", 0),
                    "completion_tokens": punct_token_stats.get("total_completion_tokens", 0),
                    "tasks_count": punct_token_stats.get("tasks_with_tokens", 0),
                    "avg_tokens_per_task": round(punct_token_stats.get("total_tokens", 0) / punct_token_stats.get("tasks_with_tokens", 1), 2) if punct_token_stats.get("tasks_with_tokens", 0) > 0 else 0
                },
                # AI 總結（Summary）
                "summary": {
                    "total_tokens": summary_token_stats.get("total_tokens", 0),
                    "prompt_tokens": summary_token_stats.get("total_prompt_tokens", 0),
                    "completion_tokens": summary_token_stats.get("total_completion_tokens", 0),
                    "summaries_count": summary_token_stats.get("summaries_with_tokens", 0),
                    "avg_tokens_per_summary": round(summary_token_stats.get("total_tokens", 0) / summary_token_stats.get("summaries_with_tokens", 1), 2) if summary_token_stats.get("summaries_with_tokens", 0) > 0 else 0
                }
            },
            "model_usage": {
                "punctuation": [{"model": stat["_id"] or "未知", "count": stat["count"]} for stat in punct_model_stats],
                "transcription": [{"model": stat["_id"] or "未知", "count": stat["count"]} for stat in trans_model_stats],
                "diarization": [{"model": stat["_id"] or "未知", "count": stat["count"]} for stat in diar_model_stats],
                "summary": [{"model": stat["_id"] or "未知", "count": stat["count"]} for stat in summary_model_stats]
            },
            "daily_stats": daily_stats,
            "top_users": top_users,
            "performance": {
                "avg_duration_seconds": round(duration_stats.get("avg_duration", 0), 2),
                "min_duration_seconds": round(duration_stats.get("min_duration", 0), 2),
                "max_duration_seconds": round(duration_stats.get("max_duration", 0), 2)
            },
            "punct_provider_usage": [{"provider": stat["_id"] or "none", "count": stat["count"]} for stat in punct_stats]
        }

    except Exception as e:
        print(f"❌ 獲取統計資料失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取統計資料失敗：{str(e)}"
        )


# ========== 審計日誌 API ==========

@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    log_type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取操作記錄"""
    audit_log_repo = AuditLogRepository(db)

    if user_id:
        logs = await audit_log_repo.get_by_user(user_id, limit=limit, skip=skip, log_type=log_type)
    else:
        logs = await audit_log_repo.get_recent(limit=limit, skip=skip, log_type=log_type)

    # 轉換 ObjectId 為字串
    for log in logs:
        if "_id" in log:
            log["_id"] = str(log["_id"])

    return {
        "logs": logs,
        "total": len(logs),
        "limit": limit,
        "skip": skip
    }


@router.get("/audit-logs/failed")
async def get_failed_audit_logs(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(100, ge=1, le=500),
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取失敗的操作記錄"""
    audit_log_repo = AuditLogRepository(db)
    logs = await audit_log_repo.get_failed_operations(days=days, limit=limit)

    return {
        "failed_logs": logs,
        "total": len(logs),
        "days": days
    }


@router.get("/audit-logs/statistics")
async def get_audit_statistics(
    days: int = Query(30, ge=1, le=365),
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取操作記錄統計"""
    audit_log_repo = AuditLogRepository(db)
    stats = await audit_log_repo.get_statistics(days=days)

    return {
        "statistics": stats,
        "days": days
    }


@router.get("/audit-logs/resource/{resource_id}")
async def get_resource_audit_logs(
    resource_id: str,
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取特定資源的操作記錄"""
    audit_log_repo = AuditLogRepository(db)
    logs = await audit_log_repo.get_by_resource(resource_id, limit=limit)

    return {
        "resource_id": resource_id,
        "logs": logs,
        "total": len(logs)
    }
