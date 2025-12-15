"""認證中介層（依賴注入）"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .jwt_handler import verify_token
from ..database.mongodb import get_database
from bson import ObjectId

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_database)
):
    """驗證 Access Token 並返回當前用戶

    Args:
        credentials: HTTP Bearer 憑證
        db: 資料庫實例

    Returns:
        用戶資料

    Raises:
        HTTPException: Token 無效或用戶不存在
    """
    token = credentials.credentials
    token_data = verify_token(token, "access")

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效或過期的 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 從資料庫查詢用戶（確保用戶未被刪除/停用）
    try:
        user = await db.users.find_one({
            "_id": ObjectId(token_data.user_id),
            "is_active": True
        })
    except:
        user = None

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用戶不存在或已被停用"
        )

    return user


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


async def check_quota(
    current_user: dict = Depends(get_current_user)
):
    """檢查用戶配額（預留，後續實作）

    Args:
        current_user: 當前用戶

    Returns:
        用戶資料
    """
    # TODO: 在階段二實作配額檢查
    return current_user
