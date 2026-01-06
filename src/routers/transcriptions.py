"""轉錄管理路由"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone
import tempfile
import uuid
import json
import shutil
import mimetypes

from ..auth.dependencies import get_current_user, check_quota
from ..database.mongodb import get_database
from ..database.repositories.task_repo import TaskRepository
from ..services.task_service import TaskService
from ..services.transcription_service import TranscriptionService
from ..services.utils.whisper_processor import WhisperProcessor
from ..services.utils.punctuation_processor import PunctuationProcessor
from ..services.utils.diarization_processor import DiarizationProcessor


router = APIRouter(prefix="/transcriptions", tags=["Transcriptions"])


# 全域服務單例（在啟動時初始化）
_whisper_processor: Optional[WhisperProcessor] = None
_punctuation_processor: Optional[PunctuationProcessor] = None
_diarization_processor: Optional[DiarizationProcessor] = None
_transcription_service: Optional[TranscriptionService] = None


def init_transcription_service(
    whisper_model,
    task_service: TaskService,
    model_name: str = "medium",
    diarization_pipeline=None,
    executor=None,
    output_dir: Optional[Path] = None
):
    """初始化全域 TranscriptionService 單例

    Args:
        whisper_model: Whisper 模型實例
        task_service: TaskService 實例
        model_name: 模型名稱（用於 ProcessPoolExecutor 中重新載入模型）
        diarization_pipeline: Diarization pipeline（可選）
        executor: 線程池執行器（可選）
        output_dir: 輸出目錄（可選）
    """
    global _whisper_processor, _punctuation_processor, _diarization_processor, _transcription_service

    # 初始化處理器
    _whisper_processor = WhisperProcessor(whisper_model, model_name)
    _punctuation_processor = PunctuationProcessor()
    _diarization_processor = DiarizationProcessor(diarization_pipeline) if diarization_pipeline else None

    # 初始化 TranscriptionService
    _transcription_service = TranscriptionService(
        task_service=task_service,
        whisper_processor=_whisper_processor,
        punctuation_processor=_punctuation_processor,
        diarization_processor=_diarization_processor,
        executor=executor,
        output_dir=output_dir
    )

    return _transcription_service


def get_transcription_service() -> TranscriptionService:
    """獲取 TranscriptionService 實例

    Returns:
        TranscriptionService 實例

    Raises:
        RuntimeError: 如果服務尚未初始化
    """
    if _transcription_service is None:
        raise RuntimeError("TranscriptionService 尚未初始化")
    return _transcription_service


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


@router.post("")
async def create_transcription(
    request: Request,
    file: UploadFile = File(..., description="音檔 (支援 mp3/m4a/wav/mp4 等格式)"),
    task_type: str = Form("paragraph", description="任務類型 (paragraph/subtitle)"),
    punct_provider: str = Form("gemini", description="標點提供者 (openai/gemini/none)"),
    chunk_audio: bool = Form(True, description="是否使用分段模式"),
    chunk_minutes: int = Form(10, description="分段長度（分鐘）"),
    diarize: bool = Form(False, description="是否啟用說話者辨識"),
    max_speakers: Optional[int] = Form(None, description="最大講者人數（可選，2-10）"),
    language: str = Form("zh", description="轉錄語言 (zh/en/ja/ko/auto)"),
    tags: Optional[str] = Form(None, description="標籤（JSON 陣列字串）"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """建立轉錄任務

    上傳音檔進行轉錄（異步模式）
    立即返回任務 ID，轉錄在背景執行

    Args:
        file: 音檔檔案
        task_type: 任務類型 (paragraph=段落/subtitle=字幕)
        punct_provider: 標點提供者 (openai/gemini/none)
        chunk_audio: 是否使用分段模式
        chunk_minutes: 分段長度（分鐘）
        diarize: 是否啟用說話者辨識
        max_speakers: 最大講者人數（2-10）
        language: 轉錄語言
        tags: 標籤
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        任務資訊

    Raises:
        HTTPException: 服務未就緒或參數錯誤
    """
    # 驗證任務類型
    if task_type not in ["paragraph", "subtitle"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任務類型必須是 'paragraph' 或 'subtitle'"
        )

    # 字幕類型強制不使用標點符號
    if task_type == "subtitle":
        punct_provider = "none"
        print(f"ℹ️  字幕模式：已自動停用標點符號處理")
    # 獲取服務
    try:
        transcription_service = get_transcription_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="轉錄服務尚未初始化"
        )

    # 生成任務 ID
    task_id = str(uuid.uuid4())

    # 建立臨時目錄並保存上傳的檔案
    temp_dir = Path(tempfile.mkdtemp())
    file_suffix = Path(file.filename).suffix
    temp_audio = temp_dir / f"input{file_suffix}"

    try:
        # 保存上傳的檔案
        with temp_audio.open("wb") as f:
            content = await file.read()
            f.write(content)

        print(f"📁 收到檔案：{file.filename} ({len(content) / 1024 / 1024:.2f} MB)")

        # 獲取音檔時長
        from src.services.audio_service import AudioService
        audio_service = AudioService()
        try:
            audio_duration_ms = audio_service.get_audio_duration(temp_audio)
            audio_duration_seconds = audio_duration_ms / 1000.0
            print(f"⏱️ 音檔時長：{audio_duration_seconds:.2f} 秒")
        except Exception as e:
            print(f"⚠️ 獲取音檔時長失敗：{e}")
            shutil.rmtree(temp_dir)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"無法讀取音檔資訊：{str(e)}"
            )

        # 獲取完整用戶資料（包含配額）
        from src.database.repositories.user_repo import UserRepository
        user_repo = UserRepository(db)
        full_user_data = await user_repo.get_by_id(str(current_user["_id"]))

        if not full_user_data:
            shutil.rmtree(temp_dir)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="無法獲取用戶資訊"
            )

        # 檢查轉錄配額
        from src.auth.quota import QuotaManager
        try:
            await QuotaManager.check_transcription_quota(
                full_user_data,
                audio_duration_seconds
            )
        except HTTPException as quota_error:
            # 清理臨時檔案
            shutil.rmtree(temp_dir)
            # 拋出配額不足異常
            raise quota_error

        # 檢查 diarization 可用性
        if diarize and not _diarization_processor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Speaker diarization 功能未啟用。請設定 HF_TOKEN 環境變數並重啟服務。"
            )

        # 檢查當前處理中的任務數量（限流機制）
        MAX_CONCURRENT_TASKS = 2  # 最多同時處理 2 個任務
        processing_count = await transcription_service.task_service.count_processing_tasks()
        pending_count = await transcription_service.task_service.count_pending_tasks()

        # 判斷是否需要排隊
        should_queue = processing_count >= MAX_CONCURRENT_TASKS

        if should_queue:
            print(f"⚠️  系統忙碌中（{processing_count} 個任務處理中，{pending_count} 個任務排隊中），新任務加入隊列")

        # 解析標籤
        task_tags = []
        if tags:
            try:
                task_tags = json.loads(tags)
            except:
                task_tags = []

        # 創建任務記錄
        from datetime import datetime, timezone, timedelta
        TZ_UTC8 = timezone(timedelta(hours=8))

        def get_current_time():
            return datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")

        current_time = get_current_time()
        task_data = {
            "_id": task_id,
            "task_id": task_id,

            # 任務類型（新增）
            "task_type": task_type,

            # 使用者資訊
            "user": {
                "user_id": str(current_user["_id"]),
                "user_email": current_user["email"]
            },

            # 檔案資訊
            "file": {
                "filename": file.filename,
                "size_mb": round(len(content) / 1024 / 1024, 2)
            },

            # 轉錄配置
            "config": {
                "punct_provider": punct_provider,
                "chunk_audio": chunk_audio,
                "chunk_minutes": chunk_minutes,
                "diarize": diarize,
                "max_speakers": max_speakers,
                "language": language
            },

            # 狀態
            "status": "pending",

            # 統計資訊
            "stats": {
                "audio_duration_seconds": audio_duration_seconds,
            },

            # 使用者設定與標籤
            "tags": task_tags,
            # ⚠️ keep_audio 默認為 False
            # 注意：False 不代表不保存音檔！所有音檔都會被保存到 uploads/
            # False 的意思是「可以被自動清理機制刪除」
            # True 的意思是「用戶手動勾選保留，不會被自動刪除」
            "keep_audio": False,

            # 講者名稱對應（用於字幕模式）
            "speaker_names": {},

            # 時間戳記
            "timestamps": {
                "created_at": current_time,
                "updated_at": current_time,
            }
        }

        # 保存到資料庫
        task_repo = TaskRepository(db)
        await task_repo.create(task_data)

        # 初始化記憶體狀態（確保 SSE 能立即讀取到正確狀態）
        transcription_service.task_service.update_memory_state(task_id, {
            "status": "pending",
            "progress": "等待處理中..."
        })

        # 記錄臨時目錄
        transcription_service.task_service.set_temp_dir(task_id, temp_dir)

        # 根據系統負載決定是否立即啟動或加入隊列
        if not should_queue:
            # 系統空閒，立即啟動轉錄（異步執行）
            use_punctuation = punct_provider != "none"
            language_code = None if language == "auto" else language

            # ✅ 關鍵修復：立即更新狀態為 processing，防止隊列處理器重複啟動
            await task_repo.update(task_id, {
                "status": "processing",
                "updated_at": datetime.now(timezone.utc)
            })
            transcription_service.task_service.update_memory_state(task_id, {
                "status": "processing",
                "progress": "準備開始轉錄..."
            })

            await transcription_service.start_transcription(
                task_id=task_id,
                audio_file_path=temp_audio,
                language=language_code,
                use_chunking=chunk_audio,
                use_punctuation=use_punctuation,
                punctuation_provider=punct_provider,
                use_diarization=diarize,
                max_speakers=max_speakers
            )

            print(f"✅ 任務 {task_id} 已建立，正在背景執行轉錄...")
        else:
            # 系統忙碌，加入隊列（保持 pending 狀態）
            print(f"📋 任務 {task_id} 已加入隊列，等待處理...（隊列中有 {pending_count + 1} 個任務）")

        # 記錄 audit log（創建轉錄任務）
        try:
            from ..utils.audit_logger import get_audit_logger
            audit_logger = get_audit_logger()
            await audit_logger.log_task_operation(
                request=request,
                action="create",
                user_id=str(current_user["_id"]),
                task_id=task_id,
                status_code=200,
                message=f"創建轉錄任務：{file.filename}",
                request_body={
                    "filename": file.filename,
                    "size_mb": round(len(content) / 1024 / 1024, 2),
                    "punct_provider": punct_provider,
                    "chunk_audio": chunk_audio,
                    "diarize": diarize,
                    "language": language
                }
            )
        except Exception as e:
            print(f"⚠️ 記錄 audit log 失敗：{e}")

        # 返回結果（根據是否排隊調整消息）
        if should_queue:
            message = f"轉錄任務已加入隊列，目前有 {processing_count} 個任務處理中，{pending_count + 1} 個任務等待中"
            queue_position = pending_count + 1
        else:
            message = "轉錄任務已建立，正在背景處理"
            queue_position = 0

        return {
            "task_id": task_id,
            "status": "pending",
            "message": message,
            "queued": should_queue,
            "queue_position": queue_position,
            "file": {
                "filename": file.filename,
                "size_mb": round(len(content) / 1024 / 1024, 2)
            },
            "config": {
                "punct_provider": punct_provider,
                "chunk_audio": chunk_audio,
                "language": language
            }
        }

    except HTTPException:
        # 清理臨時檔案
        if temp_dir.exists():
            import shutil
            shutil.rmtree(temp_dir)
        raise
    except Exception as e:
        # 清理臨時檔案
        if temp_dir.exists():
            import shutil
            shutil.rmtree(temp_dir)
        print(f"❌ 建立轉錄任務失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立轉錄任務失敗：{str(e)}"
        )


@router.get("/{task_id}/download")
async def download_transcription(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """下載轉錄結果

    Args:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    if task["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"任務尚未完成（當前狀態：{task['status']}）"
        )

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
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="轉錄內容不存在"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="轉錄內容不存在"
            )
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

    return StreamingResponse(
        BytesIO(content.encode('utf-8')),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.get("/{task_id}/audio")
async def download_audio(
    task_id: str,
    token: Optional[str] = Query(None, description="JWT access token (查詢參數，用於 audio 元素)"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db = Depends(get_database)
):
    """下載原始音檔

    支持兩種認證方式：
    1. Authorization header (Bearer token) - 用於 API 調用
    2. 查詢參數 token - 用於 HTML audio 元素（因為 audio 元素不支持自定義 headers）

    Args:
        task_id: 任務 ID
        token: JWT token (query parameter)
        credentials: JWT token from Authorization header
        db: 資料庫實例

    Returns:
        音檔檔案

    Raises:
        HTTPException: 任務不存在、無權訪問或音檔不存在
    """
    # 優先使用 header 中的 token，其次使用查詢參數
    access_token = None
    if credentials:
        access_token = credentials.credentials
    elif token:
        access_token = token
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要認證：請提供 Authorization header 或 token 查詢參數"
        )

    # 驗證 token 並獲取用戶資訊
    from ..auth.jwt_handler import verify_token
    token_data = verify_token(access_token, "access")

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的認證令牌"
        )

    user_id = token_data.user_id
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的認證令牌"
        )

    # 從資料庫獲取任務
    task_repo = TaskRepository(db)
    task = await task_repo.get_by_id_and_user(task_id, user_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    audio_file_path = get_task_field(task, "audio_file")
    if not audio_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音檔不存在（可能已被刪除）"
        )

    audio_file = Path(audio_file_path)
    if not audio_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音檔不存在"
        )

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
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    if task["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"任務尚未完成（當前狀態：{task['status']}）"
        )

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
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"讀取 segments 檔案失敗：{str(e)}"
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Segments 不存在"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segments 不存在"
            )
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
    task_id: str,
    content: dict,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新轉錄文字內容和 segments

    Args:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    if task["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"只能更新已完成任務的內容（當前狀態：{task['status']}）"
        )

    # 更新 MongoDB collections（新方式）
    from src.database.repositories.transcription_repo import TranscriptionRepository
    from src.database.repositories.segment_repo import SegmentRepository

    try:
        # 1. 更新 transcriptions collection
        new_text = content.get("text", "")
        if new_text:
            transcription_repo = TranscriptionRepository(db)

            exists = await transcription_repo.exists(task_id)
            if exists:
                await transcription_repo.update(task_id, new_text)
                print(f"✅ 已更新 transcriptions collection (task_id: {task_id})")
            else:
                await transcription_repo.create(task_id, new_text)
                print(f"✅ 已建立 transcriptions collection (task_id: {task_id})")

        # 2. 更新 segments collection
        new_segments = content.get("segments")
        if new_segments is not None:
            segment_repo = SegmentRepository(db)

            exists = await segment_repo.exists(task_id)
            if exists:
                await segment_repo.update(task_id, new_segments)
                print(f"✅ 已更新 segments collection (task_id: {task_id}, count: {len(new_segments)})")
            else:
                await segment_repo.create(task_id, new_segments)
                print(f"✅ 已建立 segments collection (task_id: {task_id}, count: {len(new_segments)})")

        response_message = "轉錄內容已更新"
        if new_segments is not None:
            response_message = "轉錄內容和字幕已更新"

        return {
            "message": response_message,
            "task_id": task_id,
            "segments_updated": new_segments is not None
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新轉錄內容失敗：{str(e)}"
        )


@router.put("/{task_id}/metadata")
async def update_metadata(
    task_id: str,
    metadata: dict,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新任務元數據（自訂名稱）

    Args:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 準備更新數據
    updates = {}
    # 支援 custom_name 或 title（向後兼容）
    if "custom_name" in metadata:
        updates["custom_name"] = metadata["custom_name"]
    elif "title" in metadata:
        updates["custom_name"] = metadata["title"]

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="沒有提供需要更新的元數據"
        )

    # 更新資料庫
    success = await task_repo.update(task_id, updates)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新元數據失敗"
        )

    print(f"✅ 已更新任務 {task_id} 的元數據: {updates}")

    return {
        "message": "任務名稱已更新",
        "task_id": task_id,
        "custom_name": updates.get("custom_name")
    }


@router.put("/{task_id}/speaker-names")
async def update_speaker_names(
    task_id: str,
    speaker_names: dict,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """更新講者名稱對應

    Args:
        task_id: 任務 ID
        speaker_names: 講者代碼與自定義名稱的對應字典 {"SPEAKER_00": "張三", "SPEAKER_01": "李四"}
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 更新資料庫
    success = await task_repo.update(task_id, {"speaker_names": speaker_names})

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新講者名稱失敗"
        )

    print(f"✅ 已更新任務 {task_id} 的講者名稱: {speaker_names}")

    return {
        "message": "講者名稱已更新",
        "task_id": task_id,
        "speaker_names": speaker_names
    }
