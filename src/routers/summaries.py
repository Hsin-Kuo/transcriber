"""AI 摘要管理路由"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..services.summary_service import SummaryService
from ..models.summary import SummaryResponse, GenerateSummaryResponse


router = APIRouter(prefix="/summaries", tags=["Summaries"])


def get_summary_service(db=Depends(get_database)) -> SummaryService:
    """獲取 SummaryService 實例"""
    return SummaryService(db)


@router.post("/{task_id}", response_model=GenerateSummaryResponse)
async def generate_summary(
    task_id: str,
    summary_service: SummaryService = Depends(get_summary_service),
    current_user: dict = Depends(get_current_user)
):
    """生成 AI 摘要

    Args:
        task_id: 任務 ID
        summary_service: SummaryService 實例
        current_user: 當前用戶

    Returns:
        生成結果，包含摘要或錯誤訊息
    """
    user_id = str(current_user["_id"])

    result = await summary_service.generate_summary(task_id, user_id)

    if result["status"] == "failed":
        # 返回失敗結果但不拋出異常（讓前端處理）
        return result

    return result


@router.get("/{task_id}", response_model=SummaryResponse)
async def get_summary(
    task_id: str,
    summary_service: SummaryService = Depends(get_summary_service),
    current_user: dict = Depends(get_current_user)
):
    """獲取摘要

    Args:
        task_id: 任務 ID
        summary_service: SummaryService 實例
        current_user: 當前用戶

    Returns:
        摘要資料

    Raises:
        HTTPException: 摘要不存在或無權存取
    """
    user_id = str(current_user["_id"])

    summary = await summary_service.get_summary(task_id, user_id)

    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="摘要不存在或無權存取"
        )

    return summary


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_summary(
    task_id: str,
    summary_service: SummaryService = Depends(get_summary_service),
    current_user: dict = Depends(get_current_user)
):
    """刪除摘要

    Args:
        task_id: 任務 ID
        summary_service: SummaryService 實例
        current_user: 當前用戶

    Raises:
        HTTPException: 摘要不存在或無權存取
    """
    user_id = str(current_user["_id"])

    success = await summary_service.delete_summary(task_id, user_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="摘要不存在或無權存取"
        )
