"""
Task 查詢/列表用的業務邏輯 helper。

從 routers/tasks.py 抽取；router 只負責 HTTP 層，
enrichment / filter / expiration 判斷集中在此。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from ..utils.logger import get_logger

log = get_logger(__name__)

# ========== Progress Inference ==========

_PROGRESS_TEXT_TO_PERCENTAGE = {
    "Worker 開始處理": 3,
    "正在下載音檔": 5,
    "正在轉換音檔格式": 10,
    "正在上傳轉碼後的音檔": 15,
    "正在準備模型": 20,
    "正在轉錄音檔與說話者辨識": 30,
    "正在轉錄音檔": 30,
    "語者辨識完成": 70,
    "正在添加標點符號": 80,
    "標點處理完成": 90,
    "標點處理失敗": 90,
    "正在保存結果": 95,
    "轉錄完成": 100,
}


def _infer_progress_percentage(progress_text: str) -> int:
    """依照 progress 文字推算百分比（當 worker 未回報時使用）"""
    for keyword, pct in _PROGRESS_TEXT_TO_PERCENTAGE.items():
        if keyword in progress_text:
            return pct
    return 5


# ========== Field Access ==========

# 欄位映射：扁平名稱 -> 巢狀路徑
_FIELD_PATHS = {
    "user_id": ("user", "user_id"),
    "user_email": ("user", "user_email"),
    "filename": ("file", "filename"),
    "file_size_mb": ("file", "size_mb"),
    "punct_provider": ("config", "punct_provider"),
    "chunk_audio": ("config", "chunk_audio"),
    "diarize": ("config", "diarize"),
    "language": ("config", "language"),
    "result_file": ("result", "transcription_file"),
    "result_filename": ("result", "transcription_filename"),
    "audio_file": ("result", "audio_file"),
    "audio_filename": ("result", "audio_filename"),
    "segments_file": ("result", "segments_file"),
    "text_length": ("result", "text_length"),
    "duration_seconds": ("stats", "duration_seconds"),
    "created_at": ("timestamps", "created_at"),
    "updated_at": ("timestamps", "updated_at"),
    "completed_at": ("timestamps", "completed_at"),
}


def get_task_field(task: Dict[str, Any], field: str) -> Any:
    """安全獲取任務欄位（支援巢狀與扁平格式）"""
    if field not in _FIELD_PATHS:
        return task.get(field)

    value = task
    for key in _FIELD_PATHS[field]:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


# ========== Audio Expiration ==========

def is_audio_expired(task: Dict[str, Any], retention_days: int) -> bool:
    """判斷音檔是否已被 S3 Lifecycle 自動刪除

    根據完成時間 + tier 保留天數計算，不需要呼叫 S3。
    keep_audio 的音檔存在 kept/ 資料夾，不受 lifecycle 影響。

    retention_days 作為 fallback；優先從音檔路徑推導原始 tier 的天數，
    避免用戶升降方案後計算錯誤。
    """
    if task.get("keep_audio"):
        return False

    completed_at = task.get("timestamps", {}).get("completed_at")
    if not completed_at:
        return False

    if isinstance(completed_at, (int, float)):
        completed_at = datetime.fromtimestamp(completed_at, tz=timezone.utc)
    elif isinstance(completed_at, str):
        completed_at = datetime.fromisoformat(completed_at)

    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)

    audio_file = task.get("result", {}).get("audio_file")
    if audio_file:
        from ..utils.storage_service import extract_tier_from_path
        from ..models.quota import QUOTA_TIERS, QuotaTier
        path_tier = extract_tier_from_path(audio_file)
        if path_tier and path_tier != "kept":
            try:
                tier_config = QUOTA_TIERS.get(QuotaTier(path_tier))
                if tier_config:
                    retention_days = tier_config.get("audio_retention_days", retention_days)
            except ValueError:
                pass

    expiry_time = completed_at + timedelta(days=retention_days)
    return datetime.now(timezone.utc) > expiry_time


# ========== Enrichment ==========

def enrich_task_data(task: Dict[str, Any]) -> Dict[str, Any]:
    """豐富任務數據，添加計算欄位（進度預設值、百分比推算）"""
    enriched = task.copy()
    task_status = enriched.get("status")

    if "progress" not in enriched or not enriched["progress"]:
        if task_status == "pending":
            enriched["progress"] = "等待處理中..."
            enriched["progress_percentage"] = 0
        elif task_status == "processing":
            enriched["progress"] = "轉錄處理中..."
            if not enriched.get("progress_percentage"):
                enriched["progress_percentage"] = 5

    if enriched.get("progress") and (
        enriched.get("progress_percentage") is None
        or enriched.get("progress_percentage") == 0
    ) and task_status == "processing":
        enriched["progress_percentage"] = _infer_progress_percentage(enriched["progress"])

    if "progress_percentage" in enriched and enriched["progress_percentage"] is not None:
        try:
            enriched["progress_percentage"] = float(enriched["progress_percentage"])
        except (TypeError, ValueError):
            enriched["progress_percentage"] = 0

    return enriched


# ========== List Filtering ==========

def filter_task_for_list(task: Dict[str, Any], retention_days: int = 7) -> Dict[str, Any]:
    """過濾任務數據，只返回前端列表需要的字段"""
    filtered = {
        "_id": task.get("_id"),
        "task_id": task.get("_id"),
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "progress_percentage": task.get("progress_percentage"),
        "custom_name": task.get("custom_name"),
        "tags": task.get("tags", []),
        "keep_audio": task.get("keep_audio", False),
        "speaker_names": task.get("speaker_names", {}),
        "subtitle_settings": task.get("subtitle_settings", {}),
        "timestamps": task.get("timestamps", {}),
    }

    if task.get("file"):
        filtered["file"] = {
            "filename": task["file"].get("filename"),
            "size_mb": task["file"].get("size_mb")
        }

    if task.get("result"):
        audio_file = task["result"].get("audio_file")
        audio_filename = task["result"].get("audio_filename")

        if audio_file and is_audio_expired(task, retention_days):
            audio_file = None
            audio_filename = None

        filtered["result"] = {
            "text_length": task["result"].get("text_length"),
            "word_count": task["result"].get("word_count"),
            "audio_file": audio_file,
            "audio_filename": audio_filename
        }

    if task.get("error"):
        err = task["error"]
        filtered["error"] = err.get("code", "SYSTEM_ERROR") if isinstance(err, dict) else "SYSTEM_ERROR"

    if task.get("cancelling"):
        filtered["cancelling"] = task.get("cancelling")

    return filtered


# ========== JSON Serialization ==========

def serialize_for_json(obj):
    """將包含 datetime 等特殊類型的對象轉換為可 JSON 序列化的格式"""
    from bson import ObjectId

    if isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, ObjectId):
        return str(obj)
    else:
        return obj


# ========== User Tier Helpers ==========

async def get_user_retention_days(db, user_id: str) -> int:
    """取得用戶 tier 對應的音檔保留天數"""
    from ..database.repositories.user_repo import UserRepository
    from ..models.quota import QUOTA_TIERS, QuotaTier

    user_repo = UserRepository(db)
    full_user = await user_repo.get_by_id(user_id)
    user_tier = full_user.get("quota", {}).get("tier", "free") if full_user else "free"
    tier_config = QUOTA_TIERS.get(QuotaTier(user_tier), QUOTA_TIERS[QuotaTier.FREE])
    return tier_config.get("audio_retention_days", 7)
