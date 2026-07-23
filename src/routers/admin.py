"""
管理後台 API - 用戶管理、任務管理、統計、審計日誌
"""
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from ..auth.dependencies import get_current_admin, get_database, require_permission
from ..auth.rbac import AdminRole, Permission, permissions_for, resolve_admin_role
from ..services.admin_role_service import (
    validate_admin_role_assignment,
    validate_role_demotion,
    normalize_promotion_admin_role,
)
from ..auth.password import hash_password
from ..database.repositories.user_repo import UserRepository
from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.audit_log_repo import AuditLogRepository
from ..database.repositories.summary_log_repo import SummaryLogRepository
from ..database.repositories.presence_repo import PresenceRepository, PRESENCE_TTL_SECONDS
from ..database.repositories.presence_rollup_repo import PresenceRollupRepository
from ..database.repositories.daily_active_repo import DailyActiveRepository
from ..models.quota import QuotaTier, QUOTA_TIERS
from ..utils.time_utils import get_utc_timestamp
from ..utils.audit_logger import log_admin_action
from ..utils.email_service import get_email_service
from ..utils.sentry_helpers import create_background_task
from ..utils.logger import get_logger
from ..utils.api_errors import api_error
from ..utils.user_display import user_email_or_label
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
    admin_role: Optional[str] = None  # 升級為 admin 時要套用的細分角色；不給預設 read_only


class UpdateAdminRoleRequest(BaseModel):
    """指派後台細分角色請求（RBAC）"""
    admin_role: str  # superadmin / billing / support / read_only


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


# ========== 當前管理員 ==========

@router.get("/me/permissions")
async def get_my_permissions(
    admin: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """回傳當前管理員的角色與能力清單，供前端據以隱藏無權操作的 UI。

    這是「渲染輔助」，非授權來源——真正的閘門是各 endpoint 的 require_permission。
    未 migrate（無 admin_role）的 admin 依 Phase 0 相容政策回 superadmin。
    """
    user = await UserRepository(db).get_by_id(str(admin["_id"]))
    role = resolve_admin_role((user or {}).get("admin_role"))
    if role is None:
        raise api_error("ADMIN_INVALID_ROLE", "Invalid admin role",
                        status.HTTP_403_FORBIDDEN)
    return {
        "role": role.value,
        "permissions": sorted(p.value for p in permissions_for(role)),
    }


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
    admin: dict = Depends(require_permission(Permission.USER_READ)),
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
            "display_name": user_email_or_label(
                user.get("email"), user_id, deleted=bool(user.get("deleted_at"))),
            "is_deleted": bool(user.get("deleted_at")),
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
    admin: dict = Depends(require_permission(Permission.USER_READ)),
    db = Depends(get_database)
):
    """獲取用戶詳情（管理員）"""
    user_repo = UserRepository(db)
    task_repo = TaskRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

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
        "display_name": user_email_or_label(
            user.get("email"), str(user["_id"]), deleted=bool(user.get("deleted_at"))),
        "is_deleted": bool(user.get("deleted_at")),
        "role": user.get("role", "user"),
        "admin_role": user.get("admin_role"),
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
    admin: dict = Depends(require_permission(Permission.USER_MANAGE)),
    db = Depends(get_database)
):
    """停用/啟用用戶帳號（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

    if str(admin["_id"]) == user_id:
        raise api_error("ADMIN_CANNOT_DISABLE_SELF",
                        "You cannot disable your own account",
                        status.HTTP_400_BAD_REQUEST)

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
    admin: dict = Depends(require_permission(Permission.ADMIN_GRANT)),
    db = Depends(get_database)
):
    """修改用戶角色（管理員）"""
    if body.role not in ["user", "admin"]:
        raise api_error("ADMIN_INVALID_ROLE",
                        "Role must be 'user' or 'admin'",
                        status.HTTP_400_BAD_REQUEST)

    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

    if str(admin["_id"]) == user_id:
        raise api_error("ADMIN_CANNOT_CHANGE_OWN_ROLE",
                        "You cannot change your own role",
                        status.HTTP_400_BAD_REQUEST)

    old_role = user.get("role", "user")
    old_admin_role = user.get("admin_role")
    new_admin_role = None

    if body.role == "admin" and old_role != "admin":
        # 升級：套用細分角色（未指定 → read_only 最小權限），避免相容路徑把新 admin
        # 當成 superadmin。
        chosen = normalize_promotion_admin_role(body.admin_role)
        if isinstance(chosen, tuple):
            raise api_error(chosen[0], chosen[1], status.HTTP_400_BAD_REQUEST)
        new_admin_role = chosen
        await user_repo.update(user_id, {"role": "admin", "admin_role": chosen})
    elif body.role == "user" and old_role == "admin":
        # 降級：護欄——不能降掉最後一個 superadmin；並清掉 admin_role 殘值。
        superadmin_count = await user_repo.count(
            {"role": "admin", "admin_role": AdminRole.SUPERADMIN.value})
        err = validate_role_demotion(
            target_admin_role=old_admin_role, superadmin_count=superadmin_count)
        if err:
            raise api_error(err[0], err[1], status.HTTP_400_BAD_REQUEST)
        await user_repo.update(user_id, {"role": "user"})
        await user_repo.set_admin_role(user_id, None)
    else:
        # 同角色，維持原本 idempotent 行為
        await user_repo.update(user_id, {"role": body.role})

    success = True
    await log_admin_action(
        admin_id=str(admin["_id"]),
        action="change_role",
        resource_type="user",
        resource_id=user_id,
        details={
            "email": user.get("email"),
            "before": {"role": old_role, "admin_role": old_admin_role},
            "after": {"role": body.role, "admin_role": new_admin_role}
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


@router.put("/users/{user_id}/admin-role")
async def update_user_admin_role(
    user_id: str,
    body: UpdateAdminRoleRequest,
    http_request: Request,
    admin: dict = Depends(require_permission(Permission.ADMIN_GRANT)),
    db = Depends(get_database)
):
    """指派後台細分角色 admin_role（superadmin 專屬——ADMIN_GRANT 只有 superadmin 有）。

    護欄：白名單值、不能改自己、目標須已是 admin、不能移除最後一個 superadmin。
    這些判斷抽在 services/admin_role_service.py 純函式，這裡只負責查 DB + 轉錯誤。
    """
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

    superadmin_count = await user_repo.count(
        {"role": "admin", "admin_role": AdminRole.SUPERADMIN.value})
    err = validate_admin_role_assignment(
        is_self=(str(admin["_id"]) == user_id),
        target_role=user.get("role", "user"),
        new_admin_role=body.admin_role,
        target_admin_role=user.get("admin_role"),
        superadmin_count=superadmin_count,
    )
    if err:
        raise api_error(err[0], err[1], status.HTTP_400_BAD_REQUEST)

    old_admin_role = user.get("admin_role")
    success = await user_repo.set_admin_role(user_id, body.admin_role)

    if success:
        await log_admin_action(
            admin_id=str(admin["_id"]),
            action="change_admin_role",
            resource_type="user",
            resource_id=user_id,
            details={
                "email": user.get("email"),
                "before": {"admin_role": old_admin_role},
                "after": {"admin_role": body.admin_role}
            },
            request=http_request,
        )

    return {
        "success": success,
        "message": f"管理員角色已更新為 {body.admin_role}"
    }


@router.put("/users/{user_id}/quota")
async def update_user_quota(
    user_id: str,
    body: UpdateUserQuotaRequest,
    http_request: Request,
    admin: dict = Depends(require_permission(Permission.USER_QUOTA)),
    db = Depends(get_database)
):
    """調整用戶配額（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

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
            raise api_error("ADMIN_INVALID_QUOTA_TIER",
                            "Invalid quota tier: {tier}",
                            status.HTTP_400_BAD_REQUEST,
                            tier=body.tier)
    elif body.custom:
        new_quota = {**current_quota, **body.custom}
    else:
        raise api_error("ADMIN_QUOTA_INPUT_REQUIRED",
                        "Provide either a tier or custom quota settings",
                        status.HTTP_400_BAD_REQUEST)

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
    admin: dict = Depends(require_permission(Permission.USER_QUOTA)),
    db = Depends(get_database)
):
    """重置用戶月配額使用量（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

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
    admin: dict = Depends(require_permission(Permission.USER_QUOTA)),
    db = Depends(get_database)
):
    """調整用戶額外額度（補償或扣除，不影響每月配額）

    使用原子操作保證扣除時不會變負；單次調整有最大值限制避免誤操作。
    """
    if not body.duration_minutes and not body.ai_summaries:
        raise api_error("ADMIN_EXTRA_QUOTA_DELTA_REQUIRED",
                        "duration_minutes and ai_summaries cannot both be 0",
                        status.HTTP_400_BAD_REQUEST)

    if abs(body.duration_minutes) > MAX_EXTRA_QUOTA_DELTA_DURATION:
        raise api_error("ADMIN_EXTRA_QUOTA_DURATION_TOO_LARGE",
                        "A single duration adjustment cannot exceed {max} minutes",
                        status.HTTP_400_BAD_REQUEST,
                        max=MAX_EXTRA_QUOTA_DELTA_DURATION)
    if abs(body.ai_summaries) > MAX_EXTRA_QUOTA_DELTA_SUMMARIES:
        raise api_error("ADMIN_EXTRA_QUOTA_SUMMARIES_TOO_LARGE",
                        "A single AI summary adjustment cannot exceed {max} times",
                        status.HTTP_400_BAD_REQUEST,
                        max=MAX_EXTRA_QUOTA_DELTA_SUMMARIES)

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

    updated_user = await user_repo.adjust_extra_quota_atomic(
        user_id,
        duration_minutes=body.duration_minutes,
        ai_summaries=body.ai_summaries
    )

    if updated_user is None:
        raise api_error("ADMIN_EXTRA_QUOTA_INSUFFICIENT_BALANCE",
                        "Deduction failed: insufficient balance, please refresh to confirm the current balance",
                        status.HTTP_409_CONFLICT)

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
    admin: dict = Depends(require_permission(Permission.USER_PASSWORD_RESET)),
    db = Depends(get_database)
):
    """重設用戶密碼（管理員）"""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_id(user_id)
    if not user:
        raise api_error("ADMIN_USER_NOT_FOUND", "User not found",
                        status.HTTP_404_NOT_FOUND)

    if len(body.new_password) < 8:
        raise api_error("ADMIN_PASSWORD_TOO_SHORT",
                        "Password must be at least 8 characters",
                        status.HTTP_400_BAD_REQUEST)

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
    admin: dict = Depends(require_permission(Permission.TASK_READ)),
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
        # 取得用戶資訊（去識別化任務 email 為 None → 顯示穩定假名）
        task_user_id = task.get("user", {}).get("user_id")
        task_user_email = user_email_or_label(
            task.get("user", {}).get("user_email"), task_user_id)

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
    admin: dict = Depends(require_permission(Permission.TASK_READ)),
    db = Depends(get_database)
):
    """獲取任務詳情（管理員）"""
    task_repo = TaskRepository(db)

    task = await task_repo.get_by_id(task_id)
    if not task:
        raise api_error("ADMIN_TASK_NOT_FOUND", "Task not found",
                        status.HTTP_404_NOT_FOUND)

    # 取得用戶資訊（去識別化任務 email 為 None → 顯示穩定假名）
    task_user_id = task.get("user", {}).get("user_id")
    task_user_email = user_email_or_label(
        task.get("user", {}).get("user_email"), task_user_id)

    # AI 摘要生成記錄（每次生成都 append，含時間與 token 消耗）
    summary_log_repo = SummaryLogRepository(db)
    summary_logs = await summary_log_repo.list_by_task(task_id)

    return {
        "task_id": task.get("_id") or task.get("task_id"),
        "task_type": task.get("task_type"),
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
    admin: dict = Depends(require_permission(Permission.TASK_MANAGE)),
    db = Depends(get_database)
):
    """強制取消任務（管理員）"""
    task_repo = TaskRepository(db)

    task = await task_repo.get_by_id(task_id)
    if not task:
        raise api_error("ADMIN_TASK_NOT_FOUND", "Task not found",
                        status.HTTP_404_NOT_FOUND)

    current_status = task.get("status")
    if current_status not in ["pending", "processing"]:
        raise api_error("ADMIN_TASK_NOT_CANCELLABLE",
                        "Cannot cancel a task in status '{status}'",
                        status.HTTP_400_BAD_REQUEST,
                        status=current_status)

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
    admin: dict = Depends(require_permission(Permission.TASK_DELETE)),
    db = Depends(get_database)
):
    """強制刪除任務（管理員）"""
    task_repo = TaskRepository(db)

    task = await task_repo.get_by_id(task_id)
    if not task:
        raise api_error("ADMIN_TASK_NOT_FOUND", "Task not found",
                        status.HTTP_404_NOT_FOUND)

    current_status = task.get("status")
    if current_status in ["pending", "processing"]:
        raise api_error("ADMIN_TASK_IN_PROGRESS_CANNOT_DELETE",
                        "Cannot delete an in-progress task, cancel it first",
                        status.HTTP_400_BAD_REQUEST)

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
    admin: dict = Depends(require_permission(Permission.TASK_DELETE)),
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
    admin: dict = Depends(require_permission(Permission.ANALYTICS_READ)),
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
        raise api_error(
            "ADMIN_STATISTICS_FAILED",
            "Failed to fetch statistics: {error}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=str(e),
        )


# ========== 線上人數 API ==========

@router.get("/stats/online")
async def get_online_users(
    window_seconds: int = Query(
        PRESENCE_TTL_SECONDS, ge=30, le=900,
        description="視為在線的閒置門檻（秒）；預設等於 presence TTL",
    ),
    admin: dict = Depends(require_permission(Permission.ANALYTICS_READ)),
    db=Depends(get_database),
):
    """當下線上（最近 window_seconds 內有活動）的已登入使用者數。

    供後台即時運營看板輪詢用；刻意不寫 audit log（會被高頻輪詢，寫了反而灌爆
    audit_logs）。資料來源為 user_presence collection（被動記錄 + TTL 自動清）。
    """
    count = await PresenceRepository(db).count_online(window_seconds=window_seconds)
    return {"online_users": count, "window_seconds": window_seconds}


@router.get("/stats/online/history")
async def get_online_history(
    days: int = Query(7, ge=1, le=90, description="往回涵蓋幾天"),
    admin: dict = Depends(require_permission(Permission.ANALYTICS_READ)),
    db=Depends(get_database),
):
    """線上人數歷史（每小時桶：峰值、平均、峰值發生時間）。

    供後台趨勢圖看「長期活躍巔峰」；資料來自 presence_rollup（背景每分鐘抽樣、
    每小時彙整）。回傳 buckets（時間正序）與 peak（區間內最高的那一桶）。
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    repo = PresenceRollupRepository(db)
    buckets = await repo.buckets_between(start, now)
    peak = await repo.peak_between(start, now)
    return {"days": days, "buckets": buckets, "peak": peak}


@router.get("/stats/dau")
async def get_dau(
    days: int = Query(30, ge=1, le=365, description="往回涵蓋幾天"),
    admin: dict = Depends(require_permission(Permission.ANALYTICS_READ)),
    db=Depends(get_database),
):
    """每日活躍使用者數（DAU）歷史 + 今日即時去重數。

    「活躍」= 當天有帶有效 token 發過請求的不重複使用者（被動記錄）。與線上人數
    （併發）是不同指標。history 來自 dau_daily（長期），today 即時查 daily_active。
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    repo = DailyActiveRepository(db)
    series = await repo.dau_between(start, now)
    today = await repo.count_active(now.strftime("%Y-%m-%d"))
    return {"days": days, "series": series, "today": today}


@router.get("/stats/online/users")
async def get_online_users_list(
    request: Request,
    window_seconds: int = Query(
        PRESENCE_TTL_SECONDS, ge=30, le=900,
        description="視為在線的閒置門檻（秒）",
    ),
    admin: dict = Depends(require_permission(Permission.PRESENCE_VIEW)),
    db=Depends(get_database),
):
    """當下在線的使用者名單（含身分）。

    比聚合人數敏感（逐一 PII），故：
    - 需 `PRESENCE_VIEW`（僅 support / superadmin；read_only 拿不到）。
    - **寫 audit_log**（誰在何時查了在線名單）——與只回數字、刻意不 audit 的
      `/stats/online` 不同。
    身分於讀取時 join users 解析（presence 本身不存 PII）。
    """
    presence = await PresenceRepository(db).list_online(window_seconds=window_seconds)
    now = datetime.now(timezone.utc)

    # 批次 join users 解析身分（一次 $in，不逐筆查）
    oids = []
    for p in presence:
        try:
            oids.append(ObjectId(p["user_id"]))
        except Exception:
            continue
    users = {}
    if oids:
        cursor = UserRepository(db).collection.find(
            {"_id": {"$in": oids}},
            {"email": 1, "username": 1, "role": 1, "admin_role": 1},
        )
        async for u in cursor:
            users[str(u["_id"])] = u

    items = []
    for p in presence:
        u = users.get(p["user_id"], {})
        ls = p["last_seen"]
        if ls.tzinfo is None:  # motor 讀回為 naive UTC
            ls = ls.replace(tzinfo=timezone.utc)
        items.append({
            "user_id": p["user_id"],
            "email": u.get("email"),
            "username": u.get("username"),
            "role": u.get("role"),
            "admin_role": u.get("admin_role"),
            "last_seen": ls.isoformat(),
            "idle_seconds": int((now - ls).total_seconds()),
        })

    await log_admin_action(
        admin_id=str(admin["_id"]),
        action="view_online_users",
        resource_type="presence",
        details={"count": len(items), "window_seconds": window_seconds},
        request=request,
    )
    return {"window_seconds": window_seconds, "online_users": len(items), "users": items}


# ========== 收入統計 API ==========

@router.get("/revenue")
async def get_revenue_stats(
    admin: dict = Depends(require_permission(Permission.BILLING_READ)),
    db=Depends(get_database),
):
    """營收 dashboard 數據"""
    return await build_admin_analytics(db).revenue()


# ========== AI 成本統計 API ==========

@router.get("/cost")
async def get_ai_cost_stats(
    request: Request,
    months: int = Query(6, ge=1, le=24, description="往回涵蓋幾個日曆月（含當月）"),
    admin: dict = Depends(require_permission(Permission.ANALYTICS_READ)),
    db = Depends(get_database),
):
    """AI 成本 dashboard：逐月 × 功能（標點/摘要）× 模型的 token → USD 試算。"""
    try:
        try:
            from ..utils.audit_logger import get_audit_logger
            await get_audit_logger().log_admin_operation(
                request=request,
                action="view_ai_cost",
                user_id=str(admin["_id"]),
                status_code=200,
                message=f"查看 AI 成本統計（近 {months} 月）",
            )
        except Exception as e:
            logger.warning("audit_log.write_failed", error=str(e))

        return await build_admin_analytics(db).monthly_cost(months=months)

    except Exception as e:
        logger.error("admin.cost.failed", error=str(e))
        raise api_error(
            "ADMIN_COST_FAILED",
            "Failed to fetch AI cost stats: {error}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=str(e),
        )


# ========== 審計日誌 API ==========

@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
    log_type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    admin: dict = Depends(require_permission(Permission.AUDIT_READ)),
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
    admin: dict = Depends(require_permission(Permission.AUDIT_READ)),
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
    admin: dict = Depends(require_permission(Permission.AUDIT_READ)),
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
    admin: dict = Depends(require_permission(Permission.AUDIT_READ)),
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
    admin: dict = Depends(require_permission(Permission.OPS)),
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
