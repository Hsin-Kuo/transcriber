"""
管理後台 API - 用戶管理、任務管理、統計、審計日誌
"""
from typing import Optional, List
from datetime import timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from ..auth.dependencies import get_current_admin, get_database
from ..auth.password import hash_password
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.audit_log_repo import AuditLogRepository
from ..database.repositories.summary_log_repo import SummaryLogRepository
from ..models.quota import QuotaTier, QUOTA_TIERS
from ..utils.time_utils import get_utc_timestamp
from ..utils.audit_logger import log_admin_action
from ..utils.email_service import get_email_service
from ..utils.sentry_helpers import create_background_task
from ..utils.logger import get_logger
from ..services.admin_analytics import build_admin_analytics


def _notify_user_async(to_email: str, action_label: str, admin_email: str, details_lines: list) -> None:
    """非阻擋寄送 admin 操作通知信。失敗只記 log 不影響 endpoint latency。"""
    if not to_email:
        return

    async def _send():
        try:
            await get_email_service().send_admin_action_notification(
                to_email=to_email,
                action_label=action_label,
                admin_email=admin_email,
                details_lines=details_lines,
            )
        except Exception as e:
            logger.warning("admin.notification_email.failed", error=str(e))

    create_background_task(_send(), name=f"admin_notify:{action_label[:20]}")

logger = get_logger(__name__)

# 單次調整額外額度的上限（避免 admin 手滑）
MAX_EXTRA_QUOTA_DELTA_DURATION = 10000  # 分鐘
MAX_EXTRA_QUOTA_DELTA_SUMMARIES = 1000  # 次

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


class AdjustExtraQuotaRequest(BaseModel):
    """調整用戶額外額度請求（補償或扣除）"""
    duration_minutes: float = 0  # 正數補償、負數扣除
    ai_summaries: int = 0
    reason: Optional[str] = None  # 操作原因（記錄於 audit log）


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
        active_task_count = await task_repo.count_active_by_user(user_id)

        result.append({
            "id": user_id,
            "email": user.get("email"),
            "role": user.get("role", "user"),
            "is_active": user.get("is_active", True),
            "email_verified": user.get("email_verified", False),
            "auth_providers": user.get("auth_providers", []),
            "has_password": user.get("password_hash") is not None,
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
            "filename": task.get("file", {}).get("filename"),
            "status": task.get("status"),
            "created_at": task.get("timestamps", {}).get("created_at")
        })

    return {
        "id": str(user["_id"]),
        "email": user.get("email"),
        "role": user.get("role", "user"),
        "is_active": user.get("is_active", True),
        "email_verified": user.get("email_verified", False),
        "auth_providers": user.get("auth_providers", []),
        "has_password": user.get("password_hash") is not None,
        "quota": user.get("quota", {}),
        "usage": user.get("usage", {}),
        "extra_quota": user.get("extra_quota", {}),
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
    body: UpdateUserStatusRequest,
    http_request: Request,
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

    if str(admin["_id"]) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能停用自己的帳號"
        )

    success = await user_repo.update(user_id, {"is_active": body.is_active})

    if success:
        action = "enable_user" if body.is_active else "disable_user"
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action=action,
            resource_type="user",
            resource_id=user_id,
            details={
                "email": user.get("email"),
                "before": {"is_active": user.get("is_active", True)},
                "after": {"is_active": body.is_active}
            },
            request=http_request,
        )

        # 帳號停用通知（啟用不擾，停用才寄）
        if not body.is_active:
            _notify_user_async(
                to_email=user.get("email"),
                action_label="帳號已被停用",
                admin_email=admin.get("email", "unknown"),
                details_lines=["停用後將無法登入及使用任何功能。"],
            )

    return {
        "success": success,
        "message": f"用戶已{'啟用' if body.is_active else '停用'}"
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    body: UpdateUserRoleRequest,
    http_request: Request,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """修改用戶角色（管理員）"""
    if body.role not in ["user", "admin"]:
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

    if str(admin["_id"]) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己的角色"
        )

    old_role = user.get("role", "user")
    success = await user_repo.update(user_id, {"role": body.role})

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="change_role",
            resource_type="user",
            resource_id=user_id,
            details={
                "email": user.get("email"),
                "before": {"role": old_role},
                "after": {"role": body.role}
            },
            request=http_request,
        )

        if old_role != body.role:
            _notify_user_async(
                to_email=user.get("email"),
                action_label=f"角色已變更：{old_role} → {body.role}",
                admin_email=admin.get("email", "unknown"),
                details_lines=[f"原本角色：{old_role}", f"新角色：{body.role}"],
            )

    return {
        "success": success,
        "message": f"用戶角色已更新為 {body.role}"
    }


@router.put("/users/{user_id}/quota")
async def update_user_quota(
    user_id: str,
    body: UpdateUserQuotaRequest,
    http_request: Request,
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

    if body.tier:
        try:
            tier_enum = QuotaTier(body.tier)
            tier_quota = QUOTA_TIERS[tier_enum]
            new_quota = {
                "tier": body.tier,
                "max_transcriptions": tier_quota["max_transcriptions"],
                "max_duration_minutes": tier_quota["max_duration_minutes"],
                "max_concurrent_tasks": tier_quota["max_concurrent_tasks"],
                "max_ai_summaries": tier_quota["max_ai_summaries"],
                "max_keep_audio": tier_quota["max_keep_audio"],
                "audio_retention_days": tier_quota["audio_retention_days"],
                "features": tier_quota["features"]
            }
        except (ValueError, KeyError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"無效的配額等級: {body.tier}"
            )
    elif body.custom:
        new_quota = {**current_quota, **body.custom}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供 tier 或 custom 配額設定"
        )

    old_tier = current_quota.get("tier")
    new_tier = new_quota.get("tier")
    success = await user_repo.update_quota(user_id, new_quota)

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="update_quota",
            resource_type="user",
            resource_id=user_id,
            details={
                "email": user.get("email"),
                "before": {
                    "tier": old_tier,
                    "max_duration_minutes": current_quota.get("max_duration_minutes")
                },
                "after": {
                    "tier": new_tier,
                    "max_duration_minutes": new_quota.get("max_duration_minutes")
                }
            },
            request=http_request,
        )

        # 只在 tier 改變（不論升降）時通知；單純調整 custom 數字不擾
        if old_tier and new_tier and old_tier != new_tier:
            _notify_user_async(
                to_email=user.get("email"),
                action_label=f"方案變更：{old_tier} → {new_tier}",
                admin_email=admin.get("email", "unknown"),
                details_lines=["新方案配額已即時生效。"],
            )

    return {
        "success": success,
        "quota": new_quota,
        "message": "配額已更新"
    }


@router.post("/users/{user_id}/reset-quota")
async def reset_user_monthly_quota(
    user_id: str,
    http_request: Request,
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

    old_usage = user.get("usage", {})
    old_transcriptions = old_usage.get("transcriptions", 0)
    old_duration = old_usage.get("duration_minutes", 0)

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
            details={
                "email": user.get("email"),
                "before": {
                    "transcriptions": old_transcriptions,
                    "duration_minutes": old_duration
                },
                "after": {
                    "transcriptions": 0,
                    "duration_minutes": 0
                }
            },
            request=http_request,
        )

        _notify_user_async(
            to_email=user.get("email"),
            action_label="月配額使用量已被重置",
            admin_email=admin.get("email", "unknown"),
            details_lines=[
                f"重置前：{old_transcriptions} 個任務、{old_duration} 分鐘",
                "重置後：0 / 0（本月起重新計算）",
            ],
        )

    return {
        "success": success,
        "message": "月配額使用量已重置"
    }


@router.post("/users/{user_id}/extra-quota")
async def adjust_user_extra_quota(
    user_id: str,
    body: AdjustExtraQuotaRequest,
    http_request: Request,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """調整用戶額外額度（補償或扣除，不影響每月配額）

    使用原子操作保證扣除時不會變負；單次調整有最大值限制避免誤操作。
    """
    if not body.duration_minutes and not body.ai_summaries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes 與 ai_summaries 不可同時為 0"
        )

    if abs(body.duration_minutes) > MAX_EXTRA_QUOTA_DELTA_DURATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"單次轉錄時長調整不可超過 {MAX_EXTRA_QUOTA_DELTA_DURATION} 分鐘"
        )
    if abs(body.ai_summaries) > MAX_EXTRA_QUOTA_DELTA_SUMMARIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"單次 AI 摘要調整不可超過 {MAX_EXTRA_QUOTA_DELTA_SUMMARIES} 次"
        )

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在"
        )

    updated_user = await user_repo.adjust_extra_quota_atomic(
        user_id,
        duration_minutes=body.duration_minutes,
        ai_summaries=body.ai_summaries
    )

    if updated_user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="扣除失敗：餘額不足，請重新整理頁面確認當前餘額"
        )

    new_extra = updated_user.get("extra_quota", {})
    new_duration = new_extra.get("duration_minutes", 0)
    new_summaries = new_extra.get("ai_summaries", 0)
    actual_before_duration = new_duration - body.duration_minutes
    actual_before_summaries = new_summaries - body.ai_summaries

    try:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="adjust_extra_quota",
            resource_type="user",
            resource_id=user_id,
            details={
                "email": user.get("email"),
                "delta": {
                    "duration_minutes": body.duration_minutes,
                    "ai_summaries": body.ai_summaries
                },
                "before": {
                    "duration_minutes": actual_before_duration,
                    "ai_summaries": actual_before_summaries
                },
                "after": {
                    "duration_minutes": new_duration,
                    "ai_summaries": new_summaries
                },
                "reason": body.reason
            },
            request=http_request,
        )
    except Exception as e:
        logger.error(
            "admin.quota_adjust.audit_log_failed",
            admin_id=str(admin.get("_id")),
            user_id=user_id,
            delta_duration=body.duration_minutes,
            delta_summaries=body.ai_summaries,
            reason=body.reason,
            error=str(e),
        )

    # 通知用戶（補償或扣除都通知，避免出現「我額度怎麼少了」的客訴）
    delta_lines = []
    if body.duration_minutes:
        sign = "+" if body.duration_minutes > 0 else ""
        delta_lines.append(f"轉錄時數：{sign}{body.duration_minutes} 分鐘（現有 {new_duration}）")
    if body.ai_summaries:
        sign = "+" if body.ai_summaries > 0 else ""
        delta_lines.append(f"AI 摘要次數：{sign}{body.ai_summaries} 次（現有 {new_summaries}）")
    if body.reason:
        delta_lines.append(f"原因：{body.reason}")

    _notify_user_async(
        to_email=user.get("email"),
        action_label="額外額度已被調整",
        admin_email=admin.get("email", "unknown"),
        details_lines=delta_lines,
    )

    return {
        "success": True,
        "extra_quota": {
            "duration_minutes": new_duration,
            "ai_summaries": new_summaries
        }
    }


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    body: ResetPasswordRequest,
    http_request: Request,
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

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密碼長度至少需要 8 個字元"
        )

    hashed_password = hash_password(body.new_password)
    success = await user_repo.update(user_id, {"password_hash": hashed_password})

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="reset_password",
            resource_type="user",
            resource_id=user_id,
            details={"email": user.get("email")},
            request=http_request,
        )

        # 密碼被 admin 重設一定要通知，使用者才能察覺異常
        _notify_user_async(
            to_email=user.get("email"),
            action_label="密碼已被重設",
            admin_email=admin.get("email", "unknown"),
            details_lines=[
                "請使用新密碼登入。",
                "若此操作非您預期（例如沒請 admin 協助），請立即聯繫並更改密碼。",
            ],
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
            filters.update(TaskRepository.owned_by(uid))
        else:
            # 沒找到用戶，返回空結果
            return {"tasks": [], "total": 0, "skip": skip, "limit": limit}

    if user_id:
        filters.update(TaskRepository.owned_by(user_id))

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
        task_user_id = task.get("user", {}).get("user_id")
        task_user_email = task.get("user", {}).get("user_email")

        result.append({
            "task_id": task.get("_id") or task.get("task_id"),
            "user_id": task_user_id,
            "user_email": task_user_email,
            "filename": task.get("file", {}).get("filename"),
            "file_size_mb": task.get("file", {}).get("size_mb"),
            "status": task.get("status"),
            "progress": task.get("progress"),
            "progress_percentage": task.get("progress_percentage"),
            "audio_duration_seconds": task.get("stats", {}).get("audio_duration_seconds"),
            "duration_seconds": task.get("stats", {}).get("duration_seconds"),
            "created_at": task.get("timestamps", {}).get("created_at"),
            "completed_at": task.get("timestamps", {}).get("completed_at"),
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
    task_user_id = task.get("user", {}).get("user_id")
    task_user_email = task.get("user", {}).get("user_email")

    # AI 摘要生成記錄（每次生成都 append，含時間與 token 消耗）
    summary_log_repo = SummaryLogRepository(db)
    summary_logs = await summary_log_repo.list_by_task(task_id)

    return {
        "task_id": task.get("_id") or task.get("task_id"),
        "user": {
            "user_id": task_user_id,
            "user_email": task_user_email
        },
        "file": {
            "filename": task.get("file", {}).get("filename"),
            "size_mb": task.get("file", {}).get("size_mb")
        },
        "config": task.get("config", {}),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "progress_percentage": task.get("progress_percentage"),
        "result": {
            "audio_file": task.get("result", {}).get("audio_file"),
            "transcription_file": task.get("result", {}).get("transcription_file"),
            "text_length": task.get("result", {}).get("text_length")
        },
        "stats": task.get("stats", {}),
        "models": task.get("models", {}),
        "tags": task.get("tags", []),
        "custom_name": task.get("custom_name"),
        "timestamps": {
            "created_at": task.get("timestamps", {}).get("created_at"),
            "updated_at": task.get("timestamps", {}).get("updated_at"),
            "started_at": task.get("timestamps", {}).get("started_at"),
            "completed_at": task.get("timestamps", {}).get("completed_at")
        },
        "error_message": task.get("error_message") or (task["error"].get("message") if isinstance(task.get("error"), dict) else task.get("error")),
        "summary_logs": summary_logs
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
    request: Request,
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """獲取後台統計資料"""
    try:
        # 記錄 audit log（查看後台統計）
        try:
            from ..utils.audit_logger import get_audit_logger
            await get_audit_logger().log_admin_operation(
                request=request,
                action="view_statistics",
                user_id=str(admin["_id"]),
                status_code=200,
                message="查看後台統計資料",
            )
        except Exception as e:
            logger.warning("audit_log.write_failed", error=str(e))

        return await build_admin_analytics(db).full_report()

    except Exception as e:
        logger.error("admin.statistics.failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取統計資料失敗：{str(e)}"
        )


# ========== 收入統計 API ==========

@router.get("/revenue")
async def get_revenue_stats(
    admin: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """營收 dashboard 數據"""
    return await build_admin_analytics(db).revenue()


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


@router.post("/cleanup/handoff-orphans")
async def cleanup_handoff_orphans(
    older_than_hours: int = Query(24, ge=1, le=720),
    admin: dict = Depends(get_current_admin),
):
    """掃 S3 handoff/ 找超過 N 小時的孤兒並刪除。

    正常情況下 Worker 完成任務後會立即刪除自己的 handoff；殘留代表 dispatch
    上傳後 Worker 沒處理（crash / cancel / Spot 中斷沒恢復等）。

    對應 CONTEXT.md「Handoff audio」。手動觸發，未自動排程——
    建議搭 crontab 每日跑一次。
    """
    from ..utils.storage.backend import is_aws
    from ..utils.storage.handoff import sweep_handoff_orphans

    if not is_aws():
        return {"deleted": 0, "message": "local 模式無 handoff/ 結構"}

    # 包 executor 避免 blocking event loop（S3 list/delete 是 sync）
    import asyncio
    loop = asyncio.get_event_loop()
    deleted = await loop.run_in_executor(
        None, sweep_handoff_orphans, older_than_hours,
    )
    return {
        "deleted": deleted,
        "older_than_hours": older_than_hours,
    }
