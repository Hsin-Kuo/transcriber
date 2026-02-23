"""轉錄管理路由"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List
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
from ..database.repositories.tag_repo import TagRepository
from ..services.task_service import TaskService
from ..services.transcription_service import TranscriptionService
from ..services.tag_service import TagService
from ..services.utils.whisper_processor import WhisperProcessor
from ..services.utils.punctuation_processor import PunctuationProcessor
from ..services.utils.diarization_processor import DiarizationProcessor
from ..utils.storage_service import is_aws
from ..utils.config_loader import get_parameter
import os
import asyncio


def _get_sync_db():
    """取得同步 MongoDB 連線（用於背景任務，不依賴 FastAPI DI）"""
    from pymongo import MongoClient
    mongodb_url = get_parameter("/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
    client = MongoClient(mongodb_url, serverSelectionTimeoutMS=5000)
    return client, client[db_name]


def _sign_sqs_message(payload: dict) -> dict:
    """為 SQS 訊息添加 HMAC 簽名

    Args:
        payload: 訊息內容

    Returns:
        添加了 _signature 欄位的訊息
    """
    worker_secret = get_parameter("/transcriber/worker-secret", fallback_env="WORKER_SECRET", default="")
    if not worker_secret:
        return payload  # 未設定密鑰時不簽名

    import hmac
    import hashlib

    # 計算簽名（不含 _signature 欄位）
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        worker_secret.encode(),
        payload_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return {**payload, "_signature": signature}


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
    executor=None
):
    """初始化全域 TranscriptionService 單例

    Args:
        whisper_model: Whisper 模型實例
        task_service: TaskService 實例
        model_name: 模型名稱（用於 ProcessPoolExecutor 中重新載入模型）
        diarization_pipeline: Diarization pipeline（可選）
        executor: 線程池執行器（可選）
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
        executor=executor
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
    language: str = Form("zh", description="轉錄語言 (zh/en/ja/ko/auto)"),
    tags: Optional[str] = Form(None, description="標籤（JSON 陣列字串）"),
    upload_id: Optional[str] = Form(None, description="分片上傳完成後的 upload_id（替代直接上傳檔案）"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """建立轉錄任務（支援單檔或多檔合併）

    上傳音檔進行轉錄（異步模式）
    立即返回任務 ID，轉錄在背景執行

    Args:
        files: 多個音檔（合併模式）
        file: 單個音檔（單檔模式）
        merge_files: 是否為合併模式
        custom_name: 自訂任務名稱
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
    # ── 分片上傳模式：從已組裝的檔案讀取 ──
    use_chunked_upload = False
    chunked_temp_dir = None
    chunked_audio_path = None

    if upload_id:
        from .uploads import get_upload_meta, remove_upload
        meta = get_upload_meta(upload_id)
        if not meta:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload_id 無效或尚未完成組裝")
        if meta["user_id"] != str(current_user["_id"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "無權使用此上傳")
        use_chunked_upload = True
        chunked_temp_dir = meta["temp_dir"]
        chunked_audio_path = meta["assembled_path"]
        # 從 active_uploads 移除（後續由本函數管理 temp_dir 生命週期）
        remove_upload(upload_id)

    # 處理檔案參數
    if use_chunked_upload:
        uploaded_files = []  # 不需要 UploadFile，後面會直接使用 chunked_audio_path
    elif merge_files and files and len(files) > 0:
        # 合併模式：多檔案
        if len(files) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="合併模式至少需要2個檔案"
            )
        uploaded_files = files
    elif file:
        # 單檔模式
        uploaded_files = [file]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供音檔或 upload_id"
        )

    # 檢查檔案總大小（注意：UploadFile.size 可能為 None）
    if not use_chunked_upload:
        total_size = sum(f.size or 0 for f in uploaded_files)
        MAX_TOTAL_SIZE = 500 * 1024 * 1024  # 500MB
        if total_size > 0 and total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="檔案總大小超過限制（最大500MB）"
            )

    # 驗證任務類型
    if task_type not in ["paragraph", "subtitle"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任務類型必須是 'paragraph' 或 'subtitle'"
        )

    # 驗證 chunk_minutes（1-120 分鐘）
    if chunk_minutes < 1 or chunk_minutes > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="分段長度必須在 1-120 分鐘之間"
        )

    # 驗證 max_speakers（2-10，若有提供）
    if max_speakers is not None and (max_speakers < 2 or max_speakers > 10):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="最大講者人數必須在 2-10 之間"
        )

    # 驗證 language（白名單）
    ALLOWED_LANGUAGES = {"zh", "en", "ja", "ko", "auto"}
    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的語言：{language}，可選：{', '.join(ALLOWED_LANGUAGES)}"
        )

    # 驗證 punct_provider（白名單）
    ALLOWED_PUNCT_PROVIDERS = {"openai", "gemini", "none"}
    if punct_provider not in ALLOWED_PUNCT_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的標點提供者：{punct_provider}"
        )

    # 驗證 custom_name（長度和字元安全性）
    if custom_name:
        if len(custom_name) > 255:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="自訂名稱過長（最多 255 字元）"
            )
        # 移除可能導致路徑穿越的字元
        custom_name = custom_name.replace("/", "").replace("\\", "").replace("..", "")

    # 字幕類型強制不使用標點符號
    if task_type == "subtitle":
        punct_provider = "none"
        print(f"ℹ️  字幕模式：已自動停用標點符號處理")
    # 獲取服務（AWS 模式下 TranscriptionService 可能為 None）
    transcription_service = _transcription_service
    if not is_aws() and transcription_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="轉錄服務尚未初始化"
        )

    # 生成任務 ID
    task_id = str(uuid.uuid4())

    # 建立臨時目錄（分片上傳模式直接複用已有的 temp_dir）
    if use_chunked_upload:
        temp_dir = chunked_temp_dir
    else:
        temp_dir = Path(tempfile.mkdtemp())

    try:
        # 如果是多檔案，先合併
        # 導入 AudioService（用於合併音檔和獲取時長）
        from src.services.audio_service import AudioService

        if use_chunked_upload:
            # ── 分片上傳：檔案已組裝好，直接使用 ──
            temp_audio = chunked_audio_path
            original_filename = custom_name.strip() if custom_name and custom_name.strip() else chunked_audio_path.name
            print(f"📁 分片上傳模式：使用已組裝檔案 {chunked_audio_path.name} ({chunked_audio_path.stat().st_size / 1024 / 1024:.2f} MB)")
        elif len(uploaded_files) > 1:
            print(f"🔄 合併模式：{len(uploaded_files)} 個檔案")

            # 保存上傳的檔案到臨時目錄
            saved_files = []
            for idx, upload_file in enumerate(uploaded_files):
                file_suffix = Path(upload_file.filename).suffix
                temp_path = temp_dir / f"input_{idx}{file_suffix}"

                with temp_path.open("wb") as f:
                    content = await upload_file.read()
                    f.write(content)

                saved_files.append(temp_path)
                print(f"  📁 {idx + 1}. {upload_file.filename}")

            # 合併音檔到臨時目錄（固定MP3格式：16kHz, mono, 192kbps）
            audio_service = AudioService()

            # ⭐ 使用唯一檔名避免多用戶衝突
            unique_id = str(uuid.uuid4())[:8]  # 使用前8個字符
            merged_filename = f"merged_{unique_id}.mp3"

            # 輸出路徑在臨時目錄內
            merged_output_path = temp_dir / merged_filename
            merged_audio_path = audio_service.merge_audio_files(
                saved_files,
                output_path=merged_output_path
            )

            # 使用合併後的音檔作為 temp_audio
            temp_audio = merged_audio_path

            # ⭐ 使用用戶自訂的任務名稱
            if custom_name and custom_name.strip():
                original_filename = f"{custom_name.strip()}.mp3"
            else:
                # 預設使用第一個檔案的檔名（去掉副檔名）
                first_filename = uploaded_files[0].filename
                original_filename = first_filename.rsplit('.', 1)[0] + '.mp3'

            print(f"✅ 合併完成：{merged_audio_path}")
            print(f"   任務名稱：{original_filename}")

            # ⚠️ 重要：合併後的音檔會經歷與單檔相同的生命週期：
            # 1. 轉錄成功 → 移動到 uploads/{task_id}.mp3
            # 2. 轉錄失敗/取消 → 隨臨時目錄一起刪除
        else:
            # 單檔案模式（現有邏輯）
            upload_file = uploaded_files[0]
            file_suffix = Path(upload_file.filename).suffix
            temp_audio = temp_dir / f"input{file_suffix}"

            with temp_audio.open("wb") as f:
                content = await upload_file.read()
                f.write(content)

            original_filename = upload_file.filename
            print(f"📁 收到檔案：{upload_file.filename} ({len(content) / 1024 / 1024:.2f} MB)")

        # 獲取音檔時長和大小
        audio_service = AudioService()
        try:
            audio_duration_ms = audio_service.get_audio_duration(temp_audio)
            audio_duration_seconds = audio_duration_ms / 1000.0
            audio_size_mb = round(temp_audio.stat().st_size / 1024 / 1024, 2)
            print(f"⏱️ 音檔時長：{audio_duration_seconds:.2f} 秒")
            print(f"📦 音檔大小：{audio_size_mb} MB")
        except Exception as e:
            print(f"⚠️ 獲取音檔資訊失敗：{e}")
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

        # 檢查 diarization 可用性（僅在本地模式下檢查，AWS 模式由 GPU Worker 處理）
        if diarize and not is_aws() and not _diarization_processor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Speaker diarization 功能未啟用。請設定 HF_TOKEN 環境變數並重啟服務。"
            )

        # 檢查當前處理中的任務數量（限流機制，僅本地模式）
        should_queue = False
        if not is_aws() and transcription_service:
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

        # 自動為新標籤建立 tags 集合記錄
        if task_tags:
            try:
                tag_repo = TagRepository(db)
                tag_service = TagService(tag_repo, TaskRepository(db))
                user_id = str(current_user["_id"])
                existing_tags = await tag_service.get_all_tags(user_id)
                existing_names = {t["name"] for t in existing_tags}
                for tag_name in task_tags:
                    if tag_name and tag_name not in existing_names:
                        try:
                            await tag_service.create_tag(user_id=user_id, name=tag_name)
                        except (ValueError, Exception):
                            pass
            except Exception as e:
                print(f"⚠️ 上傳時自動建立標籤記錄失敗（不影響任務建立）：{e}")

        # 創建任務記錄
        from ..utils.time_utils import get_utc_timestamp

        current_time = get_utc_timestamp()
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
                "filename": original_filename,
                "size_mb": audio_size_mb
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

            # 字幕模式設定
            "subtitle_settings": {
                "density_threshold": 3.0,  # 疏密度閾值（秒），範圍 0-120
            },

            # 時間戳記
            "timestamps": {
                "created_at": current_time,
                "updated_at": current_time,
            }
        }

        # 保存到資料庫
        task_repo = TaskRepository(db)
        await task_repo.create(task_data)

        if is_aws():
            # ===== AWS 模式：背景上傳 S3 + 發送 SQS =====
            from ..utils.storage_service import save_audio
            import boto3

            # 預先捕獲 SQS 配置
            sqs_queue_url = os.getenv("SQS_QUEUE_URL", "")
            sqs_region = os.getenv("S3_REGION", "ap-northeast-1")
            use_punctuation = punct_provider != "none"
            language_code = None if language == "auto" else language
            sqs_payload = _sign_sqs_message({
                "task_id": task_id,
                "language": language_code,
                "use_chunking": chunk_audio,
                "use_punctuation": use_punctuation,
                "punctuation_provider": punct_provider,
                "use_diarization": diarize,
                "max_speakers": max_speakers,
            })

            # 捕獲背景任務所需的變數
            _bg_task_id = task_id
            _bg_temp_audio = temp_audio
            _bg_temp_dir = temp_dir

            async def _upload_to_s3_and_notify():
                """背景執行 S3 上傳 + SQS 發送"""
                try:
                    loop = asyncio.get_event_loop()
                    # S3 上傳（blocking I/O）
                    await loop.run_in_executor(None, save_audio, _bg_task_id, _bg_temp_audio)
                    print(f"☁️  音檔已上傳到 S3: uploads/{_bg_task_id}.mp3")

                    # 發送 SQS
                    if sqs_queue_url:
                        def _send_sqs():
                            sqs = boto3.client("sqs", region_name=sqs_region)
                            sqs.send_message(
                                QueueUrl=sqs_queue_url,
                                MessageBody=json.dumps(sqs_payload)
                            )
                        await loop.run_in_executor(None, _send_sqs)
                        print(f"📨 已發送 SQS 訊息: {_bg_task_id}")
                    else:
                        print(f"⚠️  SQS_QUEUE_URL 未設定，任務 {_bg_task_id} 保持 pending 狀態")

                except Exception as e:
                    print(f"❌ S3 上傳失敗: {_bg_task_id}: {e}")
                    try:
                        client, sync_db = _get_sync_db()
                        sync_db.tasks.update_one(
                            {"_id": _bg_task_id},
                            {"$set": {"status": "failed", "error": {"message": f"音檔上傳失敗: {str(e)}"}}}
                        )
                        client.close()
                    except Exception as db_err:
                        print(f"❌ 更新任務狀態失敗: {_bg_task_id}: {db_err}")
                finally:
                    if _bg_temp_dir.exists():
                        shutil.rmtree(_bg_temp_dir)

            # 發射背景任務，不等待
            asyncio.create_task(_upload_to_s3_and_notify())
        else:
            # ===== 本地模式：現有行為 =====
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

                # 立即更新狀態為 processing，防止隊列處理器重複啟動
                await task_repo.update(task_id, {
                    "status": "processing"
                    # updated_at 由 task_repo.update() 自動設置
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
                message=f"創建轉錄任務：{original_filename}",
                request_body={
                    "filename": original_filename,
                    "size_mb": audio_size_mb,
                    "punct_provider": punct_provider,
                    "chunk_audio": chunk_audio,
                    "diarize": diarize,
                    "language": language,
                    "merge_mode": len(uploaded_files) > 1,
                    "file_count": len(uploaded_files)
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
                "filename": original_filename,
                "size_mb": audio_size_mb
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
            shutil.rmtree(temp_dir)
        raise
    except Exception as e:
        # 清理臨時檔案
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        print(f"❌ 建立轉錄任務失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立轉錄任務失敗：{str(e)}"
        )


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

    # 記錄 audit log（下載轉錄結果）
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_task_operation(
            request=request,
            action="view_transcript",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"檢視轉錄結果：{download_filename}"
        )
    except Exception as e:
        print(f"⚠️ 記錄 audit log 失敗：{e}")

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

    if is_aws():
        # AWS 模式：回傳 S3 presigned URL redirect
        from ..utils.storage_service import get_audio_presigned_url, audio_exists, S3_REGION
        from fastapi.responses import RedirectResponse
        from urllib.parse import urlparse

        if not audio_exists(task_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="音檔不存在（可能已被刪除）"
            )

        presigned_url = get_audio_presigned_url(task_id, expires_in=3600)

        # 驗證 presigned URL 指向合法的 S3 域名，防止 open redirect
        parsed = urlparse(presigned_url)
        if not parsed.hostname or not parsed.hostname.endswith(".amazonaws.com"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="產生的下載連結異常"
            )

        return RedirectResponse(url=presigned_url)
    else:
        # 本地模式：回傳 FileResponse
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
    from src.utils.time_utils import get_utc_timestamp

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

        # 3. 更新 tasks collection 的時間戳（task_repo.update 會自動同步 updated_at 和 timestamps.updated_at）
        await task_repo.update(task_id, {})
        print(f"✅ 已更新 tasks 時間戳 (task_id: {task_id})")

        response_message = "轉錄內容已更新"
        if new_segments is not None:
            response_message = "轉錄內容和字幕已更新"

        # 記錄 audit log（更新轉錄內容）
        try:
            from ..utils.audit_logger import get_audit_logger
            audit_logger = get_audit_logger()
            await audit_logger.log_task_operation(
                request=request,
                action="update_content",
                user_id=str(current_user["_id"]),
                task_id=task_id,
                status_code=200,
                message=response_message
            )
        except Exception as e:
            print(f"⚠️ 記錄 audit log 失敗：{e}")

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

    # 記錄 audit log（更新元數據）
    try:
        from ..utils.audit_logger import get_audit_logger
        audit_logger = get_audit_logger()
        await audit_logger.log_task_operation(
            request=request,
            action="update_metadata",
            user_id=str(current_user["_id"]),
            task_id=task_id,
            status_code=200,
            message=f"更新任務名稱：{updates.get('custom_name')}"
        )
    except Exception as e:
        print(f"⚠️ 記錄 audit log 失敗：{e}")

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任務不存在或無權訪問"
        )

    # 準備更新數據
    subtitle_settings = task.get("subtitle_settings", {})

    # 更新 density_threshold
    if "density_threshold" in settings:
        density = settings["density_threshold"]
        # 驗證範圍
        if not isinstance(density, (int, float)) or density < 0 or density > 120:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="density_threshold 必須是 0-120 之間的數字"
            )
        subtitle_settings["density_threshold"] = float(density)

    # 更新資料庫
    success = await task_repo.update(task_id, {"subtitle_settings": subtitle_settings})

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新字幕設定失敗"
        )

    print(f"✅ 已更新任務 {task_id} 的字幕設定: {subtitle_settings}")

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
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """批次建立轉錄任務

    一次上傳多個音檔，建立多個獨立的轉錄任務。
    每個檔案作為獨立任務加入佇列。

    Args:
        files: 多個音檔（最多10個）
        default_config: 預設配置 JSON 字串，包含 taskType, diarize, maxSpeakers, language, tags
        overrides: 單檔覆蓋設定 JSON 字串，格式：{"0": {"tags": [...], "customName": "..."}, ...}
        current_user: 當前用戶
        db: 資料庫實例

    Returns:
        批次建立結果

    Raises:
        HTTPException: 參數錯誤或服務未就緒
    """
    # 解析分片上傳的 upload_ids（格式：{"索引": "upload_id"}）
    chunked_uploads_map = {}
    if upload_ids:
        try:
            chunked_uploads_map = json.loads(upload_ids)
        except json.JSONDecodeError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload_ids 格式錯誤")

    # 確保 files 是 list（可能為 None）
    if files is None:
        files = []

    # 計算總檔案數（直接上傳 + 分片上傳）
    total_files = len(files) + len(chunked_uploads_map)

    # 檢查檔案數量
    MAX_BATCH_FILES = 10
    if total_files > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"批次上傳最多支援 {MAX_BATCH_FILES} 個檔案，您提供了 {total_files} 個"
        )

    if total_files == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請至少上傳一個檔案"
        )

    # 解析配置
    try:
        config = json.loads(default_config)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="default_config 格式錯誤，必須是有效的 JSON"
        )

    try:
        file_overrides = json.loads(overrides)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="overrides 格式錯誤，必須是有效的 JSON"
        )

    # 獲取服務（AWS 模式下 TranscriptionService 可能為 None）
    transcription_service = _transcription_service
    if not is_aws() and transcription_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="轉錄服務尚未初始化"
        )

    # 從配置中提取參數
    task_type = config.get("taskType", "paragraph")
    diarize = config.get("diarize", True)
    max_speakers = config.get("maxSpeakers")
    language = config.get("language", "auto")
    default_tags = config.get("tags", [])

    # 收集所有標籤（default + 各檔案覆蓋的）並自動建立 tags 集合記錄
    all_upload_tags = set(default_tags)
    for override in file_overrides.values():
        if isinstance(override, dict):
            all_upload_tags.update(override.get("tags", []))
    if all_upload_tags:
        try:
            tag_repo = TagRepository(db)
            tag_service = TagService(tag_repo, TaskRepository(db))
            user_id = str(current_user["_id"])
            existing_tags = await tag_service.get_all_tags(user_id)
            existing_names = {t["name"] for t in existing_tags}
            for tag_name in all_upload_tags:
                if tag_name and tag_name not in existing_names:
                    try:
                        await tag_service.create_tag(user_id=user_id, name=tag_name)
                    except (ValueError, Exception):
                        pass
        except Exception as e:
            print(f"⚠️ 批次上傳時自動建立標籤記錄失敗（不影響任務建立）：{e}")

    # 驗證任務類型
    if task_type not in ["paragraph", "subtitle"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任務類型必須是 'paragraph' 或 'subtitle'"
        )

    # 驗證 max_speakers（2-10，若有提供）
    if max_speakers is not None and (max_speakers < 2 or max_speakers > 10):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="最大講者人數必須在 2-10 之間"
        )

    # 驗證 language（白名單）
    ALLOWED_LANGUAGES = {"zh", "en", "ja", "ko", "auto"}
    if language not in ALLOWED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支援的語言：{language}"
        )

    # 字幕類型強制不使用標點符號
    punct_provider = "gemini"
    if task_type == "subtitle":
        punct_provider = "none"

    # 檢查 diarization 可用性（僅在本地模式下檢查，AWS 模式由 GPU Worker 處理）
    if diarize and not is_aws() and not _diarization_processor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Speaker diarization 功能未啟用"
        )

    # 獲取完整用戶資料
    from src.database.repositories.user_repo import UserRepository
    user_repo = UserRepository(db)
    full_user_data = await user_repo.get_by_id(str(current_user["_id"]))

    if not full_user_data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="無法獲取用戶資訊"
        )

    # 導入必要的服務
    from src.services.audio_service import AudioService
    from src.auth.quota import QuotaManager
    from ..utils.time_utils import get_utc_timestamp

    audio_service = AudioService()
    task_repo = TaskRepository(db)

    # 批次結果
    batch_id = str(uuid.uuid4())
    results = []
    created_count = 0
    failed_count = 0

    # 檢查當前處理中的任務數量（僅本地模式）
    processing_count = 0
    pending_count = 0
    if not is_aws() and transcription_service:
        MAX_CONCURRENT_TASKS = 2
        processing_count = await transcription_service.task_service.count_processing_tasks()
        pending_count = await transcription_service.task_service.count_pending_tasks()

    # 建立統一的處理列表：(global_idx, upload_file_or_None, chunked_meta_or_None)
    _batch_items = []
    # 直接上傳的檔案
    for i, uf in enumerate(files):
        _batch_items.append((i, uf, None))
    # 分片上傳的檔案
    if chunked_uploads_map:
        from .uploads import get_upload_meta, remove_upload
        for str_idx, uid in chunked_uploads_map.items():
            global_idx = int(str_idx)
            meta = get_upload_meta(uid)
            if meta and meta["user_id"] == str(current_user["_id"]):
                remove_upload(uid)
                _batch_items.append((global_idx, None, meta))
            else:
                _batch_items.append((global_idx, None, None))  # 無效，後續會報錯
    # 按 global_idx 排序
    _batch_items.sort(key=lambda x: x[0])

    # 逐一處理每個檔案
    for idx, upload_file, chunked_meta in _batch_items:
        display_name = upload_file.filename if upload_file else (chunked_meta["filename"] if chunked_meta else "unknown")
        file_result = {
            "index": idx,
            "filename": display_name,
            "task_id": None,
            "status": "pending",
            "error": None,
            "queue_position": None
        }

        temp_dir = None
        try:
            if chunked_meta is None and upload_file is None:
                raise ValueError("upload_id 無效或尚未完成組裝")

            if chunked_meta:
                # 分片上傳模式
                temp_dir = chunked_meta["temp_dir"]
                temp_audio = chunked_meta["assembled_path"]
                original_filename = chunked_meta["filename"]
            else:
                # 直接上傳模式
                temp_dir = Path(tempfile.mkdtemp())
                file_suffix = Path(upload_file.filename).suffix
                temp_audio = temp_dir / f"input{file_suffix}"

                content = await upload_file.read()
                with temp_audio.open("wb") as f:
                    f.write(content)
                original_filename = upload_file.filename

            # 獲取音檔資訊
            try:
                audio_duration_ms = audio_service.get_audio_duration(temp_audio)
                audio_duration_seconds = audio_duration_ms / 1000.0
                audio_size_mb = round(temp_audio.stat().st_size / 1024 / 1024, 2)
            except Exception as e:
                raise ValueError(f"無法讀取音檔資訊：{str(e)}")

            # 檢查配額
            try:
                await QuotaManager.check_transcription_quota(
                    full_user_data,
                    audio_duration_seconds
                )
            except HTTPException as quota_error:
                raise ValueError(quota_error.detail)

            # 獲取單檔覆蓋設定
            override = file_overrides.get(str(idx), {})
            file_tags = override.get("tags", default_tags.copy())
            custom_name = override.get("customName", None)

            # 生成任務 ID
            task_id = str(uuid.uuid4())
            current_time = get_utc_timestamp()

            # 創建任務資料
            task_data = {
                "_id": task_id,
                "task_id": task_id,
                "task_type": task_type,
                "user": {
                    "user_id": str(current_user["_id"]),
                    "user_email": current_user["email"]
                },
                "file": {
                    "filename": original_filename,
                    "size_mb": audio_size_mb
                },
                "config": {
                    "punct_provider": punct_provider,
                    "chunk_audio": True,
                    "chunk_minutes": 10,
                    "diarize": diarize,
                    "max_speakers": max_speakers,
                    "language": language
                },
                "status": "pending",
                "stats": {
                    "audio_duration_seconds": audio_duration_seconds,
                },
                "tags": file_tags,
                "keep_audio": False,
                "speaker_names": {},
                "subtitle_settings": {
                    "density_threshold": 3.0,
                },
                "timestamps": {
                    "created_at": current_time,
                    "updated_at": current_time,
                },
                "batch_id": batch_id,  # 關聯批次 ID
            }

            # 如果有自訂名稱
            if custom_name:
                task_data["custom_name"] = custom_name

            # 保存到資料庫
            await task_repo.create(task_data)

            if is_aws():
                # ===== AWS 模式：背景上傳 S3 + 發送 SQS =====
                from ..utils.storage_service import save_audio
                import boto3

                # 預先捕獲配置
                sqs_queue_url = os.getenv("SQS_QUEUE_URL", "")
                sqs_region = os.getenv("S3_REGION", "ap-northeast-1")
                use_punctuation = punct_provider != "none"
                language_code = None if language == "auto" else language
                sqs_payload = _sign_sqs_message({
                    "task_id": task_id,
                    "language": language_code,
                    "use_chunking": True,
                    "use_punctuation": use_punctuation,
                    "punctuation_provider": punct_provider,
                    "use_diarization": diarize,
                    "max_speakers": max_speakers,
                })

                # 捕獲背景任務所需的變數
                _bg_task_id = task_id
                _bg_temp_audio = temp_audio
                _bg_temp_dir = temp_dir

                async def _batch_upload_to_s3_and_notify(
                    bg_task_id=_bg_task_id, bg_temp_audio=_bg_temp_audio,
                    bg_temp_dir=_bg_temp_dir, bg_sqs_payload=sqs_payload
                ):
                    """背景執行 S3 上傳 + SQS 發送（批次）"""
                    try:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, save_audio, bg_task_id, bg_temp_audio)
                        print(f"☁️  批次音檔已上傳到 S3: uploads/{bg_task_id}.mp3")

                        if sqs_queue_url:
                            def _send_sqs():
                                sqs = boto3.client("sqs", region_name=sqs_region)
                                sqs.send_message(
                                    QueueUrl=sqs_queue_url,
                                    MessageBody=json.dumps(bg_sqs_payload)
                                )
                            await loop.run_in_executor(None, _send_sqs)
                            print(f"📨 批次已發送 SQS 訊息: {bg_task_id}")

                    except Exception as e:
                        print(f"❌ 批次 S3 上傳失敗: {bg_task_id}: {e}")
                        try:
                            client, sync_db = _get_sync_db()
                            sync_db.tasks.update_one(
                                {"_id": bg_task_id},
                                {"$set": {"status": "failed", "error": {"message": f"音檔上傳失敗: {str(e)}"}}}
                            )
                            client.close()
                        except Exception as db_err:
                            print(f"❌ 更新任務狀態失敗: {bg_task_id}: {db_err}")
                    finally:
                        if bg_temp_dir.exists():
                            shutil.rmtree(bg_temp_dir)

                # 發射背景任務，不等待
                asyncio.create_task(_batch_upload_to_s3_and_notify())
                temp_dir = None  # 避免 except 中重複清理

                file_result["task_id"] = task_id
                file_result["status"] = "pending"
                file_result["queue_position"] = created_count + 1
                created_count += 1
                print(f"☁️  批次任務 [{idx + 1}/{total_files}] {original_filename} -> {task_id} (SQS)")
            else:
                # ===== 本地模式：現有行為 =====
                # 初始化記憶體狀態
                transcription_service.task_service.update_memory_state(task_id, {
                    "status": "pending",
                    "progress": "等待處理中..."
                })

                # 記錄臨時目錄
                transcription_service.task_service.set_temp_dir(task_id, temp_dir)

                # 計算隊列位置
                should_queue = (processing_count + created_count) >= MAX_CONCURRENT_TASKS
                queue_position = pending_count + created_count + 1 if should_queue else 0

                # 如果系統空閒，立即啟動
                if not should_queue:
                    use_punctuation = punct_provider != "none"
                    language_code = None if language == "auto" else language

                    await task_repo.update(task_id, {"status": "processing"})
                    transcription_service.task_service.update_memory_state(task_id, {
                        "status": "processing",
                        "progress": "準備開始轉錄..."
                    })

                    await transcription_service.start_transcription(
                        task_id=task_id,
                        audio_file_path=temp_audio,
                        language=language_code,
                        use_chunking=True,
                        use_punctuation=use_punctuation,
                        punctuation_provider=punct_provider,
                        use_diarization=diarize,
                        max_speakers=max_speakers
                    )

                file_result["task_id"] = task_id
                file_result["status"] = "pending" if should_queue else "processing"
                file_result["queue_position"] = queue_position
                created_count += 1

                print(f"✅ 批次任務 [{idx + 1}/{total_files}] {original_filename} -> {task_id}")

        except Exception as e:
            file_result["status"] = "failed"
            file_result["error"] = str(e)
            failed_count += 1

            # 清理臨時目錄
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)

            print(f"❌ 批次任務 [{idx + 1}/{total_files}] {display_name} 失敗: {e}")

        results.append(file_result)

    # 記錄 audit log
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
            request_body={
                "batch_id": batch_id,
                "total": total_files,
                "created": created_count,
                "failed": failed_count,
                "task_type": task_type,
                "diarize": diarize,
            }
        )
    except Exception as e:
        print(f"⚠️ 記錄 audit log 失敗：{e}")

    return {
        "batch_id": batch_id,
        "total": total_files,
        "created": created_count,
        "failed": failed_count,
        "tasks": results
    }
