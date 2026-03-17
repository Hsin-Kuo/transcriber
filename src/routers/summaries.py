"""AI 摘要管理路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.dependencies import get_current_user
from ..auth.quota import QuotaManager
from ..database.mongodb import get_database
from ..database.repositories.user_repo import UserRepository
from ..services.summary_service import SummaryService
from ..models.summary import SummaryResponse, GenerateSummaryResponse
from ..utils.audit_logger import get_audit_logger


router = APIRouter(prefix="/summaries", tags=["Summaries"])


def get_summary_service(db=Depends(get_database)) -> SummaryService:
    """獲取 SummaryService 實例"""
    return SummaryService(db)


@router.post("/{task_id}", response_model=GenerateSummaryResponse)
async def generate_summary(
    task_id: str,
    request: Request,
    mode: str = Query("paragraph", description="顯示模式: paragraph 或 subtitle"),
    summary_service: SummaryService = Depends(get_summary_service),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """生成 AI 摘要

    Args:
        task_id: 任務 ID
        request: HTTP Request 對象
        mode: 顯示模式，subtitle 模式會優先使用 segments 內容
        summary_service: SummaryService 實例
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        生成結果，包含摘要或錯誤訊息
    """
    user_id = str(current_user["_id"])
    audit_logger = get_audit_logger()

    # 檢查 AI 摘要配額
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(user_id)
    await QuotaManager.check_ai_summary_quota(full_user, db=db)

    result = await summary_service.generate_summary(task_id, user_id, mode=mode)

    if result["status"] == "failed":
        await audit_logger.log_task_operation(
            request=request, action="summary_generate_failed",
            user_id=user_id, task_id=task_id, status_code=200,
            message=result.get("error", "AI 摘要生成失敗")
        )
        return result

    # 生成成功，增加使用量
    await QuotaManager.increment_ai_summary_usage(db, user_id)

    await audit_logger.log_task_operation(
        request=request, action="summary_generate",
        user_id=user_id, task_id=task_id, status_code=200,
        message="AI 摘要生成成功"
    )

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
    request: Request,
    summary_service: SummaryService = Depends(get_summary_service),
    current_user: dict = Depends(get_current_user)
):
    """刪除摘要

    Args:
        task_id: 任務 ID
        request: HTTP Request 對象
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

    audit_logger = get_audit_logger()
    await audit_logger.log_task_operation(
        request=request, action="summary_delete",
        user_id=user_id, task_id=task_id, status_code=204,
        message="AI 摘要已刪除"
    )
