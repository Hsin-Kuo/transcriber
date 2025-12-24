"""標籤管理路由"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import List

from ..auth.dependencies import get_current_user
from ..dependencies import get_tag_service
from ..services.tag_service import TagService
from ..models.tag import TagCreate, TagUpdate, TagOrderUpdate, TagResponse


router = APIRouter(prefix="/tags", tags=["Tags"])


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_data: TagCreate,
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """建立新標籤

    Args:
        tag_data: 標籤資料
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        建立的標籤

    Raises:
        HTTPException: 標籤已存在
    """
    try:
        tag = await tag_service.create_tag(
            user_id=str(current_user["_id"]),
            name=tag_data.name,
            color=tag_data.color,
            description=tag_data.description
        )
        return tag
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("", response_model=List[TagResponse])
async def get_all_tags(
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取所有標籤

    Args:
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        標籤列表
    """
    tags = await tag_service.get_all_tags(str(current_user["_id"]))
    return tags


@router.get("/order")
async def get_tag_order(
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取標籤順序

    Args:
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        標籤 ID 順序列表
    """
    tags = await tag_service.get_all_tags(str(current_user["_id"]))
    tag_ids = [str(tag.get("_id") or tag.get("tag_id")) for tag in tags]

    return {
        "order": tag_ids,
        "count": len(tag_ids)
    }


@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(
    tag_id: str,
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取單個標籤

    Args:
        tag_id: 標籤 ID
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        標籤資料

    Raises:
        HTTPException: 標籤不存在或無權訪問
    """
    tag = await tag_service.get_tag(str(current_user["_id"]), tag_id)

    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="標籤不存在或無權訪問"
        )

    return tag


@router.put("/order")
async def update_tag_order(
    request: Request,
    order_data: TagOrderUpdate,
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """更新標籤順序

    Args:
        request: Request 對象
        order_data: 順序資料
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        成功訊息

    Raises:
        HTTPException: 標籤不存在或無權訪問
    """
    try:
        print(f"🔍 更新標籤順序 - user_id: {current_user['_id']}, tag_ids: {order_data.tag_ids}")
        await tag_service.update_tag_order(
            str(current_user["_id"]),
            order_data.tag_ids
        )
        print(f"✅ 標籤順序更新成功")

        # 記錄 audit log
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log(
            user_id=str(current_user["_id"]),
            log_type="tag",
            action="update_order",
            ip_address=request.client.host if request.client else "unknown",
            path=str(request.url.path),
            method=request.method,
            status_code=200,
            response_message=f"更新標籤順序（{len(order_data.tag_ids)} 個標籤）",
            user_agent=request.headers.get("user-agent", "unknown")
        )

        return {"message": "標籤順序已更新"}
    except ValueError as e:
        print(f"❌ 更新標籤順序失敗: {e}")

        # 記錄失敗的 audit log
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log(
            user_id=str(current_user["_id"]),
            log_type="tag",
            action="update_order",
            ip_address=request.client.host if request.client else "unknown",
            path=str(request.url.path),
            method=request.method,
            status_code=400,
            response_message="更新標籤順序失敗",
            user_agent=request.headers.get("user-agent", "unknown")
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"❌ 更新標籤順序時發生未預期的錯誤: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新標籤順序失敗: {str(e)}"
        )


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: str,
    tag_data: TagUpdate,
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """更新標籤

    Args:
        tag_id: 標籤 ID
        tag_data: 更新資料
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        更新後的標籤

    Raises:
        HTTPException: 標籤不存在、無權訪問或新名稱已存在
    """
    try:
        tag = await tag_service.update_tag(
            user_id=str(current_user["_id"]),
            tag_id=tag_id,
            name=tag_data.name,
            color=tag_data.color,
            description=tag_data.description
        )

        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="標籤不存在或無權訪問"
            )

        return tag

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: str,
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """刪除標籤

    Args:
        tag_id: 標籤 ID
        tag_service: TagService 實例
        current_user: 當前用戶

    Raises:
        HTTPException: 標籤不存在或無權訪問
    """
    try:
        await tag_service.delete_tag(str(current_user["_id"]), tag_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/statistics")
async def get_tag_statistics(
    tag_service: TagService = Depends(get_tag_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取標籤統計資訊

    Args:
        tag_service: TagService 實例
        current_user: 當前用戶

    Returns:
        標籤統計列表
    """
    stats = await tag_service.get_tag_statistics(str(current_user["_id"]))
    return stats
