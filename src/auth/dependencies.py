"""認證中介層（依賴注入）"""
from fastapi import Depends, HTTPException, Request, status
from .cookies import ACCESS_COOKIE_NAME
from .jwt_handler import verify_token
from .rbac import Permission, resolve_admin_role, role_has
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..utils.logger import get_logger
from bson import ObjectId
from typing import Optional

log = get_logger(__name__)


def _user_dict_from_token_data(token_data) -> dict:
    return {
        "_id": ObjectId(token_data.user_id),
        "email": token_data.email,
        "role": token_data.role,
        "username": token_data.email.split("@")[0],  # 從 email 推導
        "is_active": True  # JWT 有效即表示活躍
    }


async def get_current_user(
    request: Request,
    db=Depends(get_database)
):
    """驗證 Access Token 並返回當前用戶

    Access token 走 httpOnly cookie（不再接受 Authorization header——
    硬切換，比照 refresh_token 遷移的既有先例）。

    Args:
        request: FastAPI Request，用來讀 cookie
        db: 資料庫實例

    Returns:
        用戶資料

    Raises:
        HTTPException: 缺少/無效/過期的 Token
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 access token cookie",
        )

    token_data = verify_token(token, "access")
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效或過期的 Token",
        )

    # 效能優化：信任 JWT token，不每次都查 DB
    # JWT 本身已經過驗證且有過期時間，足以確保安全性
    # 只在關鍵操作（登入、修改資料）時才查 DB 確認用戶狀態
    # 這樣可以避免每次輪詢都查詢資料庫
    return _user_dict_from_token_data(token_data)


async def get_current_user_sse(
    request: Request,
    db=Depends(get_database)
):
    """驗證 Access Token（用於 SSE）

    改讀 httpOnly cookie——EventSource 對同源請求會自動帶 cookie，不再
    需要把 token 塞進 URL query string（原本這麼做是因為 EventSource
    不支援自訂 header，改用 cookie 後這個曝露面直接關掉）。

    Args:
        request: FastAPI Request，用來讀 cookie
        db: 資料庫實例

    Returns:
        用戶資料

    Raises:
        HTTPException: 缺少/無效/過期的 Token
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 access token cookie",
        )

    token_data = verify_token(token, "access")
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效或過期的 Token"
        )

    return _user_dict_from_token_data(token_data)


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
):
    """驗證管理員權限

    Args:
        current_user: 當前用戶

    Returns:
        管理員用戶資料

    Raises:
        HTTPException: 沒有管理員權限
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
        )
    return current_user


def require_permission(perm: Permission):
    """細粒度權限檢查依賴工廠（RBAC P0-1 Phase 0）。

    疊在 get_current_admin（粗閘門 role=="admin"）之上，不取代它：先過粗閘門，
    再依 admin_role 檢查是否具備 perm。admin_role 從 DB 即時讀取（非 JWT claim），
    因此角色調整立即生效、可即時撤權；admin 流量極低，多一次 DB read 可接受。

    過渡相容：admin 尚未設定 admin_role 時暫視為 superadmin（全開），並記
    rbac.unmigrated_admin log 供追蹤。待所有 admin 完成 migrate（此 log 歸零）
    後，Phase 3 才把預設改為拒絕，關掉這個相容後門。

    用法：
        @router.delete("/tasks/{task_id}")
        async def delete_task(admin = Depends(require_permission(Permission.TASK_DELETE))):
            ...
    """
    async def _checker(
        current_user: dict = Depends(get_current_admin),
        db=Depends(get_database),
    ) -> dict:
        user = await UserRepository(db).get_by_id(str(current_user["_id"]))
        raw = (user or {}).get("admin_role")
        role = resolve_admin_role(raw)
        if role is None:
            log.warning(
                "rbac.invalid_role",
                user_id=str(current_user["_id"]),
                admin_role=str(raw),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="無效的管理員角色",
            )
        if raw is None:
            log.warning(
                "rbac.unmigrated_admin",
                user_id=str(current_user["_id"]),
                perm=perm.value,
            )
        if not role_has(role, perm):
            log.warning(
                "rbac.denied",
                user_id=str(current_user["_id"]),
                role=role.value,
                perm=perm.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"權限不足：需要 {perm.value}",
            )
        # 供 endpoint / 後續稽核取用當前 admin 的細分角色
        current_user["admin_role"] = role.value
        return current_user

    # 供測試/內省用：這個依賴要求的能力（讓 wiring 測試能斷言每支 endpoint 掛對權限）
    _checker._required_permission = perm
    return _checker


async def check_quota(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """檢查用戶配額（基本檢查，具體音訊時長檢查在轉錄端點）

    Args:
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        用戶資料（包含 db 實例）
    """
    from .quota import QuotaManager
    from ..database.repositories.task_repo import TaskRepository

    # 檢查並發任務數
    task_repo = TaskRepository(db)
    active_tasks = await task_repo.find_active_by_user(str(current_user["_id"]))
    await QuotaManager.check_concurrent_tasks(current_user, len(active_tasks))

    # 返回用戶資料（加上 db 實例供後續使用）
    current_user["_db"] = db
    return current_user
