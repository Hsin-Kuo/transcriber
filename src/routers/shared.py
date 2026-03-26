"""公開分享路由 — 不需要認證"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from typing import Optional
from datetime import datetime, timezone
import secrets

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.task_repo import TaskRepository
from ..utils.storage_service import is_aws

router = APIRouter(prefix="/shared", tags=["Shared"])


@router.post("/{task_id}/toggle")
async def toggle_share(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database)
):
    """切換任務的公開分享狀態（需認證，僅付費方案可用）

    Args:
        task_id: 任務 ID
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        分享狀態和 token
    """
    # 從 DB 取得完整用戶資料以檢查方案
    from ..database.repositories.user_repo import UserRepository
    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(str(current_user["_id"]))
    user_tier = full_user.get("quota", {}).get("tier", "free") if full_user else "free"
    if user_tier == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="公開分享功能僅限付費方案使用"
        )

    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    if task.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只有已完成的任務可以分享"
        )

    current_token = task.get("share_token")

    if current_token:
        # 取消分享
        await task_repo.update(task_id, {
            "share_token": None,
            "shared_at": None
        })
        return {"shared": False, "share_token": None}
    else:
        # 開啟分享：產生 token
        token = secrets.token_urlsafe(16)
        await task_repo.update(task_id, {
            "share_token": token,
            "shared_at": datetime.now(timezone.utc)
        })
        return {"shared": True, "share_token": token}


@router.get("/{token}")
async def get_shared_task(
    token: str,
    db=Depends(get_database)
):
    """取得公開分享的任務資料（不需認證）

    Args:
        token: 分享 token
        db: 資料庫實例

    Returns:
        任務的公開資料（唯讀）
    """
    task = await db.tasks.find_one({"share_token": token})

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="分享連結無效或已取消"
        )

    # 取得逐字稿內容
    content = ""
    result_info = task.get("result", {})
    task_id = str(task["_id"])

    # 從 transcriptions collection 讀取（_id = task_id）
    content_doc = await db.transcriptions.find_one({"_id": task_id})
    if content_doc:
        content = content_doc.get("content", "")
    else:
        # 向後相容：嘗試從檔案讀取
        from pathlib import Path
        transcription_file = result_info.get("transcription_file")
        if transcription_file:
            file_path = Path(transcription_file)
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")

    # 取得 segments
    segments = []
    speaker_names = task.get("speaker_names", {})
    segment_doc = await db.segments.find_one({"_id": task_id})
    if segment_doc:
        segments = segment_doc.get("segments", [])

    # 判斷音檔是否可用
    has_audio = bool(result_info.get("audio_file"))

    # 序列化日期（timestamps 儲存為 Unix epoch 秒數）
    created_at = task.get("timestamps", {}).get("completed_at") or task.get("timestamps", {}).get("created_at")
    if isinstance(created_at, (int, float)):
        created_at = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat()
    elif isinstance(created_at, datetime):
        created_at = created_at.isoformat()

    # 取得 AI 摘要（如果有）
    summary = None
    if task.get("summary_status") == "completed":
        summary_doc = await db.summaries.find_one({"_id": task_id})
        if summary_doc:
            summary = {
                "content": summary_doc.get("content", {}),
                "metadata": {
                    "model": summary_doc.get("metadata", {}).get("model", ""),
                }
            }

    # 準備返回的公開資料（僅包含必要欄位）
    return {
        "task_id": task_id,
        "display_name": task.get("custom_name") or task.get("file", {}).get("filename", ""),
        "task_type": task.get("task_type", "paragraph"),
        "created_at": created_at,
        "duration_text": _format_duration(task.get("stats", {}).get("duration_seconds")),
        "text_length": result_info.get("text_length"),
        "content": content,
        "segments": segments,
        "speaker_names": speaker_names,
        "has_audio": has_audio,
        "subtitle_settings": task.get("subtitle_settings", {}),
        "summary": summary,
    }


@router.get("/{token}/audio")
async def get_shared_audio(
    token: str,
    db=Depends(get_database)
):
    """取得公開分享任務的音檔（不需認證）

    Args:
        token: 分享 token
        db: 資料庫實例

    Returns:
        音檔（redirect to presigned URL 或 FileResponse）
    """
    task = await db.tasks.find_one({"share_token": token})

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="分享連結無效或已取消"
        )

    if is_aws():
        from ..utils.storage_service import audio_exists_by_path, get_presigned_url_by_path
        from urllib.parse import urlparse

        audio_file_path = task.get("result", {}).get("audio_file")
        if not audio_file_path or not audio_exists_by_path(audio_file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="音檔已過期或已被刪除"
            )

        presigned_url = get_presigned_url_by_path(audio_file_path, expires_in=3600)

        parsed = urlparse(presigned_url)
        if not parsed.hostname or not parsed.hostname.endswith(".amazonaws.com"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="產生的下載連結異常"
            )

        return RedirectResponse(url=presigned_url)
    else:
        from fastapi.responses import FileResponse
        from pathlib import Path

        audio_file_path = task.get("result", {}).get("audio_file")
        if not audio_file_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="音檔不存在"
            )

        audio_file = Path(audio_file_path)
        if not audio_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="音檔不存在"
            )

        return FileResponse(
            audio_file,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline",
                "Accept-Ranges": "bytes"
            }
        )


def _format_duration(seconds) -> Optional[str]:
    """格式化秒數為可讀的時間字串"""
    if not seconds:
        return None
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
