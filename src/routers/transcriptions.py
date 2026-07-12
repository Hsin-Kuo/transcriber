"""轉錄管理路由"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone
from io import BytesIO
import asyncio
import uuid
import json
import shutil
import mimetypes

import aiofiles

from ..auth.dependencies import get_current_user
from ..database.mongodb import get_database
from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.user_repo import UserRepository
from ..dependencies import get_intake_service
from ..models.intake import IntakeConfig
from ..models.quota import has_feature
from ..models.transcription import SpeakerNamesUpdate
from ..services.intake_service import TranscriptionIntakeService
from ..services.task_service import TaskService
from ..services.utils.audio_validator import (
    validate_filename_extension,
    validate_magic_bytes,
)
from ..services.utils.whisper_processor import WhisperProcessor
from ..services.utils.punctuation_processor import PunctuationProcessor
from ..services.utils.diarization_processor import DiarizationProcessor
from ..utils.api_errors import api_error
from ..utils.storage.backend import is_aws
from ..utils.config_loader import get_parameter, get_temp_dir
from ..utils.logger import get_logger
from ..services.task_dispatch import (
    LocalDispatch,
    get_task_dispatch,
    init_task_dispatch,
)


router = APIRouter(prefix="/transcriptions", tags=["Transcriptions"])
log = get_logger(__name__)


async def _stream_upload_to(upload_file: UploadFile, dest_path: Path) -> None:
    """Streaming UploadFile -> 磁碟，避免 await read() 一次性把整檔載入 RAM + sync write 卡 event loop。"""
    async with aiofiles.open(dest_path, "wb") as out:
        while True:
            buf = await upload_file.read(1024 * 1024)
            if not buf:
                break
            await out.write(buf)


# 全域處理器單例（在啟動時初始化；router 用 _diarization_processor 檢查可用性）
_whisper_processor: Optional[WhisperProcessor] = None
_punctuation_processor: Optional[PunctuationProcessor] = None
_diarization_processor: Optional[DiarizationProcessor] = None


def init_local_dispatch(
    whisper_model,
    task_service: TaskService,
    progress_store,
    model_name: str = "medium",
    diarization_pipeline=None,
    executor=None,
) -> LocalDispatch:
    """建立處理器 + LocalDispatch，註冊為 Task dispatch 單例（local 模式 startup 呼叫）。

    Args:
        whisper_model: Whisper 模型實例
        task_service: TaskService 實例
        progress_store: ProgressStore（應與 task_service 共用同一個實例）
        model_name: 模型名稱（用於 ProcessPoolExecutor 中重新載入模型）
        diarization_pipeline: Diarization pipeline（可選）
        executor: 線程池執行器（可選）
    """
    global _whisper_processor, _punctuation_processor, _diarization_processor

    _whisper_processor = WhisperProcessor(whisper_model, model_name)
    _punctuation_processor = PunctuationProcessor()
    _diarization_processor = (
        DiarizationProcessor(diarization_pipeline) if diarization_pipeline else None
    )

    dispatch = LocalDispatch(
        task_service=task_service,
        progress_store=progress_store,
        whisper=_whisper_processor,
        punctuation=_punctuation_processor,
        diarization=_diarization_processor,
        executor=executor,
    )
    init_task_dispatch(dispatch)
    return dispatch


def get_task_field(task: dict, field: str):
    """安全獲取任務欄位（支援巢狀與扁平格式）

    Args:
        task: 任務資料
        field: 欄位名稱

    Returns:
        欄位值
    """
    # 欄位路徑映射：每個欄位可能的多個路徑（依優先順序）
    FIELD_PATHS = {
        # 使用者相關
        "user_id": [("user", "user_id"), "user_id"],
        "user_email": [("user", "user_email"), "user_email"],

        # 檔案相關
        "filename": [("file", "filename"), "filename"],
        "file_size": [("file", "size_mb"), "file_size"],

        # 結果檔案
        "result_file": [("result", "transcription_file"), "result_file"],
        "result_filename": [("result", "transcription_filename"), "result_filename"],
        "audio_file": [("result", "audio_file"), "audio_file"],
        "audio_filename": [("result", "audio_filename"), "audio_filename"],
        "segments_file": [("result", "segments_file"), "segments_file"],
        "segments_filename": [("result", "segments_filename"), "segments_filename"],

        # 配置相關
        "punct_provider": [("config", "punct_provider"), "punct_provider"],
        "chunk_audio": [("config", "chunk_audio"), "chunk_audio"],
        "chunk_minutes": [("config", "chunk_minutes"), "chunk_minutes"],
        "diarize": [("config", "diarize"), "diarize"],
        "max_speakers": [("config", "max_speakers"), "max_speakers"],
        "language": [("config", "language"), "language"],

        # 時間戳記
        "created_at": [("timestamps", "created_at"), "created_at"],
        "updated_at": [("timestamps", "updated_at"), "updated_at"],
        "started_at": [("timestamps", "started_at"), "started_at"],
        "completed_at": [("timestamps", "completed_at"), "completed_at"],

        # 使用者設定
        "custom_name": ["custom_name"],
        "keep_audio": ["keep_audio"],
        "tags": ["tags"],

        # 錯誤資訊
        "error": [("error", "message"), "error"],
        "error_detail": [("error", "detail"), "error_detail"],
    }

    # 如果有預定義的路徑映射，使用它
    if field in FIELD_PATHS:
        paths = FIELD_PATHS[field]
        for path in paths:
            if isinstance(path, tuple):
                # 巢狀路徑
                value = task
                for key in path:
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        value = None
                        break
                if value is not None:
                    return value
            else:
                # 直接路徑
                value = task.get(path)
                if value is not None:
                    return value

    # 否則嘗試直接獲取
    return task.get(field)


def _validate_create_params(task_type, chunk_minutes, max_speakers, language, punct_provider, custom_name):
    """輸入驗證（純 HTTP 層白名單檢查）。"""
    if task_type not in ("paragraph", "subtitle"):
        raise api_error("TRANSCRIPTION_INVALID_TASK_TYPE", "Task type must be 'paragraph' or 'subtitle'", status.HTTP_400_BAD_REQUEST)
    if chunk_minutes < 1 or chunk_minutes > 120:
        raise api_error("TRANSCRIPTION_INVALID_CHUNK_MINUTES", "Chunk length must be between 1 and 120 minutes", status.HTTP_400_BAD_REQUEST)
    if max_speakers is not None and (max_speakers < 2 or max_speakers > 10):
        raise api_error("TRANSCRIPTION_INVALID_MAX_SPEAKERS", "Max speakers must be between 2 and 10", status.HTTP_400_BAD_REQUEST)
    ALLOWED_LANGUAGES = {"zh", "zh-TW", "zh-CN", "nan-TW", "en", "ja", "ko", "auto"}
    if language not in ALLOWED_LANGUAGES:
        raise api_error("TRANSCRIPTION_UNSUPPORTED_LANGUAGE", "Unsupported language: {language}. Allowed: {allowed}", status.HTTP_400_BAD_REQUEST, language=language, allowed=', '.join(ALLOWED_LANGUAGES))
    ALLOWED_PUNCT = {"openai", "gemini", "none"}
    if punct_provider not in ALLOWED_PUNCT:
        raise api_error("TRANSCRIPTION_UNSUPPORTED_PUNCT_PROVIDER", "Unsupported punctuation provider: {punct_provider}", status.HTTP_400_BAD_REQUEST, punct_provider=punct_provider)
    if custom_name and len(custom_name) > 255:
        raise api_error("TRANSCRIPTION_CUSTOM_NAME_TOO_LONG", "Custom name too long (max 255 characters)", status.HTTP_400_BAD_REQUEST)


async def _assemble_upload(
    *,
    upload_id,
    merge_upload_ids,
    merge_files,
    files,
    file,
    custom_name,
    current_user,
):
    """把 HTTP upload 參數組裝成 (file_path, filename, temp_dir)。

    這是正當的 router 責任：把原始 HTTP 請求轉成 service 可消費的 Path。
    """
    from .uploads import consume_upload, MAX_UPLOAD_SIZE, MAX_UPLOAD_SIZE_MB
    from src.services.audio_service import AudioService

    user_id = str(current_user["_id"])

    # ── 單檔分片上傳 ──
    if upload_id:
        meta = await consume_upload(upload_id, user_id)
        if not meta:
            raise api_error("TRANSCRIPTION_INVALID_UPLOAD_ID", "upload_id is invalid, not yet assembled, or not authorized", status.HTTP_400_BAD_REQUEST)
        temp_dir = meta["temp_dir"]
        file_path = meta["assembled_path"]
        filename = custom_name.strip() if custom_name and custom_name.strip() else file_path.name
        log.info("upload.chunked.assembled", filename=file_path.name, size_mb=round(file_path.stat().st_size / 1024 / 1024, 2))
        return file_path, filename, temp_dir

    # ── 合併模式分片上傳 ──
    if merge_upload_ids:
        try:
            uid_list = json.loads(merge_upload_ids)
        except json.JSONDecodeError:
            raise api_error("TRANSCRIPTION_INVALID_MERGE_UPLOAD_IDS", "Invalid merge_upload_ids format", status.HTTP_400_BAD_REQUEST)
        if len(uid_list) < 2:
            raise api_error("TRANSCRIPTION_MERGE_NEEDS_TWO_FILES", "Merge mode requires at least 2 files", status.HTTP_400_BAD_REQUEST)

        merge_paths = []
        merge_temp_dirs = []
        for uid in uid_list:
            meta = await consume_upload(uid, user_id)
            if not meta:
                for d in merge_temp_dirs:
                    if d.exists(): shutil.rmtree(d)
                raise api_error("TRANSCRIPTION_INVALID_UPLOAD_ID", "upload_id {uid} is invalid, not yet assembled, or not authorized", status.HTTP_400_BAD_REQUEST, uid=uid)
            merge_paths.append(meta["assembled_path"])
            merge_temp_dirs.append(meta["temp_dir"])

        temp_dir = get_temp_dir()
        audio_service = AudioService()
        merged_output = temp_dir / f"merged_{uuid.uuid4().hex[:8]}.mp3"
        # ffmpeg merge 跑 subprocess，sync I/O 包進 threadpool 才不會卡 event loop
        file_path = await asyncio.to_thread(
            audio_service.merge_audio_files, merge_paths, output_path=merged_output
        )

        if custom_name and custom_name.strip():
            filename = f"{custom_name.strip()}.mp3"
        else:
            filename = merge_paths[0].name.rsplit('.', 1)[0] + '.mp3'

        for d in merge_temp_dirs:
            if d.exists(): shutil.rmtree(d, ignore_errors=True)
        return file_path, filename, temp_dir

    # ── 直接上傳（可能多檔合併） ──
    if merge_files and files and len(files) > 0:
        uploaded_files = files
        if len(uploaded_files) < 2:
            raise api_error("TRANSCRIPTION_MERGE_NEEDS_TWO_FILES", "Merge mode requires at least 2 files", status.HTTP_400_BAD_REQUEST)
    elif file:
        uploaded_files = [file]
    else:
        raise api_error("TRANSCRIPTION_NO_FILE_PROVIDED", "Please provide an audio file or upload_id", status.HTTP_400_BAD_REQUEST)

    total_size = sum(f.size or 0 for f in uploaded_files)
    if total_size > 0 and total_size > MAX_UPLOAD_SIZE:
        raise api_error("TRANSCRIPTION_FILES_TOO_LARGE", "Total file size exceeds limit (max {max}MB)", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, max=MAX_UPLOAD_SIZE_MB)

    for uf in uploaded_files:
        validate_filename_extension(uf.filename)

    temp_dir = get_temp_dir()

    if len(uploaded_files) > 1:
        saved_files = []
        for idx, uf in enumerate(uploaded_files):
            suffix = Path(uf.filename).suffix
            temp_path = temp_dir / f"input_{idx}{suffix}"
            await _stream_upload_to(uf, temp_path)
            try:
                validate_magic_bytes(temp_path)
            except HTTPException:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise
            saved_files.append(temp_path)

        audio_service = AudioService()
        merged_output = temp_dir / f"merged_{uuid.uuid4().hex[:8]}.mp3"
        # ffmpeg merge 跑 subprocess，sync I/O 包進 threadpool 才不會卡 event loop
        file_path = await asyncio.to_thread(
            audio_service.merge_audio_files, saved_files, output_path=merged_output
        )

        if custom_name and custom_name.strip():
            filename = f"{custom_name.strip()}.mp3"
        else:
            filename = uploaded_files[0].filename.rsplit('.', 1)[0] + '.mp3'
    else:
        uf = uploaded_files[0]
        suffix = Path(uf.filename).suffix
        file_path = temp_dir / f"input{suffix}"
        await _stream_upload_to(uf, file_path)
        try:
            validate_magic_bytes(file_path)
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        filename = uf.filename

    return file_path, filename, temp_dir


@router.post("")
async def create_transcription(
    request: Request,
    files: Optional[List[UploadFile]] = File(None, description="多個音檔 (用於合併)"),
    file: Optional[UploadFile] = File(None, description="單個音檔 (支援 mp3/m4a/wav/mp4 等格式)"),
    merge_files: bool = Form(False, description="是否為合併模式"),
    custom_name: Optional[str] = Form(None, description="自訂任務名稱"),
    task_type: str = Form("paragraph", description="任務類型 (paragraph/subtitle)"),
    punct_provider: str = Form("gemini", description="標點提供者 (openai/gemini/none)"),
    chunk_audio: bool = Form(True, description="是否使用分段模式"),
    chunk_minutes: int = Form(10, description="分段長度（分鐘）"),
    diarize: bool = Form(False, description="是否啟用說話者辨識"),
    max_speakers: Optional[int] = Form(None, description="最大講者人數（可選，2-10）"),
    language: str = Form("zh", description="轉錄語言 (zh/zh-TW/zh-CN/en/ja/ko/auto)"),
    tags: Optional[str] = Form(None, description="標籤（JSON 陣列字串）"),
    upload_id: Optional[str] = Form(None, description="分片上傳完成後的 upload_id（替代直接上傳檔案）"),
    merge_upload_ids: Optional[str] = Form(None, description="合併模式分片上傳的 upload_id 陣列（JSON）"),
    ui_language: Optional[str] = Form(None, description="使用者介面語言（用於自動偵測中文時判斷繁簡體）"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database),
    intake_service: TranscriptionIntakeService = Depends(get_intake_service),
):
    """建立轉錄任務（支援單檔或多檔合併）"""
    # ── 輸入驗證（HTTP 層責任） ──
    _validate_create_params(task_type, chunk_minutes, max_speakers, language, punct_provider, custom_name)

    if task_type == "subtitle":
        punct_provider = "none"

    if custom_name:
        custom_name = custom_name.replace("/", "").replace("\\", "").replace("..", "")

    # ── Upload 組裝：把 HTTP 請求變成 (file_path, filename, temp_dir) ──
    file_path, original_filename, temp_dir = await _assemble_upload(
        upload_id=upload_id,
        merge_upload_ids=merge_upload_ids,
        merge_files=merge_files,
        files=files,
        file=file,
        custom_name=custom_name,
        current_user=current_user,
    )

    # ── 解析標籤 ──
    task_tags = []
    if tags:
        try:
            task_tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            task_tags = []

    # ── 委派給 IntakeService ──
    intake_service.set_diarization_available(bool(_diarization_processor))
    result = await intake_service.intake(
        user_id=str(current_user["_id"]),
        user_email=current_user["email"],
        file_path=file_path,
        filename=original_filename,
        config=IntakeConfig(
            task_type=task_type,
            punct_provider=punct_provider,
            chunk_audio=chunk_audio,
            chunk_minutes=chunk_minutes,
            diarize=diarize,
            max_speakers=max_speakers,
            language=language,
            ui_language=ui_language,
            tags=task_tags,
            custom_name=custom_name,
        ),
        temp_dir=temp_dir,
    )

    # ── Audit log ──
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_task_operation(
            request=request,
            action="create",
            user_id=str(current_user["_id"]),
            task_id=result.task_id,
            status_code=200,
            message=f"創建轉錄任務：{original_filename}",
            request_body={
                "filename": original_filename,
                "size_mb": result.size_mb,
                "punct_provider": punct_provider,
                "chunk_audio": chunk_audio,
                "diarize": diarize,
                "language": language,
            }
        )
    except Exception as e:
        log.warning("transcription.audit_log.failed", action="create", error=str(e))

    # ── Response ──
    queued = result.status == "pending"
    if queued and result.queue_position:
        message = f"轉錄任務已加入隊列，目前有 {result.queue_position} 個任務等待中"
    else:
        message = "轉錄任務已建立，正在背景處理"

    return {
        "task_id": result.task_id,
        "status": result.status,
        "message": message,
        "queued": queued,
        "queue_position": result.queue_position,
        "file": {
            "filename": result.filename,
            "size_mb": result.size_mb,
        },
        "config": {
            "punct_provider": punct_provider,
            "chunk_audio": chunk_audio,
            "language": language,
        }
    }


@router.get("/{task_id}/download")
async def download_transcription(
    request: Request,
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """下載轉錄結果

    Args:
        request: Request 對象
        task_id: 任務 ID
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        轉錄結果檔案

    Raises:
        HTTPException: 任務不存在、無權訪問或尚未完成
    """
    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    if task["status"] != "completed":
        raise api_error("TRANSCRIPTION_TASK_NOT_COMPLETED", "Task not completed yet (current status: {status})", status.HTTP_400_BAD_REQUEST, status=task['status'])

    # 從 transcriptions collection 讀取內容（新方式）
    from src.database.repositories.transcription_repo import TranscriptionRepository
    from fastapi.responses import StreamingResponse
    from io import BytesIO

    transcription_repo = TranscriptionRepository(db)
    transcription = await transcription_repo.get_by_task_id(task_id)

    if not transcription:
        # 向後相容：嘗試從檔案讀取
        result_file_path = get_task_field(task, "result_file")
        if result_file_path:
            result_file = Path(result_file_path)
            if result_file.exists():
                content = result_file.read_text(encoding='utf-8')
            else:
                raise api_error("TRANSCRIPTION_CONTENT_NOT_FOUND", "Transcription content not found", status.HTTP_404_NOT_FOUND)
        else:
            raise api_error("TRANSCRIPTION_CONTENT_NOT_FOUND", "Transcription content not found", status.HTTP_404_NOT_FOUND)
    else:
        content = transcription["content"]

    # 使用自訂名稱作為下載檔名（如果有設定）
    download_filename = task.get("custom_name")
    if download_filename:
        # 移除音訊副檔名
        for ext in ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma']:
            if download_filename.lower().endswith(ext):
                download_filename = download_filename[:-len(ext)]
                break
        # 確保有 .txt 副檔名
        if not download_filename.endswith('.txt'):
            download_filename = download_filename + '.txt'
    else:
        download_filename = f"{task_id}.txt"

    # 使用 RFC 5987 編碼來支援中文檔名
    encoded_filename = quote(download_filename, safe='')

    # 記錄 audit log（下載轉錄結果）
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_transcription_operation(
            request=request,
            action="download",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"下載轉錄結果：{download_filename}"
        )
    except Exception as e:
        log.warning("transcription.audit_log.failed", action="download", error=str(e))

    return StreamingResponse(
        BytesIO(content.encode('utf-8')),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


class ExportPdfRequest(BaseModel):
    """PDF 匯出參數。

    transcript_text 由 frontend 預先格式化（依 paragraph 或 subtitle mode），
    backend 只做 PDF render 不做文字組合。summary 從 DB 抓，不在 body 重送。

    transcript_text 上限 2,000,000 字（約 4MB UTF-8）— 防單一請求灌爆
    generate_pdf 工人 thread 與 t3.small 記憶體。正常逐字稿（百分鐘音檔）
    遠在這個門檻之下；超長轉錄應分段下載。
    """
    title: str = Field(..., max_length=500, description="PDF 抬頭與下載檔名")
    transcript_text: Optional[str] = Field(None, max_length=2_000_000, description="已格式化逐字稿純文字")
    include_summary: bool = True
    include_transcript: bool = True
    locale: Literal["zh-TW", "en"] = "zh-TW"


@router.post("/{task_id}/export/pdf")
async def export_transcription_pdf(
    task_id: str,
    payload: ExportPdfRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """Server-side PDF 生成（支援 TC/SC/JP/KR 多語言 CJK 字體）。

    對應 frontend useTranscriptDownload.js 的 downloadAsPdf()，把 ReportLab
    渲染搬到 backend，前端不再需要 5.4MB 字體 + pdfmake bundle。
    """
    # 1. Auth + task 存在 + 已完成
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))
    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)
    if task["status"] != "completed":
        raise api_error("TRANSCRIPTION_TASK_NOT_COMPLETED", "Task not completed yet (current status: {status})", status.HTTP_400_BAD_REQUEST, status=task['status'])

    # 2. 抓 summary（如需要）
    summary_doc = None
    if payload.include_summary:
        from ..database.repositories.summary_repo import SummaryRepository
        summary_repo = SummaryRepository(db)
        summary_doc = await summary_repo.get_by_task_id(task_id)

    # 3. 決定 primary_lang：task.language → ISO 拼出 IETF tag
    raw_lang = (task.get("language") or "zh-TW").strip()
    lang_map = {
        "zh": "zh-TW", "zh-tw": "zh-TW", "zh-hant": "zh-TW",
        "zh-cn": "zh-CN", "zh-hans": "zh-CN",
        "ja": "ja", "ja-jp": "ja",
        "ko": "ko", "ko-kr": "ko",
    }
    primary_lang = lang_map.get(raw_lang.lower(), "zh-TW")

    # 4. 生成 PDF — ReportLab 是 sync CPU-bound（10k 行轉錄 ~1.5s，極端 alternating
    #    script 可達數十秒）。用 asyncio.to_thread 搬到 thread pool 避免阻塞
    #    event loop 卡住 SSE 進度推送、login、其他 API。
    from ..utils.pdf.pdf_generator import generate_pdf
    pdf_bytes = await asyncio.to_thread(
        generate_pdf,
        title=payload.title,
        summary=summary_doc,
        transcript_text=payload.transcript_text,
        include_summary=payload.include_summary,
        include_transcript=payload.include_transcript,
        primary_lang=primary_lang,
        locale=payload.locale,
    )

    # 5. 組檔名（UTF-8 percent-encode 給 Content-Disposition）
    download_filename = (payload.title or "transcript").strip() or "transcript"
    if not download_filename.lower().endswith(".pdf"):
        download_filename += ".pdf"
    encoded = quote(download_filename, safe='')

    # 6. Audit log（同 /download 既有 pattern；PDF 是高成本操作，留 trail 給濫用偵測）
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_transcription_operation(
            request=request,
            action="export_pdf",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"匯出 PDF：{download_filename}（{len(pdf_bytes):,} bytes，lang={primary_lang}）"
        )
    except Exception as e:
        log.warning("transcription.audit_log.failed", action="export_pdf", error=str(e))

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "Content-Length": str(len(pdf_bytes)),
        }
    )


@router.get("/{task_id}/audio")
async def download_audio(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """下載原始音檔

    認證跟其他端點一樣走共用的 get_current_user（httpOnly access_token
    cookie）。這個端點以前因為 <audio src> 不支援自訂 header，自己另外寫
    了一份「header 或 ?token= 查詢參數」的雙模式驗證；改用 cookie 後
    <audio src> 的同源請求會自動帶 cookie，不再需要獨立的 token-in-URL
    機制，因此收斂回共用的 get_current_user，不再自己重複認證邏輯。

    Args:
        task_id: 任務 ID
        current_user: 目前登入使用者
        db: 資料庫實例

    Returns:
        音檔檔案

    Raises:
        HTTPException: 任務不存在、無權訪問或音檔不存在
    """
    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    if is_aws():
        # AWS 模式：回傳 S3 presigned URL redirect
        from ..utils.storage.backend import S3_REGION
        from ..utils.storage.compact import audio_exists_by_path, get_presigned_url_by_path
        from fastapi.responses import RedirectResponse
        from urllib.parse import urlparse

        audio_file_path = task.get("result", {}).get("audio_file")
        if not audio_file_path or not audio_exists_by_path(audio_file_path):
            # S3 Lifecycle 已刪除，順便清掉 DB 殘留記錄
            if audio_file_path:
                task_repo = TaskRepository(db)
                await task_repo.update(task_id, {
                    "result.audio_file": None,
                    "result.audio_filename": None
                })
            raise api_error("TRANSCRIPTION_AUDIO_EXPIRED", "Audio file has expired or been deleted", status.HTTP_404_NOT_FOUND)

        presigned_url = get_presigned_url_by_path(audio_file_path, expires_in=3600)

        # 驗證 presigned URL 指向合法的 S3 域名，防止 open redirect
        parsed = urlparse(presigned_url)
        if not parsed.hostname or not parsed.hostname.endswith(".amazonaws.com"):
            raise api_error("TRANSCRIPTION_INVALID_DOWNLOAD_URL", "Generated download link is invalid", status.HTTP_500_INTERNAL_SERVER_ERROR)

        return RedirectResponse(url=presigned_url)
    else:
        # 本地模式：回傳 FileResponse
        audio_file_path = get_task_field(task, "audio_file")
        if not audio_file_path:
            raise api_error("TRANSCRIPTION_AUDIO_NOT_FOUND", "Audio file not found (may have been deleted)", status.HTTP_404_NOT_FOUND)

        audio_file = Path(audio_file_path)
        if not audio_file.exists():
            raise api_error("TRANSCRIPTION_AUDIO_NOT_FOUND", "Audio file not found", status.HTTP_404_NOT_FOUND)

        # 使用 task_id 作為下載檔名，確保唯一性且不會重複
        download_filename = f"{task_id}{audio_file.suffix}"

        # 使用 RFC 5987 編碼來支援中文檔名
        encoded_filename = quote(download_filename, safe='')

        # 根據檔案副檔名判斷 MIME type
        file_suffix = audio_file.suffix.lower()
        media_type_map = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
            ".wma": "audio/x-ms-wma",
            ".opus": "audio/opus"
        }
        media_type = media_type_map.get(file_suffix)

        # 如果映射表中沒有，嘗試使用 mimetypes 模組猜測
        if not media_type:
            media_type, _ = mimetypes.guess_type(str(audio_file))

        # 如果還是無法判斷，使用預設的音檔類型
        if not media_type or not media_type.startswith('audio'):
            media_type = "audio/mpeg"

        return FileResponse(
            audio_file,
            media_type=media_type,
            headers={
                # 使用 inline 而非 attachment，讓瀏覽器可以串流播放
                "Content-Disposition": f"inline; filename*=UTF-8''{encoded_filename}",
                # 允許範圍請求，支援音訊跳轉
                "Accept-Ranges": "bytes"
            }
        )


@router.get("/{task_id}/segments")
async def get_segments(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """獲取轉錄的時間軸片段資料

    Args:
        task_id: 任務 ID
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        Segments 資料

    Raises:
        HTTPException: 任務不存在、無權訪問或 segments 不存在
    """
    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    if task["status"] != "completed":
        raise api_error("TRANSCRIPTION_TASK_NOT_COMPLETED", "Task not completed yet (current status: {status})", status.HTTP_400_BAD_REQUEST, status=task['status'])

    # 從 segments collection 讀取資料（新方式）
    from src.database.repositories.segment_repo import SegmentRepository

    segment_repo = SegmentRepository(db)
    segment_doc = await segment_repo.get_by_task_id(task_id)

    if not segment_doc:
        # 向後相容：嘗試從檔案讀取
        segments_file_path = get_task_field(task, "segments_file")
        if segments_file_path:
            segments_file = Path(segments_file_path)
            if segments_file.exists():
                try:
                    with open(segments_file, 'r', encoding='utf-8') as f:
                        segments_data = json.load(f)
                except Exception as e:
                    raise api_error("TRANSCRIPTION_SEGMENTS_READ_FAILED", "Failed to read segments file: {error}", status.HTTP_500_INTERNAL_SERVER_ERROR, error=str(e))
            else:
                raise api_error("TRANSCRIPTION_SEGMENTS_NOT_FOUND", "Segments not found", status.HTTP_404_NOT_FOUND)
        else:
            raise api_error("TRANSCRIPTION_SEGMENTS_NOT_FOUND", "Segments not found", status.HTTP_404_NOT_FOUND)
    else:
        segments_data = segment_doc["segments"]

    # 獲取講者名稱對應
    speaker_names = task.get("speaker_names", {})

    return {
        "task_id": task_id,
        "segments": segments_data,
        "speaker_names": speaker_names
    }


@router.put("/{task_id}/content")
async def update_content(
    request: Request,
    task_id: str,
    content: dict,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新轉錄文字內容和 segments

    Args:
        request: Request 對象
        task_id: 任務 ID
        content: 新的文字內容 {"text": "...", "segments": [...]} (segments 為可選)
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在、無權訪問或更新失敗
    """
    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    if task["status"] != "completed":
        raise api_error("TRANSCRIPTION_CONTENT_UPDATE_NOT_COMPLETED", "Can only update content of completed tasks (current status: {status})", status.HTTP_400_BAD_REQUEST, status=task['status'])

    # 更新 MongoDB collections（新方式）
    from src.database.repositories.transcription_repo import TranscriptionRepository
    from src.database.repositories.segment_repo import SegmentRepository
    from src.utils.time_utils import get_utc_timestamp

    try:
        # 1. 更新 transcriptions collection
        new_text = content.get("text", "")
        if new_text:
            transcription_repo = TranscriptionRepository(db)

            exists = await transcription_repo.exists(task_id)
            if exists:
                await transcription_repo.update(task_id, new_text)
                log.debug("transcription.content.updated", task_id=task_id, created=False)
            else:
                await transcription_repo.create(task_id, new_text)
                log.debug("transcription.content.updated", task_id=task_id, created=True)

        # 2. 更新 segments collection
        new_segments = content.get("segments")
        if new_segments is not None:
            segment_repo = SegmentRepository(db)

            exists = await segment_repo.exists(task_id)
            if exists:
                await segment_repo.update(task_id, new_segments)
                log.debug("transcription.segments.updated", task_id=task_id, count=len(new_segments), created=False)
            else:
                await segment_repo.create(task_id, new_segments)
                log.debug("transcription.segments.updated", task_id=task_id, count=len(new_segments), created=True)

        # 3. 更新 tasks collection 的時間戳（task_repo.update 會自動同步 updated_at 和 timestamps.updated_at）
        await task_repo.update(task_id, {})
        log.debug("task.timestamp.updated", task_id=task_id)

        response_message = "轉錄內容已更新"
        if new_segments is not None:
            response_message = "轉錄內容和字幕已更新"

        # 記錄 audit log（更新轉錄內容）
        try:
            from ..utils.audit_logger import get_audit_logger
            audit_logger = get_audit_logger()
            await audit_logger.log_transcription_operation(
                request=request,
                action="update_content",
                user_id=str(current_user["_id"]),
                task_id=task_id,
                status_code=200,
                message=response_message
            )
        except Exception as e:
            log.warning("transcription.audit_log.failed", action="update_content", error=str(e))

        return {
            "message": response_message,
            "task_id": task_id,
            "segments_updated": new_segments is not None
        }
    except Exception as e:
        raise api_error("TRANSCRIPTION_CONTENT_UPDATE_FAILED", "Failed to update transcription content: {error}", status.HTTP_500_INTERNAL_SERVER_ERROR, error=str(e))


@router.put("/{task_id}/metadata")
async def update_metadata(
    request: Request,
    task_id: str,
    metadata: dict,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新任務元數據（自訂名稱）

    Args:
        request: Request 對象
        task_id: 任務 ID
        metadata: 元數據 {"custom_name": "..."}
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在、無權訪問或更新失敗
    """
    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    # 準備更新數據
    updates = {}
    # 支援 custom_name 或 title（向後兼容）
    if "custom_name" in metadata:
        updates["custom_name"] = metadata["custom_name"]
    elif "title" in metadata:
        updates["custom_name"] = metadata["title"]

    if not updates:
        raise api_error("TRANSCRIPTION_NO_METADATA_PROVIDED", "No metadata provided to update", status.HTTP_400_BAD_REQUEST)

    # 更新資料庫
    success = await task_repo.update(task_id, updates)

    if not success:
        raise api_error("TRANSCRIPTION_METADATA_UPDATE_FAILED", "Failed to update metadata", status.HTTP_500_INTERNAL_SERVER_ERROR)

    log.info("task.metadata.updated", task_id=task_id, updates=updates)

    # 記錄 audit log（更新元數據）
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_transcription_operation(
            request=request,
            action="update_metadata",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"更新任務名稱：{updates.get('custom_name')}"
        )
    except Exception as e:
        log.warning("transcription.audit_log.failed", action="update_metadata", error=str(e))

    return {
        "message": "任務名稱已更新",
        "task_id": task_id,
        "custom_name": updates.get("custom_name")
    }


@router.put("/{task_id}/speaker-names")
async def update_speaker_names(
    task_id: str,
    body: SpeakerNamesUpdate,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新講者名稱對應

    Args:
        task_id: 任務 ID
        body: 講者代碼與自定義名稱的對應字典 {"SPEAKER_00": "張三", "SPEAKER_01": "李四"}
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在、無權訪問或更新失敗
    """
    speaker_names = body.root

    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    # 更新資料庫
    success = await task_repo.update(task_id, {"speaker_names": speaker_names})

    if not success:
        raise api_error("TRANSCRIPTION_SPEAKER_NAMES_UPDATE_FAILED", "Failed to update speaker names", status.HTTP_500_INTERNAL_SERVER_ERROR)

    log.info("task.speaker_names.updated", task_id=task_id, speaker_names=speaker_names)

    return {
        "message": "講者名稱已更新",
        "task_id": task_id,
        "speaker_names": speaker_names
    }


@router.put("/{task_id}/subtitle-settings")
async def update_subtitle_settings(
    task_id: str,
    settings: dict,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新字幕模式設定（疏密度等）

    Args:
        task_id: 任務 ID
        settings: 字幕設定 {"density_threshold": 3.0}
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        更新結果

    Raises:
        HTTPException: 任務不存在、無權訪問或更新失敗
    """
    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise api_error("TRANSCRIPTION_TASK_NOT_FOUND", "Task not found or access denied", status.HTTP_404_NOT_FOUND)

    # 準備更新數據
    subtitle_settings = task.get("subtitle_settings", {})

    # 更新 density_threshold
    if "density_threshold" in settings:
        density = settings["density_threshold"]
        # 驗證範圍
        if not isinstance(density, (int, float)) or density < 0 or density > 180:
            raise api_error("TRANSCRIPTION_INVALID_DENSITY_THRESHOLD", "density_threshold must be a number between 0 and 180", status.HTTP_400_BAD_REQUEST)
        subtitle_settings["density_threshold"] = float(density)

    # 更新資料庫
    success = await task_repo.update(task_id, {"subtitle_settings": subtitle_settings})

    if not success:
        raise api_error("TRANSCRIPTION_SUBTITLE_SETTINGS_UPDATE_FAILED", "Failed to update subtitle settings", status.HTTP_500_INTERNAL_SERVER_ERROR)

    log.info("task.subtitle_settings.updated", task_id=task_id, subtitle_settings=subtitle_settings)

    return {
        "message": "字幕設定已更新",
        "task_id": task_id,
        "subtitle_settings": subtitle_settings
    }


@router.post("/batch")
async def create_batch_transcriptions(
    request: Request,
    files: Optional[List[UploadFile]] = File(None, description="多個音檔（最多10個）"),
    default_config: str = Form(..., description="預設配置 JSON 字串"),
    overrides: str = Form("{}", description="單檔覆蓋設定 JSON 字串，格式：{索引: {tags, customName}}"),
    upload_ids: Optional[str] = Form(None, description="分片上傳的 upload_id JSON 陣列，格式：{索引: upload_id}"),
    ui_language: Optional[str] = Form(None, description="使用者介面語言（用於自動偵測中文時判斷繁簡體）"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database),
    intake_service: TranscriptionIntakeService = Depends(get_intake_service),
):
    """批次建立轉錄任務"""
    # ── 方案功能檢查：批次上傳僅 Basic 以上方案可用 ──
    # 強制做在後端，避免 free 使用者繞過前端 UI 直接呼叫此 API。
    # current_user 來自 JWT、為效能不含 quota（dependencies.py）；feature gating 必須
    # 用 DB 的完整 user（含 quota.features），否則 has_feature 永遠 fallback 成 free → 連
    # Basic 以上也被誤擋 403。load 不到（理論上不會）視為無權限，fail-closed。
    full_user = await UserRepository(db).get_by_id(str(current_user["_id"]))
    if not has_feature(full_user or {}, "batch_operations"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FEATURE_NOT_AVAILABLE",
                "feature": "batch_operations",
                "message": "批次上傳為 Basic 以上方案功能，請升級方案後使用",
            },
        )

    # ── 解析 upload_ids ──
    chunked_uploads_map = {}
    if upload_ids:
        try:
            chunked_uploads_map = json.loads(upload_ids)
        except json.JSONDecodeError:
            raise api_error("TRANSCRIPTION_INVALID_UPLOAD_IDS", "Invalid upload_ids format", status.HTTP_400_BAD_REQUEST)

    if files is None:
        files = []

    total_files = len(files) + len(chunked_uploads_map)
    MAX_BATCH_FILES = 10
    if total_files > MAX_BATCH_FILES:
        raise api_error("TRANSCRIPTION_BATCH_TOO_MANY_FILES", "Batch upload supports at most {max} files, you provided {provided}", status.HTTP_400_BAD_REQUEST, max=MAX_BATCH_FILES, provided=total_files)
    if total_files == 0:
        raise api_error("TRANSCRIPTION_BATCH_NO_FILES", "Please upload at least one file", status.HTTP_400_BAD_REQUEST)

    # ── 解析配置 ──
    try:
        config = json.loads(default_config)
    except json.JSONDecodeError:
        raise api_error("TRANSCRIPTION_INVALID_DEFAULT_CONFIG", "Invalid default_config format, must be valid JSON", status.HTTP_400_BAD_REQUEST)
    try:
        file_overrides = json.loads(overrides)
    except json.JSONDecodeError:
        raise api_error("TRANSCRIPTION_INVALID_OVERRIDES", "Invalid overrides format, must be valid JSON", status.HTTP_400_BAD_REQUEST)

    task_type = config.get("taskType", "paragraph")
    diarize = config.get("diarize", True)
    max_speakers = config.get("maxSpeakers")
    language = config.get("language", "auto")
    default_tags = config.get("tags", [])

    _validate_create_params(task_type, 10, max_speakers, language, "gemini", None)

    punct_provider = "none" if task_type == "subtitle" else "gemini"

    if diarize and not is_aws() and not _diarization_processor:
        raise api_error("TRANSCRIPTION_DIARIZATION_UNAVAILABLE", "Speaker diarization feature is not enabled", status.HTTP_400_BAD_REQUEST)

    intake_service.set_diarization_available(bool(_diarization_processor))

    # ── 建立處理列表 ──
    from .uploads import consume_upload

    _batch_items = []
    for i, uf in enumerate(files):
        _batch_items.append((i, uf, None))
    user_id_str = str(current_user["_id"])
    for str_idx, uid in chunked_uploads_map.items():
        global_idx = int(str_idx)
        meta = await consume_upload(uid, user_id_str)
        _batch_items.append((global_idx, None, meta))  # meta=None 代表 consume 失敗
    _batch_items.sort(key=lambda x: x[0])

    # ── 逐檔呼叫 intake() ──
    batch_id = str(uuid.uuid4())
    results = []
    created_count = 0
    failed_count = 0

    for idx, upload_file, chunked_meta in _batch_items:
        display_name = upload_file.filename if upload_file else (chunked_meta["filename"] if chunked_meta else "unknown")
        file_result = {"index": idx, "filename": display_name, "task_id": None, "status": "pending", "error": None, "queue_position": None}
        temp_dir = None

        try:
            if chunked_meta is None and upload_file is None:
                raise ValueError("upload_id 無效或尚未完成組裝")

            if chunked_meta:
                temp_dir = chunked_meta["temp_dir"]
                file_path = chunked_meta["assembled_path"]
                original_filename = chunked_meta["filename"]
            else:
                validate_filename_extension(upload_file.filename)
                temp_dir = get_temp_dir()
                suffix = Path(upload_file.filename).suffix
                file_path = temp_dir / f"input{suffix}"
                await _stream_upload_to(upload_file, file_path)
                validate_magic_bytes(file_path)
                original_filename = upload_file.filename

            override = file_overrides.get(str(idx), {})
            file_tags = override.get("tags", default_tags.copy())
            custom_name = override.get("customName", None)

            result = await intake_service.intake(
                user_id=str(current_user["_id"]),
                user_email=current_user["email"],
                file_path=file_path,
                filename=original_filename,
                config=IntakeConfig(
                    task_type=task_type,
                    punct_provider=punct_provider,
                    chunk_audio=True,
                    chunk_minutes=10,
                    diarize=diarize,
                    max_speakers=max_speakers,
                    language=language,
                    ui_language=ui_language,
                    tags=file_tags,
                    custom_name=custom_name,
                    batch_id=batch_id,
                ),
                temp_dir=temp_dir,
            )

            file_result["task_id"] = result.task_id
            file_result["status"] = result.status
            file_result["queue_position"] = result.queue_position
            created_count += 1
            log.info("task.batch.created", index=idx + 1, total=total_files, filename=original_filename, task_id=result.task_id, status=result.status)

        except HTTPException as e:
            file_result["status"] = "failed"
            file_result["error"] = e.detail
            failed_count += 1
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            log.error("task.batch.failed", index=idx + 1, total=total_files, filename=display_name, error=e.detail, exc_info=True)
        except Exception as e:
            file_result["status"] = "failed"
            file_result["error"] = str(e)
            failed_count += 1
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            log.error("task.batch.failed", index=idx + 1, total=total_files, filename=display_name, error=str(e), exc_info=True)

        results.append(file_result)

    # ── Audit log ──
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_task_operation(
            request=request,
            action="batch_create",
            user_id=str(current_user["_id"]),
            task_id=batch_id,
            status_code=200,
            message=f"批次建立 {created_count} 個轉錄任務（失敗 {failed_count} 個）",
            request_body={"batch_id": batch_id, "total": total_files, "created": created_count, "failed": failed_count, "task_type": task_type, "diarize": diarize}
        )
    except Exception as e:
        log.warning("transcription.audit_log.failed", action="batch_create", error=str(e))

    return {"batch_id": batch_id, "total": total_files, "created": created_count, "failed": failed_count, "tasks": results}
