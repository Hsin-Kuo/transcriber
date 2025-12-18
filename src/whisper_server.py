#!/usr/bin/env python3
"""
Whisper 轉錄服務 - FastAPI 版本
模型只需載入一次，可重複使用提升效率
"""

import os
import sys
import tempfile
import shutil
import asyncio
import uuid
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from threading import Lock
import multiprocessing
from faster_whisper import WhisperModel
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# 載入環境變數
from dotenv import load_dotenv
load_dotenv()

# 認證系統模組
from src.database.mongodb import MongoDB, get_database
from src.database.repositories.task_repo import TaskRepository
from src.database.repositories.tag_repo import TagRepository
from src.routers import auth as auth_router
from src.auth.dependencies import check_quota, get_current_user
from src.auth.quota import QuotaManager

# Speaker Diarization
try:
    from pyannote.audio import Pipeline
    DIARIZATION_AVAILABLE = True
except ImportError:
    DIARIZATION_AVAILABLE = False
    print("⚠️  pyannote.audio 未安裝，speaker diarization 功能不可用")

# —— 設定 —— #
DEFAULT_MODEL = "medium"
CHUNK_DURATION_MS = 10 * 60 * 1000
OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-2.0-flash"
# 多層備援模型列表（按優先順序）
GEMINI_FALLBACK_MODELS = [
    "gemini-2.0-flash-lite",      # 第一備援：2.0-flash-lite（輕量版，配額較寬鬆）
    "gemini-flash-lite-latest",   # 第二備援：flash-lite-latest（最輕量，通常有配額）
    "gemini-2.5-flash",           # 第三備援：2.5-flash（最新版本）
    "gemini-flash-latest",        # 第四備援：flash-latest（通用版本）
    "gemini-2.5-pro",             # 第五備援：2.5-pro（更強大但較慢）
]
GEMINI_FALLBACK_MODEL = "gemini-2.0-flash-lite"  # 向後兼容（已棄用）

# 進度階段權重（固定分配，總和 100%）
PROGRESS_WEIGHTS = {
    "audio_conversion": 5.0,      # 音訊轉檔：5%
    "audio_chunking": 5.0,        # 音訊切分：5%（僅分段模式）
    "transcription": 77.0,        # 轉錄：77%（分段模式）或 82%（非分段模式）
    "punctuation": 13.0,          # 加標點：13%
}

# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))

def get_current_time():
    """取得 UTC+8 當前時間"""
    return datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")

def format_duration(seconds: float) -> str:
    """格式化時長為友好的文字"""
    if seconds < 60:
        return f"{int(seconds)} 秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes} 分 {secs} 秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours} 小時 {minutes} 分"

def calculate_progress_percentage(task_data: Dict[str, Any]) -> float:
    """根據任務狀態動態計算進度百分比

    - 完成時強制返回 100%
    - 過程中根據實際 chunks 數量動態分配權重
    """
    # 如果任務已完成，直接返回 100%
    if task_data.get("status") == "completed":
        return 100.0

    progress = 0.0
    chunks = task_data.get("chunks", [])
    is_chunked = len(chunks) > 0  # 是否使用分段模式

    # 1. 音訊轉檔完成：5%
    if task_data.get("audio_converted", False):
        progress += PROGRESS_WEIGHTS["audio_conversion"]

    # 2. 轉錄階段
    if is_chunked:
        # 分段模式：audio_chunking(5%) + transcription(77%)
        if task_data.get("chunks_created", False):
            progress += PROGRESS_WEIGHTS["audio_chunking"]

        # 根據實際 chunks 數量分配轉錄進度
        num_chunks = len(chunks)
        if num_chunks > 0:
            completed_chunks = sum(1 for c in chunks if c.get("status") == "completed")
            processing_chunks = sum(1 for c in chunks if c.get("status") == "processing")

            # 每個 chunk 完成貢獻：77% / num_chunks
            # 每個 chunk 進行中貢獻：50% 的完成權重
            chunk_weight = PROGRESS_WEIGHTS["transcription"] / num_chunks
            progress += completed_chunks * chunk_weight
            progress += processing_chunks * (chunk_weight * 0.5)
    else:
        # 非分段模式：transcription(82%) = audio_chunking(5%) + transcription(77%)
        # 簡單判斷：如果已經開始標點，說明轉錄完成
        if task_data.get("punctuation_started", False) or task_data.get("punctuation_completed", False):
            progress += PROGRESS_WEIGHTS["audio_chunking"] + PROGRESS_WEIGHTS["transcription"]
        elif task_data.get("audio_converted", False):
            # 轉錄中，給予 50% 的轉錄進度
            progress += (PROGRESS_WEIGHTS["audio_chunking"] + PROGRESS_WEIGHTS["transcription"]) * 0.5

    # 3. 標點處理：13%
    if task_data.get("punctuation_completed", False):
        progress += PROGRESS_WEIGHTS["punctuation"]
    elif task_data.get("punctuation_started", False):
        # 標點處理中，根據段數計算進度
        punct_current = task_data.get("punctuation_current_chunk", 0)
        punct_total = task_data.get("punctuation_total_chunks", 1)
        punct_progress = (punct_current / punct_total) * PROGRESS_WEIGHTS["punctuation"]
        progress += punct_progress

    return min(progress, 100.0)

# 輸出目錄設定
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 任務狀態持久化檔案
TASKS_DB_FILE = OUTPUT_DIR / "tasks.json"
TAG_COLORS_FILE = OUTPUT_DIR / "tag_colors.json"
TAG_ORDER_FILE = OUTPUT_DIR / "tag_order.json"

# —— Google API Keys 管理 —— #
def load_google_api_keys():
    """從環境變數載入所有 Google API Keys"""
    keys = []
    i = 1
    while True:
        key = os.getenv(f"GOOGLE_API_KEY_{i}")
        if not key:
            break
        keys.append(key)
        i += 1

    # 如果沒有找到編號的 keys，嘗試使用單一的 GOOGLE_API_KEY
    if not keys:
        single_key = os.getenv("GOOGLE_API_KEY")
        if single_key:
            keys.append(single_key)

    return keys

GOOGLE_API_KEYS = load_google_api_keys()
current_google_key_index = 0
google_keys_lock = Lock()

def get_next_google_api_key():
    """獲取下一個 Google API Key（輪詢）"""
    global current_google_key_index

    if not GOOGLE_API_KEYS:
        raise ValueError("未設定任何 GOOGLE_API_KEY")

    with google_keys_lock:
        key = GOOGLE_API_KEYS[current_google_key_index]
        current_google_key_index = (current_google_key_index + 1) % len(GOOGLE_API_KEYS)
        print(f"🔑 使用 Google API Key #{current_google_key_index + 1}/{len(GOOGLE_API_KEYS)}")
        return key

# —— 全域模型 (啟動時載入，持久化在記憶體中) —— #
whisper_model = None
current_model_name = None

# —— 任務狀態管理 —— #
# 已遷移到 MongoDB，保留下方字典僅用於運行時狀態（非持久化）
task_temp_dirs: Dict[str, Path] = {}  # 儲存任務的暫存目錄路徑
task_cancelled: Dict[str, bool] = {}  # 標記已取消的任務
task_diarization_processes: Dict[str, Any] = {}  # 儲存任務的 diarization 進程
transcription_tasks: Dict[str, Any] = {}  # [Refactor] 儲存即時(in-memory)任務狀態，例如詳細進度

# 定義只需存在記憶體中的欄位（執行期間才有用，完成後無意義）
MEMORY_ONLY_FIELDS = {
    # 即時進度資訊
    "progress",  # 進度文字描述（如 "正在轉錄 chunk 3/10..."）
    "progress_percentage",  # 進度百分比（可從狀態即時計算）

    # 分塊執行細節
    "chunks",  # 每個 chunk 的詳細狀態陣列（超大物件，頻繁更新）
    "total_chunks",  # 總分塊數（可從 chunks 長度計算）
    "completed_chunks",  # 已完成分塊數（可從 chunks 計算）
    "chunks_created",  # 分塊是否已建立旗標
    "estimated_completion_time",  # 預估完成時間（執行期間的估算值）

    # 標點符號處理中間狀態
    "punctuation_started",  # 標點處理是否已開始
    "punctuation_current_chunk",  # 當前處理的標點段數
    "punctuation_total_chunks",  # 標點處理總段數
    "punctuation_completed",  # 標點處理是否完成

    # 說話者辨識中間狀態
    "diarization_started",  # 說話者辨識是否已開始
    "diarization_completed",  # 說話者辨識是否完成
    "diarization_status",  # 說話者辨識即時狀態

    # 其他中間處理旗標
    "audio_converted",  # 音檔是否已轉換
}

tag_colors: Dict[str, str] = {}  # 儲存標籤顏色 (標籤名稱 -> 顏色碼)
tag_order: list[str] = []  # 儲存標籤順序
tasks_lock = Lock()  # 線程安全鎖（用於運行時狀態）
executor = ThreadPoolExecutor(max_workers=1)  # 線程池（像 main branch，只用 1 個 worker 避免競爭）

# MongoDB 任務資料庫
task_repo: Optional[TaskRepository] = None  # 在 startup 事件中初始化
tag_repo: Optional[TagRepository] = None  # 標籤資料庫
main_loop: Optional[asyncio.AbstractEventLoop] = None  # 主事件循環

# ==================== 已棄用：JSON 檔案處理（已遷移到 MongoDB） ====================
# 以下函數已不再使用，保留程式碼以防萬一需要還原
# JSON 檔案仍保留在磁碟上作為備份

# def save_tasks_to_disk():
#     """[已棄用] 將任務狀態保存到磁碟"""
#     pass

# def load_tasks_from_disk():
#     """[已棄用] 從磁碟載入任務狀態"""
#     global tag_colors, tag_order
#     try:
#         # 仍然載入標籤顏色和順序（尚未遷移到 MongoDB）
#         if TAG_COLORS_FILE.exists():
#             with open(TAG_COLORS_FILE, 'r', encoding='utf-8') as f:
#                 tag_colors = json.load(f)
#             print(f"✅ 已載入 {len(tag_colors)} 個標籤顏色設定")
#
#         if TAG_ORDER_FILE.exists():
#             with open(TAG_ORDER_FILE, 'r', encoding='utf-8') as f:
#                 tag_order = json.load(f)
#             print(f"✅ 已載入標籤順序（{len(tag_order)} 個標籤）")
#     except Exception as e:
#         print(f"❌ 載入標籤設定失敗：{e}")

def load_tag_settings():
    """從磁碟載入標籤設定（標籤顏色和順序）"""
    global tag_colors, tag_order
    try:
        if TAG_COLORS_FILE.exists():
            with open(TAG_COLORS_FILE, 'r', encoding='utf-8') as f:
                tag_colors = json.load(f)
            print(f"✅ 已載入 {len(tag_colors)} 個標籤顏色設定")

        if TAG_ORDER_FILE.exists():
            with open(TAG_ORDER_FILE, 'r', encoding='utf-8') as f:
                tag_order = json.load(f)
            print(f"✅ 已載入標籤順序（{len(tag_order)} 個標籤）")
    except Exception as e:
        print(f"❌ 載入標籤設定失敗：{e}")

def save_tag_settings():
    """保存標籤設定到磁碟（標籤顏色和順序）"""
    try:
        with open(TAG_COLORS_FILE, 'w', encoding='utf-8') as f:
            json.dump(tag_colors, f, ensure_ascii=False, indent=2)
        with open(TAG_ORDER_FILE, 'w', encoding='utf-8') as f:
            json.dump(tag_order, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ 保存標籤設定失敗：{e}")

# ==================== MongoDB 輔助函數 ====================
def run_async_in_thread(coro):
    """在背景同步線程中，安全地執行一個協程 (coroutine)"""
    global main_loop
    if main_loop is None or not main_loop.is_running():
        # Fallback for scripts or tests that don't run the full app
        print("⚠️ Main event loop is not available, running in a new loop.")
        return asyncio.run(coro)

    future = asyncio.run_coroutine_threadsafe(coro, main_loop)
    return future.result()  # Blocks until the coroutine is done and returns the result.

async def get_task_from_db(task_id: str) -> Optional[Dict[str, Any]]:
    """從資料庫獲取任務"""
    if task_repo is None:
        print(f"⚠️  TaskRepository 未初始化")
        return None
    return await task_repo.get_by_id(task_id)

async def update_task_in_db(task_id: str, updates: Dict[str, Any]) -> bool:
    """更新資料庫中的任務"""
    if task_repo is None:
        print(f"⚠️  TaskRepository 未初始化")
        return False
    return await task_repo.update(task_id, updates)

async def create_task_in_db(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """在資料庫中建立任務"""
    if task_repo is None:
        print(f"⚠️  TaskRepository 未初始化")
        return task_data
    return await task_repo.create(task_data)

# Tag models (imported from src/models/tag.py)
from src.models.tag import TagCreate, TagUpdate, TagOrderUpdate as TagOrderUpdateModel, TagResponse

# Pydantic models
class TranscriptContentUpdate(BaseModel):
    content: str

class TaskMetadataUpdate(BaseModel):
    custom_name: str = None

class TaskTagsUpdate(BaseModel):
    tags: list[str] = []

class TagColorUpdate(BaseModel):
    color: str

class TagOrderUpdate(BaseModel):
    order: list[str] = []

class KeepAudioUpdate(BaseModel):
    keep_audio: bool

class BatchDeleteRequest(BaseModel):
    task_ids: List[str]

class BatchTagsRequest(BaseModel):
    task_ids: List[str]
    tags: List[str]


from src.models.task import TaskInDB as Task


app = FastAPI(
    title="Whisper 轉錄服務",
    description="上傳音檔進行轉錄，支援自動分段與標點",
    version="2.0.0"
)

# 添加 CORS 中間件
# 從環境變數讀取允許的來源
cors_origins_str = os.getenv("CORS_ORIGINS", "*")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",")] if cors_origins_str != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],  # 允許前端訪問所有響應頭
    max_age=3600,  # preflight 請求快取時間（秒）
)

# 註冊認證路由
app.include_router(auth_router.router)


# ---------- 工具函式 ----------

def cleanup_temp_dir(temp_dir: Path):
    """清理臨時目錄"""
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"🗑️ 已清理臨時目錄：{temp_dir.name}")
    except Exception as e:
        print(f"⚠️ 清理臨時目錄失敗：{e}")


def get_task_field(task: Dict[str, Any], field: str) -> Any:
    """安全獲取任務欄位（支援巢狀與扁平格式）

    Args:
        task: 任務資料
        field: 欄位名稱（扁平格式，如 'result_file', 'user_id'）

    Returns:
        欄位值，如果不存在則返回 None
    """
    # 欄位映射：扁平名稱 -> (巢狀路徑列表)
    FIELD_PATHS = {
        # user 相關
        "user_id": [("user", "user_id"), None],
        "user_email": [("user", "user_email"), None],

        # file 相關
        "filename": [("file", "filename"), None],
        "file_size_mb": [("file", "size_mb"), None],

        # config 相關
        "punct_provider": [("config", "punct_provider"), None],
        "chunk_audio": [("config", "chunk_audio"), None],
        "diarize": [("config", "diarize"), None],
        "language": [("config", "language"), None],

        # result 相關
        "result_file": [("result", "transcription_file"), None],
        "result_filename": [("result", "transcription_filename"), None],
        "audio_file": [("result", "audio_file"), None],
        "audio_filename": [("result", "audio_filename"), None],
        "segments_file": [("result", "segments_file"), None],
        "text_length": [("result", "text_length"), None],

        # stats 相關
        "duration_seconds": [("stats", "duration_seconds"), None],
        "total_tokens_used": [("stats", "token_usage", "total"), None],

        # timestamps 相關
        "created_at": [("timestamps", "created_at"), None],
        "updated_at": [("timestamps", "updated_at"), None],
        "completed_at": [("timestamps", "completed_at"), None],
    }

    # 如果是頂層欄位（status, progress, tags, keep_audio, custom_name 等）
    if field not in FIELD_PATHS:
        return task.get(field)

    # 嘗試從巢狀路徑獲取
    nested_path = FIELD_PATHS[field][0]
    if nested_path:
        value = task
        for key in nested_path:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                value = None
                break

        if value is not None:
            return value

    # 向後兼容：嘗試從扁平結構獲取
    return task.get(field)


def convert_nested_to_flat_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """將巢狀結構的任務資料轉換為扁平格式（向後兼容）

    Args:
        task: 巢狀格式的任務資料

    Returns:
        扁平格式的任務資料
    """
    if not task:
        return task

    # 如果已經是扁平格式（舊資料），直接返回
    if "user_id" in task and "filename" in task:
        return task

    # 轉換為扁平格式
    flat_task = {
        "_id": task.get("_id"),
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "tags": task.get("tags", []),
        "custom_name": task.get("custom_name"),
        "keep_audio": task.get("keep_audio", False),
    }

    # 使用者資訊
    if "user" in task:
        flat_task["user_id"] = task["user"]["user_id"]
        flat_task["user_email"] = task["user"]["user_email"]

    # 檔案資訊
    if "file" in task:
        flat_task["filename"] = task["file"]["filename"]
        flat_task["file_size_mb"] = task["file"]["size_mb"]

    # 配置
    if "config" in task:
        flat_task["punct_provider"] = task["config"].get("punct_provider")
        flat_task["chunk_audio"] = task["config"].get("chunk_audio")
        flat_task["chunk_minutes"] = task["config"].get("chunk_minutes")
        flat_task["diarize"] = task["config"].get("diarize")
        flat_task["max_speakers"] = task["config"].get("max_speakers")
        flat_task["language"] = task["config"].get("language")

    # 結果檔案
    if "result" in task and task["result"]:
        flat_task["audio_file"] = task["result"].get("audio_file")
        flat_task["audio_filename"] = task["result"].get("audio_filename")
        flat_task["result_file"] = task["result"].get("transcription_file")
        flat_task["result_filename"] = task["result"].get("transcription_filename")
        flat_task["segments_file"] = task["result"].get("segments_file")
        flat_task["text_length"] = task["result"].get("text_length")

    # 統計資訊
    if "stats" in task and task["stats"]:
        flat_task["duration_seconds"] = task["stats"].get("duration_seconds")
        if "token_usage" in task["stats"] and task["stats"]["token_usage"]:
            flat_task["total_tokens_used"] = task["stats"]["token_usage"].get("total")
            flat_task["prompt_tokens_used"] = task["stats"]["token_usage"].get("prompt")
            flat_task["completion_tokens_used"] = task["stats"]["token_usage"].get("completion")
            flat_task["llm_model_used"] = task["stats"]["token_usage"].get("model")
        if "diarization" in task["stats"] and task["stats"]["diarization"]:
            flat_task["diarization_num_speakers"] = task["stats"]["diarization"].get("num_speakers")
            flat_task["diarization_duration_seconds"] = task["stats"]["diarization"].get("duration_seconds")

    # 時間戳記
    if "timestamps" in task:
        flat_task["created_at"] = task["timestamps"]["created_at"]
        flat_task["updated_at"] = task["timestamps"].get("updated_at")
        flat_task["started_at"] = task["timestamps"].get("started_at")
        flat_task["completed_at"] = task["timestamps"].get("completed_at")

    return flat_task


def convert_flat_to_nested_updates(updates: Dict[str, Any]) -> Dict[str, Any]:
    """將扁平欄位更新轉換為巢狀結構的 MongoDB 更新格式

    Args:
        updates: 扁平格式的更新字典

    Returns:
        MongoDB dot notation 格式的更新字典
    """
    # 欄位映射：舊欄位名 -> 新巢狀路徑
    FIELD_MAPPING = {
        # result 相關
        "audio_file": "result.audio_file",
        "audio_filename": "result.audio_filename",
        "result_file": "result.transcription_file",
        "result_filename": "result.transcription_filename",
        "segments_file": "result.segments_file",
        "text_length": "result.text_length",

        # stats 相關
        "duration_seconds": "stats.duration_seconds",
        "total_tokens_used": "stats.token_usage.total",
        "prompt_tokens_used": "stats.token_usage.prompt",
        "completion_tokens_used": "stats.token_usage.completion",
        "llm_model_used": "stats.token_usage.model",
        "diarization_num_speakers": "stats.diarization.num_speakers",
        "diarization_duration_seconds": "stats.diarization.duration_seconds",

        # timestamps 相關
        "created_at": "timestamps.created_at",
        "updated_at": "timestamps.updated_at",
        "started_at": "timestamps.started_at",
        "completed_at": "timestamps.completed_at",
    }

    nested_updates = {}
    for key, value in updates.items():
        # 如果在映射表中，使用新路徑
        if key in FIELD_MAPPING:
            nested_updates[FIELD_MAPPING[key]] = value
        else:
            # 否則保持原樣（status, progress, tags, keep_audio, custom_name 等頂層欄位）
            nested_updates[key] = value

    return nested_updates


def update_task_status(task_id: str, updates: Dict[str, Any], persist_to_db: bool = None):
    """更新任務狀態（智能選擇是否持久化到 MongoDB）

    Args:
        task_id: 任務 ID
        updates: 要更新的欄位字典（扁平格式，會自動轉換為巢狀格式）
        persist_to_db: 是否持久化到 MongoDB
            - None（預設）: 自動判斷（狀態變更時持久化，進度更新時僅記憶體）
            - True: 強制持久化
            - False: 僅更新記憶體
    """
    # 更新時間戳
    updates["updated_at"] = get_current_time()

    # --- 1. 總是更新記憶體中的即時狀態（使用扁平格式） ---
    with tasks_lock:
        if task_id not in transcription_tasks:
            transcription_tasks[task_id] = {}
        transcription_tasks[task_id].update(updates)
        if 'progress' in updates:
            print(f"🔄 [{task_id}] In-memory progress: {updates['progress']}")

    # --- 2. 決定是否需要持久化到 MongoDB ---
    # 像 main branch 一樣：只在任務完成時才持久化（避免頻繁 DB 寫入）
    if persist_to_db is None:
        # 只在最終狀態時自動持久化
        persist_to_db = updates.get("status") in ["completed", "failed", "cancelled"]

    # --- 3. 持久化到 MongoDB（僅在必要時） ---
    if persist_to_db:
        # 檢查是否為最終狀態（完成、失敗、取消）
        is_final_status = updates.get("status") in ["completed", "failed", "cancelled"]

        # 過濾掉記憶體專用欄位
        # 但如果是最終狀態，保留 progress 欄位以記錄最終進度訊息
        db_updates = {
            k: v for k, v in updates.items()
            if k not in MEMORY_ONLY_FIELDS or (k == "progress" and is_final_status)
        }

        # 轉換為巢狀結構的 MongoDB 更新格式
        db_updates = convert_flat_to_nested_updates(db_updates)

        # 如果過濾後還有欄位需要更新
        if db_updates:
            # 計算進度百分比（僅使用記憶體數據，不查詢 DB）
            if "status" in db_updates or "completed_chunks" in updates:
                with tasks_lock:
                    if task_id in transcription_tasks:
                        # 直接使用記憶體中的資料計算進度（避免阻塞式 DB 查詢）
                        progress_pct = calculate_progress_percentage(transcription_tasks[task_id])
                        transcription_tasks[task_id]["progress_percentage"] = round(progress_pct, 1)

            # 更新到 MongoDB（使用 future，不阻塞當前線程）
            # 使用 asyncio.create_task 在背景執行，避免阻塞 worker 線程
            try:
                if main_loop and main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(update_task_in_db(task_id, db_updates), main_loop)
                    print(f"💾 [{task_id}] 持久化到 MongoDB (非阻塞): {list(db_updates.keys())}")
                else:
                    print(f"⚠️ [{task_id}] Event loop 不可用，跳過 DB 更新")
            except Exception as e:
                print(f"⚠️ [{task_id}] DB 更新失敗（不影響轉錄）: {e}")
        else:
            print(f"⚡ [{task_id}] 僅記憶體更新（無需持久化）")
    else:
        print(f"⚡ [{task_id}] 僅記憶體更新")

    # --- 4. 任務結束時的清理 ---
    final_status = updates.get("status")
    if final_status in ["completed", "failed", "cancelled"]:
        print(f"✅ [{task_id}] 任務已結束：{final_status}")
        # 從即時狀態字典中移除，以釋放記憶體
        with tasks_lock:
            transcription_tasks.pop(task_id, None)
# ---------- 轉錄函式 (從原始 transcribe.py 移植) ----------

def transcribe_single_chunk(
    model,
    chunk_path: Path,
    language: Optional[str] = None,
    task_id: str = None,
    chunk_idx: int = None,
    time_offset: float = 0.0,
    return_segments: bool = True
) -> tuple:
    """轉錄單一音檔片段（用於並行處理）

    Args:
        model: Whisper 模型
        chunk_path: 音檔路徑
        language: 語言代碼（None 表示自動偵測，預設值）
        task_id: 任務 ID
        chunk_idx: Chunk 索引
        time_offset: 時間偏移（秒），用於計算相對於完整音檔的時間戳
        return_segments: 是否返回帶時間戳的 segments（預設 True）

    Returns:
        返回 (text, segments, detected_language) 元組
    """
    # 標記此 chunk 開始處理（實際開始執行時才標記）
    if task_id and chunk_idx:
        # 從記憶體獲取 chunks（不查詢 DB，避免阻塞）
        with tasks_lock:
            chunks = transcription_tasks.get(task_id, {}).get("chunks", [])

            # 如果記憶體中沒有 chunks，跳過狀態更新（不阻塞等待 DB）
            if chunks and chunk_idx - 1 < len(chunks) and chunks[chunk_idx - 1]["status"] == "pending":
                chunks[chunk_idx - 1]["status"] = "processing"
                chunks[chunk_idx - 1]["started_at"] = get_current_time()
                # 直接在這裡更新，避免再次取得鎖（避免死鎖）
                if task_id not in transcription_tasks:
                    transcription_tasks[task_id] = {}
                transcription_tasks[task_id]["chunks"] = chunks
                transcription_tasks[task_id]["updated_at"] = get_current_time()

    segments, info = model.transcribe(str(chunk_path), language=language, beam_size=5)

    # 獲取 Whisper 偵測到的語言
    detected_language = info.language if hasattr(info, 'language') else None

    # 始終收集 segments
    segments_list = []
    text_parts = []

    for segment in segments:
        text_parts.append(segment.text)
        segments_list.append({
            "start": segment.start + time_offset,  # 加上時間偏移
            "end": segment.end + time_offset,
            "text": segment.text
        })

    text = "".join(text_parts).strip()

    return text, segments_list, detected_language


def transcribe_with_timestamps(model, audio_path: Path, language: Optional[str] = None) -> tuple:
    """
    轉錄音檔並返回帶時間戳的 segments

    Args:
        model: Whisper 模型
        audio_path: 音檔路徑
        language: 語言代碼（None 表示自動偵測，預設值）

    Returns:
        返回 (segments_list, detected_language) 元組
        segments_list: List of segments with format [{"start": 0.0, "end": 5.2, "text": "hello"}, ...]
        detected_language: Whisper 偵測到的語言代碼
    """
    segments_list = []
    segments, info = model.transcribe(str(audio_path), language=language, beam_size=5)

    # 獲取 Whisper 偵測到的語言
    detected_language = info.language if hasattr(info, 'language') else None

    for segment in segments:
        segments_list.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text
        })

    return segments_list, detected_language


def perform_diarization_in_process(audio_path_str: str, max_speakers: Optional[int], hf_token: str) -> Optional[List[Dict]]:
    """在獨立進程中執行 speaker diarization（可被強制終止）

    此函數設計為在單獨的進程中運行，因此不依賴全局變量

    Args:
        audio_path_str: 音檔路徑（字串格式）
        max_speakers: 最大講者人數（可選，2-10）
        hf_token: Hugging Face Token

    Returns:
        List of diarization segments with format:
        [{"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"}, ...]
    """
    try:
        # 在進程中重新載入 pipeline（因為無法跨進程傳遞）
        from pyannote.audio import Pipeline
        from huggingface_hub import login

        if hf_token:
            login(token=hf_token, add_to_git_credential=False)

        print(f"🔊 [進程] 正在載入 diarization pipeline...")
        import torch
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

        # M1 Mac MPS 加速
        if torch.backends.mps.is_available():
            pipeline.to(torch.device("mps"))
            print(f"🔊 [進程] 使用 MPS 加速")

        print(f"🔊 [進程] 正在分析說話者...")

        # 準備 diarization 參數
        diarization_kwargs = {}
        if max_speakers is not None and 2 <= max_speakers <= 10:
            diarization_kwargs["min_speakers"] = 1
            diarization_kwargs["max_speakers"] = max_speakers
            print(f"   [進程] 設定講者人數範圍：1-{max_speakers} 人")

        print(f"   [進程] Diarization 參數：{diarization_kwargs}")
        diarization = pipeline(audio_path_str, **diarization_kwargs)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })

        print(f"✅ [進程] 說話者分析完成，識別到 {len(set(s['speaker'] for s in segments))} 位說話者")
        return segments

    except Exception as e:
        print(f"⚠️  [進程] Speaker diarization 失敗：{e}")
        return None


def perform_diarization(audio_path: Path, max_speakers: Optional[int] = None) -> Optional[List[Dict]]:
    """執行 speaker diarization（線程版本，用於非分段模式）

    Args:
        audio_path: 音檔路徑
        max_speakers: 最大講者人數（可選，2-10）

    Returns:
        List of diarization segments with format:
        [{"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"}, ...]
    """
    if not diarization_pipeline:
        return None

    try:
        print(f"🔊 正在分析說話者...")

        # 準備 diarization 參數
        diarization_kwargs = {}
        if max_speakers is not None and 2 <= max_speakers <= 10:
            # pyannote.audio 需要同時設定 min_speakers 和 max_speakers
            diarization_kwargs["min_speakers"] = 1
            diarization_kwargs["max_speakers"] = max_speakers
            print(f"   設定講者人數範圍：1-{max_speakers} 人")

        print(f"   Diarization 參數：{diarization_kwargs}")
        diarization = diarization_pipeline(str(audio_path), **diarization_kwargs)

        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })

        print(f"✅ 說話者分析完成，識別到 {len(set(s['speaker'] for s in segments))} 位說話者")
        return segments

    except Exception as e:
        print(f"⚠️  Speaker diarization 失敗：{e}")
        return None


def merge_transcription_with_diarization(
    transcription_segments: List[Dict],
    diarization_segments: List[Dict]
) -> str:
    """合併轉錄文字和說話者標記

    Args:
        transcription_segments: Whisper 轉錄結果 (帶時間戳)
        diarization_segments: Speaker diarization 結果

    Returns:
        合併後的文字，格式：[Speaker A] 文字內容
    """
    if not diarization_segments:
        # 沒有 diarization 結果，直接返回純文字
        return " ".join(seg.get("text", "") for seg in transcription_segments)

    # 為每個轉錄片段分配說話者
    result_lines = []
    current_speaker = None
    current_text = []

    for trans_seg in transcription_segments:
        trans_start = trans_seg.get("start", 0)
        trans_end = trans_seg.get("end", 0)
        trans_text = trans_seg.get("text", "")

        if not trans_text.strip():
            continue

        # 找到與此轉錄片段重疊最多的說話者
        best_speaker = None
        max_overlap = 0

        for dia_seg in diarization_segments:
            dia_start = dia_seg["start"]
            dia_end = dia_seg["end"]

            # 計算重疊時間
            overlap_start = max(trans_start, dia_start)
            overlap_end = min(trans_end, dia_end)
            overlap = max(0, overlap_end - overlap_start)

            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = dia_seg["speaker"]

        # 如果說話者改變，輸出之前的內容
        if best_speaker != current_speaker and current_text:
            speaker_label = f"[{current_speaker}]" if current_speaker else ""
            result_lines.append(f"{speaker_label} {''.join(current_text)}")
            current_text = []

        current_speaker = best_speaker
        current_text.append(trans_text)

    # 輸出最後一段
    if current_text:
        speaker_label = f"[{current_speaker}]" if current_speaker else ""
        result_lines.append(f"{speaker_label} {''.join(current_text)}")

    return "\n\n".join(result_lines)


def transcribe_audio_in_chunks(
    audio_path: Path,
    model,
    chunk_duration_ms: int = CHUNK_DURATION_MS,
    task_id: str = None,
    diarize: bool = False,
    max_speakers: Optional[int] = None,
    language: Optional[str] = None
) -> str:
    """將音檔分段後並行轉錄，提高速度和準確度

    Args:
        audio_path: 音檔路徑
        model: Whisper 模型
        chunk_duration_ms: 每段長度（毫秒）
        task_id: 任務 ID
        diarize: 是否啟用說話者辨識（會先對完整音檔做 diarization，再切分轉錄）
        max_speakers: 最大講者人數（可選，2-10）
    """
    print(f"🔊 檢查音檔：{audio_path.name}")

    # 使用 ffprobe 獲取音檔資訊，不載入到記憶體
    import subprocess
    try:
        result = subprocess.run([
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', str(audio_path)
        ], capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            import json
            probe_data = json.loads(result.stdout)
            total_duration_seconds = float(probe_data['format']['duration'])
            total_duration_ms = int(total_duration_seconds * 1000)
            total_minutes = total_duration_ms / 1000 / 60
        else:
            # 如果 ffprobe 失敗，回退到 pydub（但會佔用記憶體）
            print(f"⚠️  ffprobe 失敗，回退到 pydub")
            audio = AudioSegment.from_file(audio_path)
            total_duration_ms = len(audio)
            total_minutes = total_duration_ms / 1000 / 60
            del audio  # 立即釋放記憶體
    except Exception as e:
        print(f"⚠️  獲取音檔資訊失敗，回退到 pydub: {e}")
        audio = AudioSegment.from_file(audio_path)
        total_duration_ms = len(audio)
        total_minutes = total_duration_ms / 1000 / 60
        del audio  # 立即釋放記憶體

    print(f"📊 音檔總長度：{total_minutes:.1f} 分鐘")

    # 如果音檔不長，直接轉錄
    if total_duration_ms <= chunk_duration_ms:
        print(f"📝 音檔長度在 {chunk_duration_ms/1000/60:.0f} 分鐘內，直接轉錄...")
        text, segments, detected_language = transcribe_single_chunk(model, audio_path, language=language)
        return text, segments, detected_language

    # 步驟 1：如果啟用 diarization，在背景並行執行說話者辨識
    diarization_future = None
    diarization_start_time = None
    diarization_executor = None

    # 暫時強制關閉說話者辨識，測試是否是 GIL 競爭問題
    if False and diarize and diarization_pipeline:
        diarization_start_time = datetime.now(TZ_UTC8)
        print(f"🔊 在背景啟動說話者辨識（與轉錄並行執行）...")
        if task_id:
            update_task_status(task_id, {
                "progress": "正在分析說話者（背景執行）...",
                "diarization_status": "running"
            })

        # 使用進程池執行 diarization，可以被強制終止
        diarization_executor = ProcessPoolExecutor(max_workers=1)
        hf_token = os.getenv("HF_TOKEN", "")
        diarization_future = diarization_executor.submit(
            perform_diarization_in_process,
            str(audio_path),
            max_speakers,
            hf_token
        )

        # 記錄 diarization 進程供取消時使用
        if task_id:
            with tasks_lock:
                task_diarization_processes[task_id] = diarization_executor

    # 長音檔：分段處理
    num_chunks = (total_duration_ms + chunk_duration_ms - 1) // chunk_duration_ms
    print(f"🔄 音檔較長，將分為 {num_chunks} 段處理（每段約 {chunk_duration_ms/1000/60:.0f} 分鐘）...")

    # 初始化 chunks 狀態追蹤
    if task_id:
        chunks_state = [
            {
                "chunk_id": i,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "duration_seconds": None
            }
            for i in range(1, num_chunks + 1)
        ]

        update_task_status(task_id, {
            "total_chunks": num_chunks,
            "completed_chunks": 0,
            "chunks": chunks_state,
            "chunks_created": False  # 切分尚未完成
            # 不設置 estimated_completion_time，前端會顯示「計算中......」
        })

    # 第一步：準備所有 chunks（使用 ffmpeg 直接切分，避免記憶體問題）
    print(f"📦 準備切分音檔（使用 ffmpeg 流式處理）...")
    chunk_info_list = []  # 儲存 (chunk_idx, start_ms, end_ms, temp_path)
    start_ms = 0
    chunk_idx = 1

    while start_ms < total_duration_ms:
        end_ms = min(start_ms + chunk_duration_ms, total_duration_ms)

        print(f"   準備第 {chunk_idx}/{num_chunks} 段 ({start_ms/1000/60:.1f}-{end_ms/1000/60:.1f} 分鐘)...")

        # 檢查是否已被取消
        if task_id and task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        # 使用 ffmpeg 直接切分，不載入到記憶體
        temp_path = audio_path.parent / f"_temp_{audio_path.stem}_chunk_{chunk_idx}.wav"
        start_seconds = start_ms / 1000.0
        duration_seconds = (end_ms - start_ms) / 1000.0

        try:
            # 使用 ffmpeg 切分音檔（流式處理，不佔用記憶體）
            subprocess.run([
                'ffmpeg', '-y', '-i', str(audio_path),
                '-ss', str(start_seconds),
                '-t', str(duration_seconds),
                '-acodec', 'pcm_s16le',  # WAV 格式
                '-ar', '16000',  # 16kHz 採樣率（Whisper 推薦）
                '-ac', '1',  # 單聲道
                str(temp_path)
            ], check=True, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            print(f"   ⚠️  切分第 {chunk_idx} 段超時，嘗試使用 pydub")
            # 回退到 pydub（較慢但更穩定）
            audio = AudioSegment.from_file(audio_path)
            chunk_audio = audio[start_ms:end_ms]
            chunk_audio.export(temp_path, format="wav")
            del audio, chunk_audio  # 立即釋放
        except Exception as e:
            print(f"   ⚠️  ffmpeg 切分失敗: {e}，回退到 pydub")
            # 回退到 pydub
            audio = AudioSegment.from_file(audio_path)
            chunk_audio = audio[start_ms:end_ms]
            chunk_audio.export(temp_path, format="wav")
            del audio, chunk_audio  # 立即釋放

        chunk_info_list.append((chunk_idx, start_ms, end_ms, temp_path))

        start_ms = end_ms
        chunk_idx += 1

    print(f"✅ 已準備 {len(chunk_info_list)} 個音檔片段（記憶體友好模式）")

    # 標記切分完成並計算預估完成時間
    if task_id:
        # 根據音檔時長計算預估處理時間：音檔時長的 3/5
        estimated_minutes = total_minutes * 3 / 5

        # 取得任務開始時間並計算預估完成時間
        task = run_async_in_thread(get_task_from_db(task_id))
        if task:
            started_at_str = task.get("started_at")
            if started_at_str:
                started_at = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_UTC8)
                estimated_completion = started_at + timedelta(minutes=estimated_minutes)
                estimated_completion_str = estimated_completion.strftime("%Y-%m-%d %H:%M:%S")
            else:
                estimated_completion_str = None
        else:
            estimated_completion_str = None

        update_task_status(task_id, {
            "chunks_created": True,
            "progress": f"已切分為 {num_chunks} 個片段，開始轉錄...",
            "estimated_completion_time": estimated_completion_str
        })

    # 第二步：循序轉錄所有 chunks（避免巢狀 ThreadPoolExecutor 死鎖）
    # 暫時改為循序處理，避免與外層 executor 產生衝突
    print(f"🚀 開始循序轉錄（共 {num_chunks} 段）{'，同時進行說話者辨識' if diarization_future else ''}...")
    chunks_text = [None] * num_chunks  # 預先分配陣列保持順序
    all_segments = []  # 始終收集所有 segments

    try:
        # 暫時使用循序處理避免巢狀 ThreadPoolExecutor 死鎖
        # 循序處理每個 chunk
        detected_language = None
        for chunk_idx, start_ms, end_ms, temp_path in chunk_info_list:
            # 檢查是否已被取消
            if task_id and task_cancelled.get(task_id, False):
                raise RuntimeError("任務已被使用者取消")

            # 計算時間偏移
            time_offset_seconds = start_ms / 1000.0

            try:
                # 轉錄此 chunk
                print(f"   🔄 正在轉錄第 {chunk_idx}/{num_chunks} 段...")
                text, segments, lang = transcribe_single_chunk(
                    whisper_model,
                    temp_path,
                    language,
                    task_id,
                    chunk_idx,
                    time_offset_seconds,
                    True
                )

                # 記錄第一個 chunk 的語言
                if detected_language is None and lang:
                    detected_language = lang

                # 儲存結果
                chunks_text[chunk_idx - 1] = text
                all_segments.extend(segments if segments else [])

                # 更新進度
                completed = chunk_idx
                if task_id:
                    update_task_status(task_id, {
                        "progress": f"正在轉錄音訊... ({completed}/{num_chunks} 段完成)",
                        "completed_chunks": completed
                    }, persist_to_db=False)

            except Exception as e:
                print(f"   ❌ 第 {chunk_idx} 段轉錄失敗：{e}")
                raise

        # 以下是原本的並行處理程式碼（暫時停用）
        if False:
            future_to_chunk = {}
            for chunk_idx, start_ms, end_ms, temp_path in chunk_info_list:
                # 計算這個 chunk 的時間偏移（相對於完整音檔的秒數）
                time_offset_seconds = start_ms / 1000.0

                # 始終返回帶時間戳的 segments
                future = executor.submit(
                    transcribe_single_chunk,
                    model,
                    temp_path,
                    language,  # 使用指定的語言
                    task_id,
                    chunk_idx,
                    time_offset_seconds,
                    True  # return_segments 始終為 True
                )
                future_to_chunk[future] = (chunk_idx, temp_path, time_offset_seconds)

            # 等待完成並更新進度
            detected_language = None  # 用於記錄第一個 chunk 偵測到的語言
            for future in as_completed(future_to_chunk):
                chunk_idx, temp_path, time_offset = future_to_chunk[future]

                # 檢查是否已被取消
                if task_id and task_cancelled.get(task_id, False):
                    executor.shutdown(wait=False, cancel_futures=True)
                    # 強制終止 diarization 進程
                    if diarization_future and diarization_executor:
                        print(f"🛑 正在強制終止說話者辨識進程...")
                        diarization_executor.shutdown(wait=False, cancel_futures=True)
                    raise RuntimeError("任務已被使用者取消")

                try:
                    # 記憶體優化：從記憶體獲取 chunk 開始時間，避免查詢資料庫
                    chunk_start_time = None
                    if task_id:
                        with tasks_lock:
                            live_info = transcription_tasks.get(task_id, {})
                            chunks = live_info.get("chunks", [])
                            if chunk_idx - 1 < len(chunks):
                                start_str = chunks[chunk_idx - 1].get("started_at")
                                if start_str:
                                    try:
                                        chunk_start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
                                    except:
                                        pass  # 忽略解析錯誤

                    result = future.result()

                    # 處理返回結果（現在是 (文字, segments, detected_language) 元組）
                    chunk_text, chunk_segments, chunk_detected_language = result
                    all_segments.extend(chunk_segments)  # 收集所有 segments

                    # 記錄第一個 chunk 偵測到的語言
                    if detected_language is None and chunk_detected_language:
                        detected_language = chunk_detected_language

                    chunks_text[chunk_idx - 1] = chunk_text
                    print(f"   ✅ 完成第 {chunk_idx}/{num_chunks} 段")

                    # 計算 chunk 處理時間
                    chunk_duration = None
                    if chunk_start_time:
                        chunk_end_time = datetime.now(TZ_UTC8)
                        chunk_duration = (chunk_end_time - chunk_start_time.replace(tzinfo=TZ_UTC8)).total_seconds()

                    # 更新 chunk 狀態為 completed
                    completed = sum(1 for t in chunks_text if t is not None)
                    if task_id:
                        # 從記憶體獲取 chunks
                        with tasks_lock:
                            chunks = transcription_tasks.get(task_id, {}).get("chunks", [])
                            if not chunks:
                                task = run_async_in_thread(get_task_from_db(task_id))
                                if task:
                                    chunks = task.get("chunks", [])

                            if chunk_idx - 1 < len(chunks):
                                chunks[chunk_idx - 1]["status"] = "completed"
                                chunks[chunk_idx - 1]["completed_at"] = get_current_time()
                                if chunk_duration:
                                    chunks[chunk_idx - 1]["duration_seconds"] = round(chunk_duration, 1)

                        # 僅更新記憶體（chunks, progress, completed_chunks 都是記憶體專用欄位）
                        update_task_status(task_id, {
                            "chunks": chunks,
                            "progress": f"正在轉錄音訊... ({completed}/{num_chunks} 段完成)",
                            "completed_chunks": completed
                        }, persist_to_db=False)

                except Exception as e:
                    print(f"   ❌ 第 {chunk_idx} 段轉錄失敗：{e}")
                    raise

    finally:
        # 清理所有臨時檔案
        for _, _, _, temp_path in chunk_info_list:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                print(f"⚠️ 清理臨時檔案失敗：{e}")

        # 確保 diarization executor 被正確關閉
        if diarization_executor:
            try:
                diarization_executor.shutdown(wait=False, cancel_futures=True)
                print(f"✅ Diarization 進程已關閉")
            except Exception as e:
                print(f"⚠️ 關閉 diarization executor 失敗：{e}")

        # 清理 diarization 進程記錄
        if task_id:
            with tasks_lock:
                task_diarization_processes.pop(task_id, None)

    print("✅ 所有音檔片段轉錄完成")

    # 第三步：如果啟用了 diarization，等待說話者辨識完成並合併資訊
    if diarization_future:
        print(f"⏳ 等待說話者辨識完成...")
        if task_id:
            update_task_status(task_id, {"progress": "等待說話者辨識完成..."})

        try:
            # 等待 diarization 完成並取得結果
            diarization_segments = diarization_future.result()
            if diarization_executor:
                diarization_executor.shutdown(wait=True)

            # 計算 diarization 實際耗時
            if diarization_start_time:
                diarization_duration = (datetime.now(TZ_UTC8) - diarization_start_time).total_seconds()
            else:
                diarization_duration = 0

            if diarization_segments:
                num_speakers = len(set(s['speaker'] for s in diarization_segments))
                print(f"✅ 說話者辨識完成，識別到 {num_speakers} 位說話者 (耗時 {format_duration(diarization_duration)})")
                if task_id:
                    update_task_status(task_id, {
                        "progress": f"說話者辨識完成 ({num_speakers} 位說話者，耗時 {format_duration(diarization_duration)})",
                        "diarization_status": "completed",
                        "diarization_num_speakers": num_speakers,
                        "diarization_duration_seconds": round(diarization_duration, 1)
                    })

                # 合併說話者資訊與轉錄文字
                print(f"🔗 正在合併說話者資訊與轉錄文字...")
                if task_id:
                    update_task_status(task_id, {"progress": "正在合併說話者資訊..."})

                # 按時間排序 segments（確保順序正確）
                all_segments.sort(key=lambda s: s["start"])

                final_text = merge_transcription_with_diarization(all_segments, diarization_segments)
                print(f"✅ 說話者資訊合併完成")
                return final_text, all_segments, detected_language
            else:
                print(f"⚠️  說話者辨識失敗，返回純文字轉錄")
                if task_id:
                    update_task_status(task_id, {
                        "diarization_status": "failed"
                    })
                return " ".join(chunks_text), all_segments, detected_language

        except Exception as e:
            print(f"⚠️  等待說話者辨識時發生錯誤：{e}")
            print(f"   將返回純文字轉錄")
            if task_id:
                update_task_status(task_id, {
                    "diarization_status": "failed"
                })
            return " ".join(chunks_text), all_segments, detected_language
    else:
        # 沒有 diarization，返回純文字和 segments
        return " ".join(chunks_text), all_segments, detected_language


def detect_language_with_llm(text: str, provider: str = "gemini") -> str:
    """使用 LLM 自動辨識文字語言

    Args:
        text: 要辨識的文字（建議使用前幾百字即可）
        provider: 使用的 LLM 提供者 (gemini/openai)

    Returns:
        語言代碼 (zh/en/ja/ko 等)
    """
    # 只取前 100 字進行辨識以節省成本
    sample_text = text[:100]

    prompt = f"""Please identify the primary language of the following text and respond with ONLY the language code (zh/en/ja/ko/es/fr/de/etc.).

Text:
{sample_text}

Language code:"""

    try:
        if provider == "gemini":
            result = call_gemini_with_retry(prompt).strip().lower()
        else:  # openai
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a language detection assistant. Respond only with language codes."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
            )
            result = resp.choices[0].message.content.strip().lower()

        # 驗證結果是否為有效的語言代碼
        valid_codes = ["zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru", "ar", "hi", "th", "vi"]
        if result in valid_codes:
            return result

        # 如果不是標準代碼，嘗試映射常見回應
        if "chinese" in result or "中文" in result:
            return "zh"
        elif "english" in result:
            return "en"
        elif "japanese" in result or "日本" in result:
            return "ja"
        elif "korean" in result or "韓" in result:
            return "ko"

        # 預設返回中文
        print(f"⚠️ 語言辨識結果不明確: {result}，預設使用中文")
        return "zh"

    except Exception as e:
        print(f"⚠️ 語言辨識失敗: {e}，預設使用中文")
        return "zh"


def get_punctuation_prompt(language: str, text: str) -> tuple[str, str]:
    """根據語言生成適當的標點提示語

    Args:
        language: 語言代碼 (zh/en/ja/ko/等)，由 Whisper 自動偵測或用戶指定
        text: 要處理的文字

    Returns:
        (system_message, user_message) 元組
    """
    if language == "zh":
        system_msg = "你是嚴謹的逐字稿潤飾助手，只做標點與分段。"
        user_msg = (
            "請將以下『中文逐字稿』加上適當標點符號並合理分段。"
            "不要省略或添加內容，不要意譯，保留固有名詞與數字。"
            f"輸出純文字即可：\n\n{text}"
        )
    elif language == "en":
        system_msg = "You are a precise transcript editor. Only add punctuation and paragraphing."
        user_msg = (
            "Please add appropriate punctuation and paragraphing to the following English transcript. "
            "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
            f"Output plain text only:\n\n{text}"
        )
    elif language == "ja":
        system_msg = "あなたは正確な文字起こし編集者です。句読点と段落分けのみを行います。"
        user_msg = (
            "以下の日本語文字起こしに適切な句読点と段落を追加してください。"
            "内容の省略や追加はせず、意訳せず、固有名詞と数字はそのまま保持してください。"
            f"プレーンテキストのみ出力してください：\n\n{text}"
        )
    elif language == "ko":
        system_msg = "당신은 정확한 전사 편집자입니다. 구두점과 단락 나누기만 수행합니다."
        user_msg = (
            "다음 한국어 전사에 적절한 구두점과 단락을 추가해주세요. "
            "내용을 생략하거나 추가하지 말고, 의역하지 말고, 고유명사와 숫자는 그대로 유지하세요. "
            f"일반 텍스트만 출력하세요:\n\n{text}"
        )
    else:
        # 其他語言使用英文提示
        system_msg = "You are a precise transcript editor. Only add punctuation and paragraphing."
        user_msg = (
            f"Please add appropriate punctuation and paragraphing to the following transcript. "
            "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
            f"Output plain text only:\n\n{text}"
        )

    return system_msg, user_msg


def punctuate_with_openai(text: str, language: str = "zh") -> str:
    """用 OpenAI 幫逐字稿加標點與分段（支援多語言）

    Args:
        text: 要加標點的文字
        language: 語言代碼 (zh/en/ja/ko/auto)，auto 會自動辨識
    """
    from openai import OpenAI
    client = OpenAI()

    # 獲取對應語言的提示語
    system_msg, user_msg = get_punctuation_prompt(language, text)

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def call_gemini_with_retry(prompt: str, max_retries: int = None, return_usage: bool = False):
    """調用 Gemini API，支援自動重試和 Key 切換，配額耗盡時自動切換到多層備援模型

    Args:
        prompt: 提示文字
        max_retries: 最大重試次數
        return_usage: 是否回傳 token 使用量資訊

    Returns:
        若 return_usage=False: 回傳文字字串
        若 return_usage=True: 回傳 (文字, token_usage_dict)
    """
    import google.generativeai as genai

    if max_retries is None:
        max_retries = len(GOOGLE_API_KEYS)

    last_error = None
    quota_exceeded_count = 0
    current_model = GEMINI_MODEL
    fallback_index = -1  # 追蹤當前使用的備援模型索引
    tried_models = [GEMINI_MODEL]  # 追蹤已嘗試的模型

    for attempt in range(max_retries * (len(GEMINI_FALLBACK_MODELS) + 1)):  # 擴大重試次數以支援多層備援
        try:
            # 獲取下一個 API Key
            api_key = get_next_google_api_key()
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(current_model)

            # 調用 API
            resp = model.generate_content(
                [{"role": "user", "parts": [prompt]}],
                generation_config={"temperature": 0.2}
            )

            result = (resp.text or "").strip()
            if fallback_index >= 0:
                print(f"✅ 使用備援模型 {current_model} 成功")

            # 提取 token 使用量資訊
            if return_usage and hasattr(resp, 'usage_metadata'):
                usage = {
                    "prompt_tokens": getattr(resp.usage_metadata, 'prompt_token_count', 0),
                    "completion_tokens": getattr(resp.usage_metadata, 'candidates_token_count', 0),
                    "total_tokens": getattr(resp.usage_metadata, 'total_token_count', 0),
                    "model": current_model
                }
                print(f"📊 Token 使用: {usage['total_tokens']} (輸入: {usage['prompt_tokens']}, 輸出: {usage['completion_tokens']})")
                return result, usage

            return result

        except Exception as e:
            last_error = e
            error_msg = str(e)

            # 檢查是否為 429 配額錯誤
            is_quota_error = "429" in error_msg or "quota" in error_msg.lower() or "Quota exceeded" in error_msg

            if is_quota_error:
                quota_exceeded_count += 1
                print(f"⚠️ Google API Key 配額已用完 (嘗試 {attempt + 1}，模型: {current_model})")

                # 如果所有 keys 都配額耗盡，嘗試切換到下一個備援模型
                if quota_exceeded_count >= len(GOOGLE_API_KEYS):
                    fallback_index += 1

                    if fallback_index < len(GEMINI_FALLBACK_MODELS):
                        current_model = GEMINI_FALLBACK_MODELS[fallback_index]
                        print(f"💡 所有 API Keys 在 {tried_models[-1]} 的配額已用完，切換到備用模型 {current_model}")
                        tried_models.append(current_model)
                        quota_exceeded_count = 0  # 重置計數，用新備援模型再試一輪
                        continue
                    else:
                        # 所有備援模型都用完了
                        print(f"❌ 所有模型（{', '.join(tried_models)}）的配額都已用完")
                        raise RuntimeError(f"所有 Google API Keys 都調用失敗。已嘗試模型: {', '.join(tried_models)}。最後錯誤: {error_msg}") from last_error
            else:
                print(f"⚠️ Google API Key 調用失敗 (嘗試 {attempt + 1}): {error_msg}")

            # 如果還有 key 可用，繼續嘗試
            if attempt < max_retries * (len(GEMINI_FALLBACK_MODELS) + 1) - 1:
                print(f"🔄 切換到下一個 API Key...")
                continue
            else:
                print(f"❌ 所有 API Keys 都已嘗試，失敗")
                raise RuntimeError(f"所有 Google API Keys 都調用失敗。已嘗試模型: {', '.join(tried_models)}。最後錯誤: {error_msg}") from last_error

    raise RuntimeError(f"無法調用 Gemini API。已嘗試模型: {', '.join(tried_models)}") from last_error


def get_chunked_punctuation_prompt(language: str, chunk_text: str, chunk_idx: int, total_chunks: int) -> tuple[str, str]:
    """為長文本分段生成提示語

    Args:
        language: 語言代碼
        chunk_text: 當前分段文字
        chunk_idx: 當前分段索引（從1開始）
        total_chunks: 總分段數

    Returns:
        (system_message, user_message) 元組
    """
    if language == "zh":
        system_msg = "你是嚴謹的逐字稿潤飾助手。只做『中文標點補全與合理分段』，不要省略或添加內容，不要意譯，非必要不要用刪節號，保留固有名詞與數字。"
        if chunk_idx == 1:
            user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 1 段）：\n\n{chunk_text}"
        elif chunk_idx == total_chunks:
            user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是最後一段，接續前文）：\n\n{chunk_text}"
        else:
            user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 {chunk_idx} 段，接續前文）：\n\n{chunk_text}"
    elif language == "en":
        system_msg = "You are a precise transcript editor. Only add punctuation and paragraphing. Do not omit or add content, do not paraphrase, preserve proper nouns and numbers."
        if chunk_idx == 1:
            user_msg = f"Add punctuation and paragraphing to this English transcript (part 1):\n\n{chunk_text}"
        elif chunk_idx == total_chunks:
            user_msg = f"Add punctuation and paragraphing to this English transcript (final part, continuing from previous):\n\n{chunk_text}"
        else:
            user_msg = f"Add punctuation and paragraphing to this English transcript (part {chunk_idx}, continuing from previous):\n\n{chunk_text}"
    elif language == "ja":
        system_msg = "あなたは正確な文字起こし編集者です。句読点と段落分けのみを行います。内容の省略や追加はせず、意訳せず、固有名詞と数字はそのまま保持してください。"
        if chunk_idx == 1:
            user_msg = f"以下の日本語文字起こしに句読点と段落を追加してください（第1部分）：\n\n{chunk_text}"
        elif chunk_idx == total_chunks:
            user_msg = f"以下の日本語文字起こしに句読点と段落を追加してください（最後の部分、前の続き）：\n\n{chunk_text}"
        else:
            user_msg = f"以下の日本語文字起こしに句読点と段落を追加してください（第{chunk_idx}部分、前の続き）：\n\n{chunk_text}"
    elif language == "ko":
        system_msg = "당신은 정확한 전사 편집자입니다. 구두점과 단락 나누기만 수행합니다. 내용을 생략하거나 추가하지 말고, 의역하지 말고, 고유명사와 숫자는 그대로 유지하세요."
        if chunk_idx == 1:
            user_msg = f"다음 한국어 전사에 구두점과 단락을 추가해주세요 (1부):\n\n{chunk_text}"
        elif chunk_idx == total_chunks:
            user_msg = f"다음 한국어 전사에 구두점과 단락을 추가해주세요 (마지막 부분, 이전 계속):\n\n{chunk_text}"
        else:
            user_msg = f"다음 한국어 전사에 구두점과 단락을 추가해주세요 ({chunk_idx}부, 이전 계속):\n\n{chunk_text}"
    else:
        # 其他語言使用英文提示
        system_msg = "You are a precise transcript editor. Only add punctuation and paragraphing. Do not omit or add content, do not paraphrase, preserve proper nouns and numbers."
        if chunk_idx == 1:
            user_msg = f"Add punctuation and paragraphing to this transcript (part 1):\n\n{chunk_text}"
        elif chunk_idx == total_chunks:
            user_msg = f"Add punctuation and paragraphing to this transcript (final part, continuing from previous):\n\n{chunk_text}"
        else:
            user_msg = f"Add punctuation and paragraphing to this transcript (part {chunk_idx}, continuing from previous):\n\n{chunk_text}"

    return system_msg, user_msg


def punctuate_with_gemini(text: str, chunk_size: int = None, task_id: str = None, language: str = "zh") -> str:
    """用 Google Gemini 幫逐字稿加標點與分段（支援長文本分段處理、多語言）

    Args:
        text: 要加標點的文字
        chunk_size: 分段大小（字元數），None 則根據語言自動決定
        task_id: 任務 ID（用於更新進度和記錄 token 使用量）
        language: 語言代碼 (zh/en/ja/ko/等)，由 Whisper 自動偵測或用戶指定
    """
    if not GOOGLE_API_KEYS:
        raise RuntimeError("未設定任何 GOOGLE_API_KEY")

    # Token 使用量統計
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    model_used = None

    # 根據語言決定合適的分段大小
    if chunk_size is None:
        if language in ['en', 'es', 'fr', 'de', 'it', 'pt']:
            # 英文等字母語言：使用較大的字元數（因為單詞包含空格，字元數較多）
            chunk_size = 8000  # 約 1300-1600 個英文單詞
        else:
            # 中文、日文、韓文等：使用標準字元數
            chunk_size = 3000  # 約 3000 個字符
        print(f"📏 根據語言 '{language}' 設定分段大小：{chunk_size} 字元")

    # 如果文本不長，直接處理
    if len(text) <= chunk_size:
        system_msg, user_msg = get_punctuation_prompt(language, text)
        prompt = system_msg + "\n\n" + user_msg
        result, usage = call_gemini_with_retry(prompt, return_usage=True)

        # 記錄 token 使用量到資料庫
        if task_id and usage:
            update_task_status(task_id, {
                "total_tokens_used": usage['total_tokens'],
                "prompt_tokens_used": usage['prompt_tokens'],
                "completion_tokens_used": usage['completion_tokens'],
                "llm_model_used": usage['model']
            })

        return result

    # 長文本：分段處理
    print(f"📊 文本長度 {len(text)} 字，將分段處理（每段約 {chunk_size} 字）...")
    chunks = []
    start = 0

    # 根據語言選擇分段標記
    split_markers = '。？！\n' if language in ['zh', 'ja'] else '.?!\n'

    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            for i in range(end, max(start + chunk_size // 2, end - 200), -1):
                if text[i] in split_markers:
                    end = i + 1
                    break
        chunks.append(text[start:end])
        start = end

    print(f"🔄 共分為 {len(chunks)} 段處理...")

    # 記錄標點分段總數
    if task_id:
        update_task_status(task_id, {
            "punctuation_total_chunks": len(chunks),
            "punctuation_current_chunk": 0
        })

    results = []

    for idx, chunk in enumerate(chunks, 1):
        print(f"   處理第 {idx}/{len(chunks)} 段...")

        # 檢查是否已被取消
        if task_id and task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        # 更新任務進度（顯示當前標點處理段數）
        if task_id:
            update_task_status(task_id, {
                "punctuation_current_chunk": idx,
                "progress": f"正在添加標點符號... (第 {idx}/{len(chunks)} 段)"
            }, persist_to_db=False)

        # 使用語言感知的提示語
        system_msg, user_msg = get_chunked_punctuation_prompt(language, chunk, idx, len(chunks))

        prompt = system_msg + "\n\n" + user_msg
        result, usage = call_gemini_with_retry(prompt, return_usage=True)
        results.append(result)

        # 累積 token 使用量
        if usage:
            total_prompt_tokens += usage['prompt_tokens']
            total_completion_tokens += usage['completion_tokens']
            total_tokens += usage['total_tokens']
            model_used = usage['model']  # 記錄最後使用的模型

    print("✅ 所有段落處理完成，正在合併...")

    # 記錄總 token 使用量到資料庫
    if task_id:
        print(f"📊 總 Token 使用量: {total_tokens} (輸入: {total_prompt_tokens}, 輸出: {total_completion_tokens})")
        update_task_status(task_id, {
            "total_tokens_used": total_tokens,
            "prompt_tokens_used": total_prompt_tokens,
            "completion_tokens_used": total_completion_tokens,
            "llm_model_used": model_used
        })

    return "\n\n".join(results)


def cleanup_old_audio_files(current_task_id: str):
    """清理舊的音檔，保留規則：
    1. 最新的任務（current_task_id）始終保留
    2. 用戶勾選的任務（keep_audio=True）永遠保留（最多 3 個）
    3. 系統最多保留 4 個音檔
    4. 超過 4 個時，從沒有勾選的任務中，按完成時間從最舊的開始刪除

    Args:
        current_task_id: 當前最新任務的 ID

    Note:
        必須在任務狀態更新（設定 audio_file）之後調用
    """
    try:
        print(f"🧹 開始清理舊音檔...")

        # 收集所有已完成且有音檔的任務（從 MongoDB）
        # 記憶體優化：只查詢需要的欄位，限制為 100 個（而非之前的 1000）
        tasks_with_audio = []

        # 使用優化的查詢方法（只返回必要欄位，不載入 segments、transcript 等大型數據）
        all_tasks = run_async_in_thread(task_repo.find_tasks_with_audio(limit=100))

        for task in all_tasks:
            audio_file_path = get_task_field(task, "audio_file")
            if audio_file_path:
                audio_path = Path(audio_file_path)
                completed_at = get_task_field(task, "completed_at") or ""
                keep_audio = task.get("keep_audio", False)
                task_id = task.get("task_id")

                tasks_with_audio.append({
                    "task_id": task_id,
                    "audio_file": audio_path,
                    "completed_at": completed_at,
                    "keep_audio": keep_audio,
                    "is_current": task_id == current_task_id
                })

        # 決定哪些音檔要保留
        files_to_keep = set()

        # 1. 最新的任務始終保留
        if current_task_id:
            files_to_keep.add(current_task_id)
            print(f"   ✓ 保留最新任務音檔：{current_task_id[:8]}...")

        # 2. 用戶勾選保留的任務（keep_audio=True）永遠保留
        keep_audio_tasks = [t for t in tasks_with_audio if t["keep_audio"]]
        for idx, task in enumerate(keep_audio_tasks):
            files_to_keep.add(task["task_id"])
            print(f"   ✓ 保留用戶勾選音檔 #{idx+1}：{task['audio_file'].name}")

        # 3. 如果保留的檔案超過 4 個，需要從沒有勾選的任務中刪除最舊的
        # 系統最多保留 4 個音檔
        MAX_AUDIO_FILES = 4

        if len(files_to_keep) >= MAX_AUDIO_FILES:
            # 已經達到或超過上限，不需要額外保留
            print(f"   當前已保留 {len(files_to_keep)} 個音檔（達到上限）")
        else:
            # 還有空間，可以保留一些未勾選的任務
            # 從未勾選的任務中，按完成時間排序，保留最新的
            uncheckd_tasks = [t for t in tasks_with_audio if not t["keep_audio"] and t["task_id"] not in files_to_keep]
            uncheckd_tasks.sort(key=lambda x: x["completed_at"], reverse=True)

            slots_remaining = MAX_AUDIO_FILES - len(files_to_keep)
            for idx, task in enumerate(uncheckd_tasks[:slots_remaining]):
                files_to_keep.add(task["task_id"])
                print(f"   ✓ 保留未勾選任務 #{idx+1}：{task['audio_file'].name}")

        # 4. 標記要刪除的音檔（所有不在保留清單中的）
        files_to_delete = []
        tasks_to_update = []

        for item in tasks_with_audio:
            if item["task_id"] not in files_to_keep:
                files_to_delete.append(item["audio_file"])
                tasks_to_update.append(item["task_id"])

        if not files_to_delete:
            print(f"   無需清理，當前保留 {len(files_to_keep)} 個音檔")
            return

        # 4. 刪除舊音檔
        deleted_count = 0
        for audio_file in files_to_delete:
            try:
                if audio_file.exists():
                    audio_file.unlink()
                    print(f"   🗑️ 已刪除舊音檔：{audio_file.name}")
                    deleted_count += 1
            except Exception as e:
                print(f"   ⚠️ 刪除音檔失敗 {audio_file.name}：{e}")

        # 5. 更新任務記錄，清除已刪除音檔的引用（在 MongoDB 中）
        if tasks_to_update:
            for tid in tasks_to_update:
                updates = {
                    "audio_file": None,
                    "audio_filename": None,
                    "keep_audio": False,  # 清除保留標記
                    "updated_at": get_current_time()
                }
                run_async_in_thread(update_task_in_db(tid, updates))

            print(f"✅ 清理完成：刪除了 {deleted_count} 個舊音檔，保留 {len(files_to_keep)} 個")

    except Exception as e:
        print(f"⚠️ 清理舊音檔失敗：{e}")
        # 清理失敗不應該影響主流程，所以不拋出異常


def process_transcription_task(
    task_id: str,
    temp_audio_path: Path,
    filename: str,
    punct_provider: str,
    chunk_audio: bool,
    chunk_minutes: int,
    diarize: bool = False,
    max_speakers: Optional[int] = None,
    language: str = "zh",
    user_id: str = None
):
    """
    在背景線程中執行轉錄任務
    這個函數會更新任務狀態，並處理所有轉錄邏輯

    注意：diarization 僅在非分段模式下可用，分段模式會忽略此參數
    max_speakers: 最大講者人數（可選，2-10）
    """
    # 將 'auto' 轉換為 None，讓 Whisper 自動偵測語言
    whisper_language = None if language == "auto" else language

    temp_dir = temp_audio_path.parent

    # 保存音檔到 output 目錄（保留轉換後的 WAV 格式以確保瀏覽器相容性）
    audio_filename = f"{Path(filename).stem}_{task_id}.wav"
    permanent_audio_path = OUTPUT_DIR / audio_filename

    try:
        # 記錄暫存目錄
        with tasks_lock:
            task_temp_dirs[task_id] = temp_dir

        # 初始化記憶體：直接設置 user_id，避免阻塞式 DB 查詢
        if user_id:
            with tasks_lock:
                if task_id not in transcription_tasks:
                    transcription_tasks[task_id] = {}
                # 儲存 user_id（支援巢狀和扁平兩種格式）
                transcription_tasks[task_id]["user"] = {"user_id": user_id}
                transcription_tasks[task_id]["user_id"] = user_id  # 扁平格式（向後兼容）
            print(f"📥 [{task_id}] 初始化記憶體（user_id: {user_id}），之後輪詢將零 DB 查詢")

        # 記錄開始處理時間
        start_time = datetime.now(TZ_UTC8)

        # 更新狀態：處理中
        update_task_status(task_id, {
            "status": "processing",
            "progress": "正在轉換音訊格式...",
            "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S")
        })

        # 檢查是否已被取消
        if task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        # 轉換為 WAV
        wav_path = temp_dir / "input.wav"
        print(f"🔄 [{task_id}] 轉檔為 WAV...")
        try:
            # 明確指定使用 ffmpeg 作為轉檔工具
            audio = AudioSegment.from_file(str(temp_audio_path))
            audio.export(str(wav_path), format="wav")
            # 立即釋放記憶體
            del audio
            import gc
            gc.collect()
        except Exception as e:
            import traceback
            print(f"❌ [{task_id}] 音訊轉檔失敗：{e}")
            print(f"詳細錯誤：\n{traceback.format_exc()}")
            raise

        # 標記音訊轉檔完成
        update_task_status(task_id, {
            "audio_converted": True,
            "progress": "音訊轉檔完成，準備轉錄..."
        })

        # 提前刪除原始上傳檔案，節省磁碟空間（已轉換為 WAV，不再需要）
        try:
            if temp_audio_path.exists() and temp_audio_path != wav_path:
                temp_audio_path.unlink()
                print(f"🗑️  [{task_id}] 已刪除原始上傳檔案：{temp_audio_path.name}")
        except Exception as e:
            print(f"⚠️  [{task_id}] 刪除原始檔案失敗（不影響處理）：{e}")

        # 檢查是否已被取消
        if task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        # 執行轉錄
        update_task_status(task_id, {"progress": "正在轉錄音訊..."})

        all_segments = []  # 用於儲存所有 segments
        detected_language = None  # 用於儲存 Whisper 偵測到的語言

        if chunk_audio:
            # 分段模式：現在支援 diarization（先對完整音檔做說話者辨識，再分段轉錄）
            chunk_duration_ms = chunk_minutes * 60 * 1000
            raw_text, all_segments, detected_language = transcribe_audio_in_chunks(
                wav_path,
                whisper_model,
                chunk_duration_ms,
                task_id=task_id,
                diarize=diarize,
                max_speakers=max_speakers,
                language=whisper_language
            )
        else:
            # 非分段模式：可以使用 diarization
            if diarize and diarization_pipeline:
                print(f"🔊 [{task_id}] 啟用 speaker diarization...")

                # 執行 speaker diarization
                diarization_start = datetime.now(TZ_UTC8)
                update_task_status(task_id, {
                    "progress": "正在分析說話者...",
                    "diarization_status": "running"
                })
                diarization_segments = perform_diarization(wav_path, max_speakers=max_speakers)
                diarization_duration = (datetime.now(TZ_UTC8) - diarization_start).total_seconds()

                # 執行轉錄（帶時間戳）
                update_task_status(task_id, {"progress": "正在轉錄音訊（帶時間戳）..."})
                transcription_segments, detected_language = transcribe_with_timestamps(whisper_model, wav_path, language=whisper_language)
                all_segments = transcription_segments  # 保存 segments

                # 合併結果
                if diarization_segments:
                    num_speakers = len(set(s['speaker'] for s in diarization_segments))
                    update_task_status(task_id, {
                        "progress": "正在合併說話者資訊...",
                        "diarization_status": "completed",
                        "diarization_num_speakers": num_speakers,
                        "diarization_duration_seconds": round(diarization_duration, 1)
                    })
                    raw_text = merge_transcription_with_diarization(
                        transcription_segments,
                        diarization_segments
                    )
                else:
                    # diarization 失敗，回退到純文字
                    update_task_status(task_id, {
                        "diarization_status": "failed"
                    })
                    raw_text = " ".join(seg["text"] for seg in transcription_segments)
            else:
                print(f"📝 [{task_id}] 開始轉逐字稿...")
                raw_text, all_segments, detected_language = transcribe_single_chunk(whisper_model, wav_path, language=whisper_language)

        # 檢查是否已被取消
        if task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        print(f"✅ [{task_id}] 轉錄完成（{len(raw_text)} 字）")

        # 決定使用哪個語言進行標點處理
        # 如果用戶選擇 auto，使用 Whisper 偵測的語言；否則使用用戶指定的語言
        punct_language = detected_language if language == "auto" and detected_language else language
        if detected_language and language == "auto":
            print(f"🔍 [{task_id}] Whisper 偵測到的語言：{detected_language}")

        # 加標點
        final_text = raw_text
        if punct_provider == "gemini":
            try:
                update_task_status(task_id, {
                    "punctuation_started": True,
                    "progress": "正在添加標點符號（Gemini）..."
                })
                print(f"✨ [{task_id}] 使用 Gemini 加標點與分段（語言：{punct_language}）...")
                final_text = punctuate_with_gemini(raw_text, task_id=task_id, language=punct_language)
                update_task_status(task_id, {"punctuation_completed": True})
            except Exception as e:
                print(f"⚠️ [{task_id}] Gemini 加標點失敗：{e}")
                print(f"📝 [{task_id}] 將使用 Whisper 原始轉錄結果")
                update_task_status(task_id, {
                    "punctuation_completed": False,
                    "punctuation_error": str(e),
                    "progress": "標點符號添加失敗，使用原始轉錄結果"
                })
        elif punct_provider == "openai":
            try:
                update_task_status(task_id, {
                    "punctuation_started": True,
                    "progress": "正在添加標點符號（OpenAI）..."
                })
                if not os.getenv("OPENAI_API_KEY"):
                    raise ValueError("未設定 OPENAI_API_KEY")
                print(f"✨ [{task_id}] 使用 OpenAI 加標點與分段（語言：{punct_language}）...")
                final_text = punctuate_with_openai(raw_text, language=punct_language)
                update_task_status(task_id, {"punctuation_completed": True})
            except Exception as e:
                print(f"⚠️ [{task_id}] OpenAI 加標點失敗：{e}")
                print(f"📝 [{task_id}] 將使用 Whisper 原始轉錄結果")
                update_task_status(task_id, {
                    "punctuation_completed": False,
                    "punctuation_error": str(e),
                    "progress": "標點符號添加失敗，使用原始轉錄結果"
                })

        print(f"🎉 [{task_id}] 處理完成！")

        # 保存文字檔到 output/ 目錄
        update_task_status(task_id, {"progress": "正在保存結果..."})
        timestamp = datetime.now(TZ_UTC8).strftime("%Y%m%d_%H%M%S")
        safe_filename = Path(filename).stem.replace(" ", "_")
        output_filename = f"{safe_filename}_{timestamp}_transcript.txt"
        permanent_output = OUTPUT_DIR / output_filename
        permanent_output.write_text(final_text, encoding="utf-8")
        print(f"💾 [{task_id}] 文字檔已保存：{permanent_output.relative_to(OUTPUT_DIR.parent)}")

        # 保存 segments 到 JSON 檔案
        segments_filename = f"{safe_filename}_{timestamp}_segments.json"
        segments_output = OUTPUT_DIR / segments_filename
        segments_output.write_text(json.dumps(all_segments, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📊 [{task_id}] Segments 已保存：{segments_output.relative_to(OUTPUT_DIR.parent)}")

        # 複製 WAV 音檔到 output 目錄（保留以供播放，WAV 格式在瀏覽器中有最佳相容性）
        import shutil
        shutil.copy2(wav_path, permanent_audio_path)
        print(f"🎵 [{task_id}] 音檔已保存（WAV 格式）：{permanent_audio_path.relative_to(OUTPUT_DIR.parent)}")

        # 計算總處理時間
        end_time = datetime.now(TZ_UTC8)
        duration_seconds = (end_time - start_time).total_seconds()

        # 獲取音檔時長（用於配額更新）- 使用 ffprobe 避免記憶體問題
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', str(wav_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                import json
                probe_data = json.loads(result.stdout)
                audio_duration_seconds = float(probe_data['format']['duration'])
            else:
                # 回退到 pydub
                audio = AudioSegment.from_wav(wav_path)
                audio_duration_seconds = len(audio) / 1000.0
                del audio
        except Exception as e:
            print(f"⚠️  [{task_id}] 無法獲取音檔時長：{e}")
            audio_duration_seconds = 0

        # 提前刪除臨時 WAV 檔案，節省磁碟空間（已複製到 output/ 目錄）
        try:
            if wav_path.exists():
                wav_path.unlink()
                print(f"🗑️  [{task_id}] 已刪除臨時 WAV 檔案：{wav_path.name}")
        except Exception as e:
            print(f"⚠️  [{task_id}] 刪除臨時 WAV 失敗（不影響處理）：{e}")

        # 更新狀態：完成
        update_task_status(task_id, {
            "status": "completed",
            "progress": "轉錄完成",
            "result_file": str(permanent_output),
            "result_filename": output_filename,
            "segments_file": str(segments_output),
            "segments_filename": segments_filename,
            "audio_file": str(permanent_audio_path),
            "audio_filename": audio_filename,
            "text_length": len(final_text),
            "completed_at": get_current_time(),
            "duration_seconds": round(duration_seconds, 1),
            "audio_duration_seconds": round(audio_duration_seconds, 1)  # 保存音檔時長
        })

        # 更新用戶配額（異步調用）
        try:
            # 從 MongoDB 獲取任務以取得 user_id
            task = run_async_in_thread(get_task_from_db(task_id))
            user_id = task.get("user_id") if task else None

            if user_id:
                # 在同步線程中運行異步配額更新
                import asyncio
                from src.database.mongodb import MongoDB

                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    db = MongoDB.get_db()
                    loop.run_until_complete(
                        QuotaManager.increment_usage(db, user_id, audio_duration_seconds)
                    )
                    loop.close()
                    print(f"✅ [{task_id}] 配額已更新：+{round(audio_duration_seconds/60, 2)} 分鐘")
                except Exception as quota_err:
                    print(f"⚠️  [{task_id}] 配額更新失敗：{quota_err}")
        except Exception as e:
            print(f"⚠️  [{task_id}] 配額更新過程出錯：{e}")

        # 清理舊的音檔（只保留最新的 3 個）
        # 必須在 update_task_status 之後，這樣當前任務的音檔才會被計入
        cleanup_old_audio_files(task_id)

        print(f"⏱️ [{task_id}] 總處理時間：{format_duration(duration_seconds)}")

    except Exception as e:
        # 檢查是否為取消操作
        is_cancelled = "取消" in str(e)

        if is_cancelled:
            print(f"🛑 [{task_id}] 任務已被使用者取消")
            update_task_status(task_id, {
                "status": "cancelled",
                "progress": "任務已取消",
                "error": "使用者取消了任務"
            })
        else:
            # 更新狀態：失敗
            print(f"❌ [{task_id}] 錯誤：{e}")
            update_task_status(task_id, {
                "status": "failed",
                "progress": f"錯誤：{str(e)}",
                "error": str(e)
            })

    finally:
        # 清理臨時檔案
        cleanup_temp_dir(temp_dir)

        # 清理任務相關記錄
        with tasks_lock:
            task_temp_dirs.pop(task_id, None)
            task_cancelled.pop(task_id, None)
            task_diarization_processes.pop(task_id, None)
            # 確保從 transcription_tasks 中移除（以防 update_task_status 未觸發清理）
            transcription_tasks.pop(task_id, None)

        # 強制垃圾回收以釋放記憶體
        import gc
        gc.collect()
        print(f"🧹 [{task_id}] 記憶體清理完成")


async def periodic_memory_cleanup():
    """定期清理記憶體中的孤立資料（背景任務）"""
    import gc

    while True:
        try:
            # 每 10 分鐘執行一次
            await asyncio.sleep(600)

            print("🧹 執行定期記憶體清理...")

            # 從資料庫查詢所有進行中的任務
            # 記憶體優化：減少查詢數量（100 → 20）並只查詢 task_id
            if task_repo:
                active_task_ids = set()
                active_tasks = await task_repo.collection.find(
                    {"status": {"$in": ["pending", "processing"]}},
                    {"task_id": 1}  # 只查詢 task_id
                ).limit(20).to_list(length=20)

                active_task_ids = {task["task_id"] for task in active_tasks if "task_id" in task}

                # 清理不在進行中列表的記憶體資料
                with tasks_lock:
                    # 清理 transcription_tasks
                    orphaned_tasks = [tid for tid in transcription_tasks.keys() if tid not in active_task_ids]
                    for tid in orphaned_tasks:
                        transcription_tasks.pop(tid, None)
                        print(f"  🗑️  清理孤立任務記憶體: {tid}")

                    # 清理其他字典
                    for tid in list(task_temp_dirs.keys()):
                        if tid not in active_task_ids:
                            task_temp_dirs.pop(tid, None)

                    for tid in list(task_cancelled.keys()):
                        if tid not in active_task_ids:
                            task_cancelled.pop(tid, None)

                    for tid in list(task_diarization_processes.keys()):
                        if tid not in active_task_ids:
                            task_diarization_processes.pop(tid, None)

                # 強制垃圾回收
                gc.collect()

                if orphaned_tasks:
                    print(f"✅ 記憶體清理完成，清除 {len(orphaned_tasks)} 個孤立任務")
                else:
                    print("✅ 記憶體清理完成，無孤立資料")

        except Exception as e:
            print(f"⚠️  定期記憶體清理失敗: {e}")


async def cleanup_orphaned_tasks():
    """清理異常中斷的任務（程式重啟時執行）"""
    if task_repo is None:
        return

    try:
        # 查找所有處於 pending 或 processing 狀態的任務
        # 記憶體優化：限制數量並只查詢需要的欄位
        orphaned_tasks = await task_repo.collection.find(
            {"status": {"$in": ["pending", "processing"]}},
            {"_id": 1, "task_id": 1, "status": 1, "timestamps": 1}  # 只查詢需要的欄位
        ).limit(50).to_list(length=50)  # 限制最多 50 個

        if not orphaned_tasks:
            print("✅ 沒有發現異常中斷的任務")
            return

        print(f"⚠️  發現 {len(orphaned_tasks)} 個異常中斷的任務，正在清理...")

        # 將這些任務標記為失敗
        current_time = get_current_time()
        for task in orphaned_tasks:
            task_id = task.get("task_id", "unknown")

            # 更新任務狀態
            update_data = {
                "status": "failed",
                "progress": "伺服器重啟，任務已中斷",
                "error": "任務執行期間伺服器重啟，任務已被標記為失敗"
            }

            # 支援巢狀結構的時間戳更新
            if "timestamps" in task:
                update_data["timestamps.updated_at"] = current_time
                update_data["timestamps.completed_at"] = current_time
            else:
                update_data["updated_at"] = current_time
                update_data["completed_at"] = current_time

            await task_repo.collection.update_one(
                {"_id": task["_id"]},
                {"$set": update_data}
            )
            print(f"   ✓ 任務 {task_id} 已標記為失敗")

        print(f"✅ 已清理 {len(orphaned_tasks)} 個異常中斷的任務")

    except Exception as e:
        print(f"❌ 清理異常中斷任務時發生錯誤：{e}")


# ---------- API Endpoints ----------

@app.on_event("startup")
async def startup_event():
    """啟動時載入 Whisper 模型和任務記錄"""
    global whisper_model, current_model_name, task_repo, main_loop

    # 獲取主事件循環
    main_loop = asyncio.get_running_loop()

    # 連接 MongoDB
    print(f"🔌 正在連接 MongoDB...")
    try:
        await MongoDB.connect()
        print(f"✅ 已連接到 MongoDB: {os.getenv('MONGODB_DB_NAME', 'whisper_transcriber')}")
    except Exception as e:
        print(f"❌ MongoDB 連接失敗: {e}")
        print(f"   請確保 MongoDB 正在運行並檢查 .env 配置")
        raise

    # 初始化 TaskRepository 和 TagRepository
    print(f"📂 正在初始化任務資料庫...")
    db = MongoDB.get_db()
    global task_repo, tag_repo
    task_repo = TaskRepository(db)
    tag_repo = TagRepository(db)

    # 建立索引（如果尚未建立）
    try:
        await task_repo.create_indexes()
        print(f"✅ 任務資料庫索引建立完成")
    except Exception as e:
        print(f"⚠️  索引建立失敗: {e}")

    # 統計任務數量
    task_count = await db.tasks.count_documents({})
    print(f"✅ 任務資料庫已就緒（共 {task_count} 個任務）")

    # 清理異常中斷的任務
    await cleanup_orphaned_tasks()

    # 啟動定期記憶體清理任務（每 10 分鐘執行一次）
    asyncio.create_task(periodic_memory_cleanup())

    # 載入標籤設定
    load_tag_settings()

    # 載入 Faster-Whisper 模型
    current_model_name = DEFAULT_MODEL
    print(f"🎙 正在載入 Faster-Whisper 模型：{current_model_name}...")
    print(f"🔧 配置：device=auto, compute_type=int8（針對 M1 優化）")
    whisper_model = WhisperModel(
        current_model_name,
        device="auto",  # 自動選擇 CPU
        compute_type="int8",  # 使用 INT8 量化，節省記憶體並提升速度
        cpu_threads=1,  # 每個推理任務用 1 線程（避免與 diarization 競爭）
        num_workers=4  # 允許 4 個任務同時推理
    )
    print(f"✅ 模型載入完成，服務已就緒！")

    # 載入 Speaker Diarization 模型（可選）
    global diarization_pipeline
    diarization_pipeline = None

    if DIARIZATION_AVAILABLE:
        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            try:
                # 使用 huggingface_hub 登入
                from huggingface_hub import login
                login(token=hf_token, add_to_git_credential=False)

                print("🔊 正在載入 Speaker Diarization 模型...")
                import torch
                diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1"
                )

                # M1 Mac MPS 加速
                if torch.backends.mps.is_available():
                    diarization_pipeline.to(torch.device("mps"))
                    print("✅ Speaker Diarization 模型載入完成（使用 MPS 加速）！")
                else:
                    print("✅ Speaker Diarization 模型載入完成！")
            except Exception as e:
                print(f"⚠️  Speaker Diarization 模型載入失敗：{e}")
                print("   請確認已在 Hugging Face 同意使用條款：https://huggingface.co/pyannote/speaker-diarization-3.1")
        else:
            print("ℹ️  未設定 HF_TOKEN，speaker diarization 功能不可用")
            print("   如需使用，請：")
            print("   1. 訪問 https://huggingface.co/settings/tokens")
            print("   2. 創建 access token")
            print("   3. 在 .env 添加：HF_TOKEN=your_token_here")


@app.on_event("shutdown")
async def shutdown_event():
    """關閉時斷開 MongoDB 連接"""
    print(f"🔌 正在關閉 MongoDB 連接...")
    await MongoDB.close()


@app.get("/")
async def root():
    """服務狀態"""
    # 從 MongoDB 查詢活躍任務數量
    from src.database.mongodb import MongoDB
    db = MongoDB.get_db()
    active_count = await db.tasks.count_documents({
        "status": {"$in": ["pending", "processing"]}
    })

    return {
        "service": "Whisper 轉錄服務",
        "version": "2.0.0",
        "status": "running",
        "model": current_model_name,
        "output_dir": str(OUTPUT_DIR.relative_to(OUTPUT_DIR.parent)),
        "concurrent_limit": executor._max_workers,
        "active_transcriptions": active_count,
        "endpoints": {
            "POST /transcribe": "上傳音檔進行轉錄（異步，立即返回 task_id）",
            "GET /transcribe/{task_id}": "查詢任務狀態",
            "GET /transcribe/{task_id}/download": "下載轉錄結果",
            "GET /transcribe/active/list": "列出所有任務（含進行中）",
            "GET /transcripts": "列出已保存的文字檔",
            "GET /health": "健康檢查",
            "GET /docs": "Swagger API 文檔"
        }
    }


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(..., description="音檔 (支援 mp3/m4a/wav/mp4 等格式)"),
    punct_provider: str = Form("gemini", description="標點提供者 (openai/gemini/none)"),
    chunk_audio: bool = Form(True, description="是否使用分段模式"),
    chunk_minutes: int = Form(10, description="分段長度（分鐘）"),
    diarize: bool = Form(False, description="是否啟用說話者辨識"),
    max_speakers: Optional[int] = Form(None, description="最大講者人數（可選，2-10）"),
    language: str = Form("zh", description="轉錄語言 (zh/en/ja/ko/auto)"),
    tags: Optional[str] = Form(None, description="標籤（JSON 陣列字串，如 '[\"環宇專案\",\"2025\"]'）"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_database)
):
    """
    上傳音檔進行轉錄（異步模式）

    立即返回任務 ID，轉錄在背景執行
    使用 GET /transcribe/{task_id} 查詢狀態
    使用 GET /transcribe/{task_id}/download 下載結果

    - **file**: 音檔檔案
    - **punct_provider**: 標點提供者 (openai/gemini/none)
    - **chunk_audio**: 是否使用分段模式（長音檔建議開啟）
    - **chunk_minutes**: 分段長度（分鐘）
    - **diarize**: 是否啟用說話者辨識（speaker diarization）
    - **max_speakers**: 最大講者人數（可選，2-10，留空則自動偵測）
    """
    global whisper_model

    if not whisper_model:
        raise HTTPException(status_code=503, detail="模型尚未載入完成")

    # 生成任務 ID
    task_id = str(uuid.uuid4())

    # 建立臨時目錄並保存上傳的檔案
    temp_dir = Path(tempfile.mkdtemp())
    file_suffix = Path(file.filename).suffix
    temp_audio = temp_dir / f"input{file_suffix}"

    try:
        with temp_audio.open("wb") as f:
            content = await file.read()
            f.write(content)

        print(f"📁 收到檔案：{file.filename} ({len(content) / 1024 / 1024:.2f} MB)")

        # 檢查 diarization 可用性
        if diarize and not diarization_pipeline:
            raise HTTPException(
                status_code=400,
                detail="Speaker diarization 功能未啟用。請設定 HF_TOKEN 環境變數並重啟服務。"
            )

        # 解析標籤（如果有提供）
        task_tags = []
        if tags:
            try:
                import json
                task_tags = json.loads(tags)
            except:
                task_tags = []

        # 創建任務記錄到 MongoDB（巢狀結構）
        current_time = get_current_time()
        task_data = {
            "_id": task_id,  # 使用 task_id 作為 _id
            "task_id": task_id,

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

            # 使用者設定與標籤
            "tags": task_tags,
            "keep_audio": False,

            # 時間戳記
            "timestamps": {
                "created_at": current_time,
                "updated_at": current_time,
                "started_at": None,
                "completed_at": None
            }
        }

        # 保存到 MongoDB
        await task_repo.create(task_data)
        print(f"✅ [{task_id}] 任務已建立到 MongoDB")

        # 在背景線程中執行轉錄
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            executor,
            process_transcription_task,
            task_id,
            temp_audio,
            file.filename,
            punct_provider,
            chunk_audio,
            chunk_minutes,
            diarize,
            max_speakers,
            language,
            str(current_user["_id"])  # 傳遞 user_id
        )

        # 立即返回任務資訊
        return JSONResponse({
            "task_id": task_id,
            "status": "pending",
            "message": "轉錄任務已提交，請使用 task_id 查詢狀態",
            "filename": file.filename,
            "created_at": get_task_field(task_data, "created_at"),
            "status_url": f"/transcribe/{task_id}",
            "download_url": f"/transcribe/{task_id}/download"
        })

    except Exception as e:
        # 發生錯誤時清理
        cleanup_temp_dir(temp_dir)
        print(f"❌ 提交任務失敗：{e}")
        raise HTTPException(status_code=500, detail=f"提交任務失敗：{str(e)}")


@app.get("/transcribe/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """查詢轉錄任務狀態（需認證，只能查看自己的任務）"""

    # 完全記憶體模式：進行中任務零 DB 查詢（像 main 分支一樣）
    with tasks_lock:
        live_task_info = transcription_tasks.get(task_id)

    # 如果任務在記憶體中（正在處理），完全使用記憶體數據
    if live_task_info:
        # 權限驗證：檢查記憶體中的 user_id
        task_user_id = live_task_info.get("user_id") or live_task_info.get("user", {}).get("user_id")
        if task_user_id != str(current_user["_id"]):
            raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

        # 直接使用記憶體數據，零 DB 查詢！
        task_in_db = live_task_info
        print(f"⚡ [{task_id}] 從記憶體返回（零 DB 查詢）")
    else:
        # 任務不在記憶體中（已完成或不存在），查詢 MongoDB
        task_in_db = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

        if not task_in_db:
            raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

        print(f"💾 [{task_id}] 從 MongoDB 返回（已完成任務）")

    # 不需要再合併即時資訊（已經在記憶體數據中了）
    if False and task_in_db.get("status") in ["processing", "pending"] and live_task_info:
        # 將記憶體中的 'progress' 等即時欄位，更新到從資料庫取出的物件上
        task_in_db["progress"] = live_task_info.get("progress", task_in_db.get("progress"))
        
        diarization_status = live_task_info.get("diarization_status")
        if diarization_status:
            task_in_db["diarization_status"] = diarization_status

    # 4. 使用 enrich_task_data 函數添加其他計算欄位 (保留現有邏輯)
    enriched_task_dict = enrich_task_data(task_in_db)

    # 5. 回傳原始字典以避免 Pydantic 驗證錯誤
    return enriched_task_dict


@app.get("/transcribe/{task_id}/download")
async def download_task_result(
    task_id: str,
    current_user: dict = Depends(check_quota)
):
    """下載轉錄結果（需認證，只能下載自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"任務尚未完成（當前狀態：{task['status']}）"
        )

    result_file_path = get_task_field(task, "result_file")
    if not result_file_path:
        raise HTTPException(status_code=404, detail="結果檔案不存在")

    result_file = Path(result_file_path)
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="結果檔案不存在")

    # 使用自訂名稱作為下載檔名（如果有設定），否則使用原始檔名
    if task.get("custom_name"):
        download_filename = task["custom_name"]
        # 移除常見的音訊副檔名
        import os
        name_without_ext = download_filename
        for ext in ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma']:
            if download_filename.lower().endswith(ext):
                name_without_ext = download_filename[:-len(ext)]
                break
        # 確保檔名有 .txt 副檔名
        if not name_without_ext.endswith('.txt'):
            download_filename = name_without_ext + '.txt'
        else:
            download_filename = name_without_ext
    else:
        download_filename = get_task_field(task, "result_filename") or "result.txt"

    return FileResponse(
        result_file,
        media_type="text/plain",
        filename=download_filename,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


@app.get("/transcribe/{task_id}/audio")
async def get_task_audio(
    task_id: str,
    current_user: dict = Depends(check_quota)
):
    """獲取任務的音檔（需認證，只能訪問自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"任務尚未完成（當前狀態：{task['status']}）"
        )

    # 檢查是否有音檔
    audio_file_path = get_task_field(task, "audio_file")
    if not audio_file_path:
        raise HTTPException(status_code=404, detail="此任務沒有保存音檔（可能是較舊的任務）")

    audio_file = Path(audio_file_path)
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="音檔不存在")

    # 根據檔案副檔名決定 media type
    suffix = audio_file.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac"
    }
    media_type = media_types.get(suffix, "audio/mpeg")

    audio_filename = get_task_field(task, "audio_filename") or ("audio" + suffix)
    return FileResponse(
        audio_file,
        media_type=media_type,
        filename=audio_filename
    )


@app.get("/transcribe/{task_id}/segments")
async def get_task_segments(
    task_id: str,
    current_user: dict = Depends(check_quota)
):
    """獲取任務的 segments timing 數據（需認證，只能訪問自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"任務尚未完成（當前狀態：{task['status']}）"
        )

    # 檢查是否有 segments 檔案
    segments_file_path = get_task_field(task, "segments_file")
    if not segments_file_path:
        raise HTTPException(status_code=404, detail="此任務沒有 segments 數據（可能是較舊的任務）")

    segments_file = Path(segments_file_path)
    if not segments_file.exists():
        raise HTTPException(status_code=404, detail="Segments 檔案不存在")

    try:
        segments_data = json.loads(segments_file.read_text(encoding="utf-8"))
        return JSONResponse({"segments": segments_data})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"讀取 segments 失敗：{str(e)}")


@app.put("/transcribe/{task_id}/content")
async def update_transcript_content(
    task_id: str,
    update_data: TranscriptContentUpdate,
    current_user: dict = Depends(get_current_user)
):
    """更新逐字稿內容（需認證，只能編輯自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"任務尚未完成，無法編輯（當前狀態：{task['status']}）"
        )

    result_file_path = get_task_field(task, "result_file")
    if not result_file_path:
        raise HTTPException(status_code=404, detail="結果檔案不存在")

    result_file = Path(result_file_path)
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="結果檔案不存在")

    # 獲取新內容
    new_content = update_data.content
    if not new_content:
        raise HTTPException(status_code=400, detail="內容不能為空")

    try:
        # 除錯：顯示檔案路徑和內容前100字
        print(f"📝 [{task_id}] 準備更新檔案：{result_file}")
        print(f"   新內容前100字：{new_content[:100]}")

        # 保存新內容到檔案
        result_file.write_text(new_content, encoding="utf-8")

        # 除錯：驗證檔案是否真的被更新
        saved_content = result_file.read_text(encoding="utf-8")
        print(f"   檔案已更新，驗證前100字：{saved_content[:100]}")

        # 更新資料庫中的任務記錄
        await task_repo.update_content(task_id, str(current_user["_id"]), new_content)

        print(f"✅ [{task_id}] 逐字稿已更新（新長度：{len(new_content)} 字）")

        return {
            "message": "逐字稿已成功更新",
            "task_id": task_id,
            "text_length": len(new_content)
        }

    except Exception as e:
        print(f"❌ [{task_id}] 更新逐字稿失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.put("/transcribe/{task_id}/metadata")
async def update_task_metadata(
    task_id: str,
    metadata: TaskMetadataUpdate,
    current_user: dict = Depends(get_current_user)
):
    """更新任務的自訂名稱（需認證，只能編輯自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    try:
        # 更新資料庫中的任務元數據
        success = await task_repo.update_metadata(
            task_id,
            str(current_user["_id"]),
            custom_name=metadata.custom_name
        )

        if not success:
            raise HTTPException(status_code=500, detail="更新失敗")

        print(f"📝 [{task_id}] 更新自訂名稱：{metadata.custom_name}")

        # 獲取更新後的任務
        updated_task = await task_repo.get_by_id(task_id)

        return {
            "message": "任務名稱已更新",
            "task_id": task_id,
            "custom_name": updated_task.get("custom_name")
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [{task_id}] 更新任務名稱失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.put("/transcribe/{task_id}")
async def update_task_tags(
    task_id: str,
    tag_update: TaskTagsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """更新任務的標籤（需認證，只能編輯自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    try:
        # 更新資料庫中的任務標籤
        success = await task_repo.update_tags(
            task_id,
            str(current_user["_id"]),
            tag_update.tags
        )

        if not success:
            raise HTTPException(status_code=500, detail="更新失敗")

        print(f"🏷️  [{task_id}] 更新標籤：{tag_update.tags}")

        return {
            "message": "標籤已更新",
            "task_id": task_id,
            "tags": tag_update.tags
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [{task_id}] 更新標籤失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.put("/transcribe/{task_id}/keep-audio")
async def update_keep_audio(
    task_id: str,
    keep_audio_update: KeepAudioUpdate,
    current_user: dict = Depends(get_current_user)
):
    """更新任務的音檔保留狀態（需認證，只能編輯自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    # 檢查任務是否有音檔
    audio_file_path = get_task_field(task, "audio_file")
    if task.get("status") != "completed" or not audio_file_path:
        raise HTTPException(status_code=400, detail="此任務沒有音檔可以保留")

    try:
        # 如果要設置為 True，檢查已勾選的數量
        if keep_audio_update.keep_audio:
            # 計算當前有多少個任務被標記為保留音檔
            current_keep_count = await task_repo.count_keep_audio_tasks(str(current_user["_id"]))

            # 檢查當前任務是否已經勾選
            if not task.get("keep_audio", False):
                # 如果當前任務還沒勾選，則需要檢查是否超過限制
                if current_keep_count >= 3:
                    raise HTTPException(status_code=400, detail="最多只能勾選 3 個音檔保留")

        # 更新資料庫中的音檔保留狀態
        success = await task_repo.update_keep_audio(
            task_id,
            str(current_user["_id"]),
            keep_audio_update.keep_audio
        )

        if not success:
            raise HTTPException(status_code=500, detail="更新失敗")

        print(f"📌 [{task_id}] 更新音檔保留狀態：{keep_audio_update.keep_audio}")

        return {
            "message": "音檔保留狀態已更新",
            "task_id": task_id,
            "keep_audio": keep_audio_update.keep_audio
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [{task_id}] 更新音檔保留狀態失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.get("/tags")
async def get_all_tags(current_user: dict = Depends(get_current_user)):
    """獲取當前用戶的所有標籤及其顏色（需認證）"""
    # 從 MongoDB 獲取用戶的所有標籤
    user_tags = await task_repo.get_all_user_tags(str(current_user["_id"]))

    # 返回標籤及其顏色
    tags_with_colors = []
    for tag in sorted(user_tags):
        tags_with_colors.append({
            "name": tag,
            "color": tag_colors.get(tag, None)  # 如果沒有設定顏色則為 None
        })

    return {
        "tags": tags_with_colors,
        "count": len(tags_with_colors)
    }


@app.put("/tags/{tag_name}/color")
async def update_tag_color(tag_name: str, color_update: TagColorUpdate):
    """更新標籤的顏色"""
    try:
        tag_colors[tag_name] = color_update.color
        print(f"🎨 更新標籤顏色：{tag_name} -> {color_update.color}")

        # 保存到磁碟
        save_tag_settings()

        return {
            "message": "標籤顏色已更新",
            "tag": tag_name,
            "color": color_update.color
        }

    except Exception as e:
        print(f"❌ 更新標籤顏色失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.get("/tags/order")
async def get_tag_order():
    """獲取標籤順序"""
    return {
        "order": tag_order,
        "count": len(tag_order)
    }


@app.put("/tags/order")
async def update_tag_order(order_update: TagOrderUpdate):
    """更新標籤順序"""
    try:
        global tag_order
        tag_order = order_update.order
        print(f"📋 更新標籤順序：{len(tag_order)} 個標籤")

        # 保存到磁碟
        save_tag_settings()

        return {
            "message": "標籤順序已更新",
            "order": tag_order,
            "count": len(tag_order)
        }

    except Exception as e:
        print(f"❌ 更新標籤順序失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


# ==================== 新的 Tag CRUD API（基於ID的標籤管理） ====================

@app.post("/api/tags", response_model=TagResponse, status_code=201)
async def create_tag(
    tag_data: TagCreate,
    current_user: dict = Depends(get_current_user)
):
    """建立新標籤（需認證）"""
    try:
        tag = await tag_repo.create(
            user_id=str(current_user["_id"]),
            name=tag_data.name,
            color=tag_data.color
        )
        return TagResponse(**tag)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"❌ 建立標籤失敗：{e}")
        raise HTTPException(status_code=500, detail=f"建立失敗：{str(e)}")


@app.get("/api/tags", response_model=List[TagResponse])
async def get_all_tags_new(current_user: dict = Depends(get_current_user)):
    """獲取當前用戶的所有標籤（需認證）"""
    try:
        tags = await tag_repo.get_all_by_user(str(current_user["_id"]))
        return [TagResponse(**tag) for tag in tags]
    except Exception as e:
        print(f"❌ 獲取標籤失敗：{e}")
        raise HTTPException(status_code=500, detail=f"獲取失敗：{str(e)}")


@app.get("/api/tags/{tag_id}", response_model=TagResponse)
async def get_tag(
    tag_id: str,
    current_user: dict = Depends(get_current_user)
):
    """獲取單個標籤（需認證）"""
    tag = await tag_repo.get_by_id(tag_id, str(current_user["_id"]))
    if not tag:
        raise HTTPException(status_code=404, detail="標籤不存在或無權訪問")
    return TagResponse(**tag)


@app.put("/api/tags/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: str,
    tag_data: TagUpdate,
    current_user: dict = Depends(get_current_user)
):
    """更新標籤（需認證）"""
    try:
        # 如果要更新名稱，需要同步更新所有使用該標籤的任務
        old_tag = await tag_repo.get_by_id(tag_id, str(current_user["_id"]))
        if not old_tag:
            raise HTTPException(status_code=404, detail="標籤不存在或無權訪問")

        # 更新標籤
        success = await tag_repo.update(
            tag_id=tag_id,
            user_id=str(current_user["_id"]),
            name=tag_data.name,
            color=tag_data.color
        )

        if not success:
            raise HTTPException(status_code=500, detail="更新失敗")

        # 如果名稱有變更，更新所有任務中的標籤
        if tag_data.name and tag_data.name != old_tag["name"]:
            db = MongoDB.get_db()
            updated_tasks = await tag_repo.rename_tag_in_tasks(
                user_id=str(current_user["_id"]),
                old_name=old_tag["name"],
                new_name=tag_data.name,
                tasks_collection=db.tasks
            )
            print(f"📝 已更新 {updated_tasks} 個任務中的標籤名稱")

        # 返回更新後的標籤
        updated_tag = await tag_repo.get_by_id(tag_id, str(current_user["_id"]))
        return TagResponse(**updated_tag)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 更新標籤失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.delete("/api/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: str,
    current_user: dict = Depends(get_current_user)
):
    """刪除標籤（需認證，會從所有任務中移除）"""
    try:
        # 獲取標籤資訊
        tag = await tag_repo.get_by_id(tag_id, str(current_user["_id"]))
        if not tag:
            raise HTTPException(status_code=404, detail="標籤不存在或無權訪問")

        # 從所有任務中移除該標籤
        db = MongoDB.get_db()
        updated_tasks = await tag_repo.remove_tag_from_tasks(
            user_id=str(current_user["_id"]),
            tag_name=tag["name"],
            tasks_collection=db.tasks
        )
        print(f"📝 已從 {updated_tasks} 個任務中移除標籤")

        # 刪除標籤
        success = await tag_repo.delete(tag_id, str(current_user["_id"]))
        if not success:
            raise HTTPException(status_code=500, detail="刪除失敗")

        return None

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 刪除標籤失敗：{e}")
        raise HTTPException(status_code=500, detail=f"刪除失敗：{str(e)}")


@app.put("/api/tags/order")
async def update_tags_order(
    order_data: TagOrderUpdateModel,
    current_user: dict = Depends(get_current_user)
):
    """更新標籤順序（需認證）"""
    try:
        updated_count = await tag_repo.update_order(
            user_id=str(current_user["_id"]),
            tag_ids=order_data.tag_ids
        )

        return {
            "message": "標籤順序已更新",
            "updated_count": updated_count
        }

    except Exception as e:
        print(f"❌ 更新標籤順序失敗：{e}")
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@app.post("/transcribe/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """取消正在執行的任務（需認證，只能取消自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    # 只能取消進行中或等待中的任務
    if task["status"] not in ["pending", "processing"]:
        raise HTTPException(
            status_code=400,
            detail=f"無法取消已結束的任務（當前狀態：{task['status']}）"
        )

    # 標記任務為已取消（運行時狀態）
    task_cancelled[task_id] = True

    # 立即終止 diarization 進程（如果正在運行）
    diarization_executor = task_diarization_processes.get(task_id)
    if diarization_executor:
        print(f"🛑 正在強制終止說話者辨識進程...")
        try:
            diarization_executor.shutdown(wait=False, cancel_futures=True)
            print(f"✅ 說話者辨識進程已終止")
        except Exception as e:
            print(f"⚠️ 終止 diarization 進程失敗：{e}")
        task_diarization_processes.pop(task_id, None)

    # 立即清理暫存目錄（如果存在）
    temp_dir = task_temp_dirs.get(task_id)
    if temp_dir:
        cleanup_temp_dir(temp_dir)
        task_temp_dirs.pop(task_id, None)

    # 更新資料庫中的任務狀態
    await task_repo.mark_as_cancelled(task_id, str(current_user["_id"]))

    print(f"🛑 任務 {task_id} 已被標記為取消")

    return {
        "message": "任務取消指令已發送",
        "task_id": task_id,
        "note": "任務將在當前步驟完成後停止"
    }


@app.delete("/transcribe/{task_id}")
async def delete_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """刪除任務及其相關檔案（需認證，只能刪除自己的任務）"""
    # 從 MongoDB 獲取任務（含權限檢查）
    task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在或無權訪問")

    # 不允許刪除進行中的任務
    if task["status"] in ["pending", "processing"]:
        raise HTTPException(
            status_code=400,
            detail=f"無法刪除進行中的任務（當前狀態：{task['status']}），請先取消任務"
        )

    deleted_files = []

    # 刪除結果檔案（如果存在）
    result_file_path = get_task_field(task, "result_file")
    if task["status"] == "completed" and result_file_path:
        result_file = Path(result_file_path)
        try:
            if result_file.exists():
                result_file.unlink()
                deleted_files.append(result_file.name)
                print(f"🗑️ 已刪除轉錄檔案：{result_file.name}")
        except Exception as e:
            print(f"⚠️ 刪除轉錄檔案失敗：{e}")

    # 刪除 segments 檔案（如果存在）
    segments_file_path = get_task_field(task, "segments_file")
    if task["status"] == "completed" and segments_file_path:
        segments_file = Path(segments_file_path)
        try:
            if segments_file.exists():
                segments_file.unlink()
                deleted_files.append(segments_file.name)
                print(f"🗑️ 已刪除 segments 檔案：{segments_file.name}")
        except Exception as e:
            print(f"⚠️ 刪除 segments 檔案失敗：{e}")

    # 刪除音檔（如果存在）
    audio_file_path = get_task_field(task, "audio_file")
    if task["status"] == "completed" and audio_file_path:
        audio_file = Path(audio_file_path)
        try:
            if audio_file.exists():
                audio_file.unlink()
                deleted_files.append(audio_file.name)
                print(f"🗑️ 已刪除音檔：{audio_file.name}")
        except Exception as e:
            print(f"⚠️ 刪除音檔失敗：{e}")

    # 從資料庫中刪除任務
    await task_repo.delete(task_id, str(current_user["_id"]))

    return {
        "message": "任務已刪除",
        "task_id": task_id,
        "deleted_files": deleted_files
    }


@app.post("/transcribe/batch/delete")
async def batch_delete_tasks(
    request: BatchDeleteRequest,
    current_user: dict = Depends(get_current_user)
):
    """批次刪除任務（需認證，只能刪除自己的任務）"""
    # 先獲取要刪除的任務以刪除相關檔案
    tasks_to_delete = []
    for task_id in request.task_ids:
        task = await task_repo.get_by_id_and_user(task_id, str(current_user["_id"]))
        if task:
            tasks_to_delete.append(task)

    # 刪除相關檔案
    deleted_files_map = {}
    for task in tasks_to_delete:
        task_id = task["_id"]
        deleted_files = []

        # 刪除結果檔案
        result_file_path = get_task_field(task, "result_file")
        if task["status"] == "completed" and result_file_path:
            result_file = Path(result_file_path)
            try:
                if result_file.exists():
                    result_file.unlink()
                    deleted_files.append(result_file.name)
            except Exception as e:
                print(f"⚠️ 刪除轉錄檔案失敗：{e}")

        # 刪除 segments 檔案
        segments_file_path = get_task_field(task, "segments_file")
        if task["status"] == "completed" and segments_file_path:
            segments_file = Path(segments_file_path)
            try:
                if segments_file.exists():
                    segments_file.unlink()
                    deleted_files.append(segments_file.name)
            except Exception as e:
                print(f"⚠️ 刪除 segments 檔案失敗：{e}")

        # 刪除音檔
        audio_file_path = get_task_field(task, "audio_file")
        if task["status"] == "completed" and audio_file_path:
            audio_file = Path(audio_file_path)
            try:
                if audio_file.exists():
                    audio_file.unlink()
                    deleted_files.append(audio_file.name)
            except Exception as e:
                print(f"⚠️ 刪除音檔失敗：{e}")

        deleted_files_map[task_id] = deleted_files

    # 從資料庫批次刪除任務
    deleted_count, deleted_ids = await task_repo.bulk_delete(
        request.task_ids,
        str(current_user["_id"])
    )

    # 組織返回結果
    deleted_tasks = [
        {"task_id": task_id, "deleted_files": deleted_files_map.get(task_id, [])}
        for task_id in deleted_ids
    ]

    failed_tasks = [
        {"task_id": task_id, "reason": "任務不存在、無權訪問或正在進行中"}
        for task_id in request.task_ids if task_id not in deleted_ids
    ]

    return {
        "message": f"成功刪除 {deleted_count} 個任務",
        "deleted_count": deleted_count,
        "failed_count": len(failed_tasks),
        "deleted_tasks": deleted_tasks,
        "failed_tasks": failed_tasks
    }


@app.post("/transcribe/batch/tags/add")
async def batch_add_tags(
    request: BatchTagsRequest,
    current_user: dict = Depends(get_current_user)
):
    """批次加入標籤（需認證，只能編輯自己的任務）"""
    # 使用 TaskRepository 批次添加標籤
    modified_count = await task_repo.bulk_update_tags_add(
        request.task_ids,
        str(current_user["_id"]),
        request.tags
    )

    return {
        "message": f"成功為 {modified_count} 個任務加入標籤",
        "updated_count": modified_count,
        "failed_count": len(request.task_ids) - modified_count,
        "tags": request.tags
    }


@app.post("/transcribe/batch/tags/remove")
async def batch_remove_tags(
    request: BatchTagsRequest,
    current_user: dict = Depends(get_current_user)
):
    """批次移除標籤（需認證，只能編輯自己的任務）"""
    # 使用 TaskRepository 批次移除標籤
    modified_count = await task_repo.bulk_update_tags_remove(
        request.task_ids,
        str(current_user["_id"]),
        request.tags
    )

    return {
        "message": f"成功從 {modified_count} 個任務移除標籤",
        "updated_count": modified_count,
        "failed_count": len(request.task_ids) - modified_count,
        "tags": request.tags
    }


def enrich_task_data(task: Dict[str, Any]) -> Dict[str, Any]:
    """為任務資料添加計算欄位（預估時間、格式化時長等）

    支援巢狀結構：stats.duration_seconds, timestamps.* 等

    記憶體優化：只添加需要的計算欄位，避免深度複製
    """
    # 不使用 copy()，直接在原物件上添加欄位（MongoDB 已返回新物件）
    # 這樣可以減少記憶體使用

    # 添加進度百分比
    if task.get("status") in ["pending", "processing"]:
        task["progress_percentage"] = calculate_progress_percentage(task)

    # 添加預估剩餘時間
    if task.get("status") == "processing":
        # 使用固定的預估完成時間（在切分完成時計算一次）
        estimated_completion_time = task.get("estimated_completion_time")

        if estimated_completion_time:
            # 格式化完成時間為 MM/DD HH:MM
            try:
                completion_dt = datetime.strptime(estimated_completion_time, "%Y-%m-%d %H:%M:%S")
                task["estimated_completion_text"] = completion_dt.strftime("%m/%d %H:%M")
            except:
                task["estimated_completion_text"] = "計算中......"
        else:
            # 尚未切分完成，顯示計算中
            task["estimated_completion_text"] = "計算中......"

    # 添加格式化的總處理時長（如果已完成）
    # 支援巢狀結構：stats.duration_seconds
    if task.get("status") == "completed":
        duration_seconds = None

        # 嘗試從巢狀結構獲取
        if "stats" in task and task["stats"] and "duration_seconds" in task["stats"]:
            duration_seconds = task["stats"]["duration_seconds"]
        # 向後兼容：扁平結構
        elif "duration_seconds" in task:
            duration_seconds = task["duration_seconds"]

        if duration_seconds:
            task["duration_text"] = format_duration(duration_seconds)

    return task


@app.get("/transcribe/active/list")
async def list_active_tasks(current_user: dict = Depends(get_current_user)):
    """列出當前用戶的轉錄任務（需認證）- 記憶體優化版"""
    user_id = str(current_user["_id"])

    # 記憶體優化：只查詢需要的數量，不要一次查 100 個
    # 只獲取最近 30 個任務（足夠顯示）
    all_tasks = await task_repo.find_by_user(user_id, limit=30)
    active = await task_repo.find_active_by_user(user_id)

    # 合併記憶體中的即時進度資訊（只針對進行中的任務）
    with tasks_lock:
        for task in active:
            task_id = task.get("task_id")
            if task_id and task_id in transcription_tasks:
                # 只更新即時欄位，不複製整個物件
                live_info = transcription_tasks[task_id]
                if "progress" in live_info:
                    task["progress"] = live_info["progress"]
                if "progress_percentage" in live_info:
                    task["progress_percentage"] = live_info["progress_percentage"]
                if "diarization_status" in live_info:
                    task["diarization_status"] = live_info["diarization_status"]

    # 為所有任務添加計算欄位（使用生成器減少記憶體）
    active_enriched = [enrich_task_data(task) for task in active]

    # 只 enrich 需要返回的任務（最多 20 個）
    all_tasks_sorted = sorted(all_tasks, key=lambda t: (
        t.get("timestamps", {}).get("created_at") if isinstance(t.get("timestamps"), dict)
        else t.get("created_at", "")
    ), reverse=True)[:20]

    all_tasks_enriched = [enrich_task_data(task) for task in all_tasks_sorted]

    # 釋放不需要的資料並強制垃圾回收
    del all_tasks, all_tasks_sorted, active
    import gc
    gc.collect()

    return {
        "active_count": len(active_enriched),
        "total_count": await task_repo.count_by_user(user_id),  # 直接查詢計數，不載入全部
        "active_tasks": active_enriched,  # 已排序
        "all_tasks": all_tasks_enriched  # 已排序並限制為 20 個
    }


@app.get("/transcripts")
async def list_transcripts():
    """列出已保存的轉錄文字檔"""
    try:
        transcripts = []
        for txt_file in sorted(OUTPUT_DIR.glob("*.txt"), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = txt_file.stat()
            transcripts.append({
                "filename": txt_file.name,
                "size_kb": round(stat.st_size / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "path": str(txt_file.relative_to(OUTPUT_DIR.parent))
            })

        return {
            "total": len(transcripts),
            "output_dir": str(OUTPUT_DIR.relative_to(OUTPUT_DIR.parent)),
            "transcripts": transcripts
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """健康檢查"""
    return {
        "status": "healthy",
        "model_loaded": whisper_model is not None,
        "model_name": current_model_name
    }


# ==================== 音訊編輯功能 ====================

# 音訊片段儲存目錄
AUDIO_CLIPS_DIR = OUTPUT_DIR / "audio_clips"
AUDIO_CLIPS_DIR.mkdir(exist_ok=True)

# 片段元數據儲存
audio_clips: Dict[str, Dict[str, Any]] = {}
clips_lock = Lock()


def save_audio_clip(audio_segment: AudioSegment, source_filename: str, clip_id: str = None) -> Dict[str, Any]:
    """
    保存音訊片段到磁碟

    Args:
        audio_segment: pydub AudioSegment 對象
        source_filename: 來源檔案名稱
        clip_id: 可選的片段 ID（用於合併）

    Returns:
        {
            "clip_id": str,
            "filename": str,
            "duration": float,
            "path": str
        }
    """
    if clip_id is None:
        clip_id = str(uuid.uuid4())

    timestamp = datetime.now(TZ_UTC8).strftime("%Y%m%d_%H%M%S")
    filename = f"clip_{timestamp}_{clip_id[:8]}.mp3"
    filepath = AUDIO_CLIPS_DIR / filename

    # 導出為 MP3
    audio_segment.export(str(filepath), format="mp3", bitrate="192k")

    clip_data = {
        "clip_id": clip_id,
        "filename": filename,
        "duration": len(audio_segment) / 1000.0,  # 毫秒轉秒
        "path": str(filepath),
        "source": source_filename,
        "created_at": get_current_time()
    }

    with clips_lock:
        audio_clips[clip_id] = clip_data

    return clip_data


@app.post("/audio/clip")
async def clip_audio(
    audio_file: UploadFile = File(...),
    regions: str = Form(..., description="區段 JSON 陣列，格式：[{start, end, id}]")
):
    """
    剪輯音訊文件中的指定區段

    - **audio_file**: 原始音訊文件
    - **regions**: JSON 字串，包含區段陣列 [{"start": 10.5, "end": 25.3, "id": "xxx"}]

    Returns:
        {
            "clips": [
                {"clip_id": "...", "filename": "...", "duration": 14.8},
                ...
            ]
        }
    """
    temp_dir = Path(tempfile.mkdtemp())

    try:
        # 保存上傳的音檔
        file_suffix = Path(audio_file.filename).suffix
        temp_audio_path = temp_dir / f"input{file_suffix}"

        with temp_audio_path.open("wb") as f:
            content = await audio_file.read()
            f.write(content)

        print(f"🎵 載入音檔進行剪輯：{audio_file.filename}")

        # 載入音檔
        audio = AudioSegment.from_file(str(temp_audio_path))

        # 解析區段
        import json
        regions_data = json.loads(regions)

        if not regions_data or len(regions_data) == 0:
            raise HTTPException(status_code=400, detail="未提供任何區段")

        # 剪輯每個區段
        clips = []
        for idx, region in enumerate(regions_data):
            start_ms = int(region["start"] * 1000)
            end_ms = int(region["end"] * 1000)

            # 邊界檢查
            if end_ms > len(audio):
                end_ms = len(audio)

            if start_ms >= end_ms:
                raise HTTPException(
                    status_code=400,
                    detail=f"區段 {idx + 1} 的起始時間大於或等於結束時間"
                )

            # 提取片段
            clip_segment = audio[start_ms:end_ms]

            # 保存片段
            clip_data = save_audio_clip(clip_segment, audio_file.filename)
            clips.append({
                "clip_id": clip_data["clip_id"],
                "filename": clip_data["filename"],
                "duration": clip_data["duration"]
            })

        print(f"✅ 成功剪輯 {len(clips)} 個片段")

        return JSONResponse({
            "clips": clips,
            "source_file": audio_file.filename,
            "total_clips": len(clips)
        })

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="regions 格式錯誤，需為有效 JSON")
    except Exception as e:
        print(f"❌ 剪輯失敗：{e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"剪輯失敗：{str(e)}")
    finally:
        # 清理臨時文件
        cleanup_temp_dir(temp_dir)


@app.post("/audio/merge")
async def merge_audio(
    clip_ids: str = Form(..., description="要合併的片段 ID 陣列（JSON 字串）"),
    mode: str = Form("different-files", description="合併模式")
):
    """
    合併多個音訊片段

    - **clip_ids**: 片段 ID 陣列（JSON 字串）
    - **mode**: 合併模式
        - "different-files": 合併不同音檔（中間無間隔）
        - "same-file-clips": 合併同一音檔的片段（保持原始時間順序）

    Returns:
        {
            "merged_id": "...",
            "filename": "...",
            "duration": 120.5
        }
    """
    try:
        # 解析 clip_ids
        import json
        clip_ids_list = json.loads(clip_ids)

        if len(clip_ids_list) < 2:
            raise HTTPException(status_code=400, detail="至少需要 2 個片段")

        # 取得所有片段
        with clips_lock:
            clips_to_merge = []
            for clip_id in clip_ids_list:
                if clip_id not in audio_clips:
                    raise HTTPException(status_code=404, detail=f"片段 {clip_id} 不存在")
                clips_to_merge.append(audio_clips[clip_id])

        print(f"🔗 合併 {len(clips_to_merge)} 個片段（模式：{mode}）")

        # 載入所有片段
        segments = []
        for clip_data in clips_to_merge:
            segment = AudioSegment.from_file(clip_data["path"])
            segments.append(segment)

        # 合併邏輯
        merged = segments[0]
        for seg in segments[1:]:
            merged += seg

        # 保存合併結果
        merged_id = str(uuid.uuid4())
        merged_data = save_audio_clip(
            merged,
            f"merged_{len(clips_to_merge)}_clips",
            merged_id
        )

        duration_str = format_duration(merged_data['duration'])
        print(f"✅ 合併完成：{merged_data['filename']} ({duration_str})")

        return JSONResponse({
            "merged_id": merged_data["clip_id"],
            "filename": merged_data["filename"],
            "duration": merged_data["duration"]
        })

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="clip_ids 格式錯誤")
    except Exception as e:
        print(f"❌ 合併失敗：{e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"合併失敗：{str(e)}")


@app.get("/audio/download/{clip_id}")
async def download_clip(clip_id: str):
    """下載音訊片段或合併結果"""
    with clips_lock:
        if clip_id not in audio_clips:
            raise HTTPException(status_code=404, detail="片段不存在")

        clip_data = audio_clips[clip_id]

    filepath = Path(clip_data["path"])

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="檔案已被刪除")

    return FileResponse(
        path=str(filepath),
        filename=clip_data["filename"],
        media_type="audio/mpeg"
    )


@app.post("/audio/cleanup")
async def cleanup_old_clips(max_age_hours: int = 24):
    """
    清理超過指定時間的音訊片段

    - **max_age_hours**: 最大保留時間（小時），預設 24 小時
    """
    from datetime import datetime, timedelta

    cutoff_time = datetime.now(TZ_UTC8) - timedelta(hours=max_age_hours)

    deleted_count = 0
    with clips_lock:
        clips_to_delete = []

        for clip_id, clip_data in audio_clips.items():
            # 解析創建時間
            created_str = clip_data.get("created_at", "")
            try:
                created_time = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
                created_time = created_time.replace(tzinfo=TZ_UTC8)

                if created_time < cutoff_time:
                    clips_to_delete.append(clip_id)
            except:
                continue

        # 刪除過期片段
        for clip_id in clips_to_delete:
            clip_data = audio_clips[clip_id]
            filepath = Path(clip_data["path"])

            if filepath.exists():
                filepath.unlink()

            del audio_clips[clip_id]
            deleted_count += 1

    print(f"🧹 清理了 {deleted_count} 個過期音訊片段")

    return JSONResponse({
        "deleted_count": deleted_count,
        "message": f"成功清理 {deleted_count} 個超過 {max_age_hours} 小時的片段"
    })


@app.post("/audio/convert-to-web-format")
async def convert_audio_to_web_format(
    audio_file: UploadFile = File(..., description="要轉換的音檔")
):
    """
    將音訊檔案轉換為瀏覽器相容的格式 (MP3)
    用於解決瀏覽器無法解碼某些格式的問題
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # 儲存上傳的檔案
        temp_input_path = temp_dir_path / audio_file.filename
        with open(temp_input_path, "wb") as f:
            content = await audio_file.read()
            f.write(content)

        try:
            # 使用 pydub 載入音訊（支援各種格式）
            print(f"🔄 正在轉換音訊格式：{audio_file.filename}")
            audio = AudioSegment.from_file(str(temp_input_path))

            # 轉換為 MP3 格式（瀏覽器廣泛支援）
            # 使用較高的位元率以保持音質
            output_filename = f"converted_{Path(audio_file.filename).stem}.mp3"
            output_path = AUDIO_CLIPS_DIR / output_filename

            audio.export(
                str(output_path),
                format="mp3",
                bitrate="192k",
                parameters=["-ar", "44100"]  # 44.1kHz 取樣率
            )

            # 取得音訊資訊
            duration = len(audio) / 1000.0
            file_size = output_path.stat().st_size

            # 儲存到 clips 管理
            clip_id = str(uuid.uuid4())
            with clips_lock:
                audio_clips[clip_id] = {
                    "clip_id": clip_id,
                    "filename": output_filename,
                    "path": str(output_path),
                    "duration": duration,
                    "size": file_size,
                    "created_at": datetime.now(),
                    "original_filename": audio_file.filename
                }

            print(f"✅ 音訊轉換完成：{output_filename} ({duration:.2f}秒, {file_size / 1024 / 1024:.2f}MB)")

            return JSONResponse({
                "clip_id": clip_id,
                "filename": output_filename,
                "duration": duration,
                "size": file_size,
                "format": "mp3",
                "message": "音訊已成功轉換為瀏覽器相容格式"
            })

        except Exception as e:
            print(f"❌ 音訊轉換失敗：{str(e)}")
            raise HTTPException(status_code=400, detail=f"音訊轉換失敗：{str(e)}")


# ==================== Admin Dashboard API ====================

@app.get("/api/admin/statistics")
async def get_admin_statistics():
    """獲取後台統計資料（暫時無需認證）"""
    try:
        db = MongoDB.get_db()

        # 1. 總體統計
        total_tasks = await db.tasks.count_documents({})
        completed_tasks = await db.tasks.count_documents({"status": "completed"})
        processing_tasks = await db.tasks.count_documents({"status": "processing"})
        failed_tasks = await db.tasks.count_documents({"status": "failed"})

        # 2. Token 使用統計
        token_pipeline = [
            {
                "$match": {
                    "stats.token_usage.total": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$stats.token_usage.total"},
                    "total_prompt_tokens": {"$sum": "$stats.token_usage.prompt"},
                    "total_completion_tokens": {"$sum": "$stats.token_usage.completion"},
                    "tasks_with_tokens": {"$sum": 1}
                }
            }
        ]
        token_stats_cursor = db.tasks.aggregate(token_pipeline)
        token_stats_list = await token_stats_cursor.to_list(length=1)
        token_stats = token_stats_list[0] if token_stats_list else {
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "tasks_with_tokens": 0
        }

        # 3. 模型使用統計
        model_pipeline = [
            {
                "$match": {
                    "stats.token_usage.model": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": "$stats.token_usage.model",
                    "count": {"$sum": 1},
                    "total_tokens": {"$sum": "$stats.token_usage.total"}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ]
        model_stats_cursor = db.tasks.aggregate(model_pipeline)
        model_stats = await model_stats_cursor.to_list(length=None)

        # 4. 每日統計（最近 30 天）
        from datetime import datetime, timedelta
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        daily_pipeline = [
            {
                "$match": {
                    "timestamps.created_at": {"$gte": thirty_days_ago}
                }
            },
            {
                "$group": {
                    "_id": {"$substr": ["$timestamps.created_at", 0, 10]},
                    "tasks_count": {"$sum": 1},
                    "tokens_used": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}}
                }
            },
            {
                "$sort": {"_id": 1}
            }
        ]
        daily_stats_cursor = db.tasks.aggregate(daily_pipeline)
        daily_stats = await daily_stats_cursor.to_list(length=None)

        # 5. 使用者統計
        user_stats_pipeline = [
            {
                "$group": {
                    "_id": "$user.user_id",
                    "tasks_count": {"$sum": 1},
                    "tokens_used": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}}
                }
            },
            {
                "$sort": {"tasks_count": -1}
            },
            {
                "$limit": 10
            }
        ]
        user_stats_cursor = db.tasks.aggregate(user_stats_pipeline)
        top_users = await user_stats_cursor.to_list(length=None)

        # 6. 平均處理時間
        avg_duration_pipeline = [
            {
                "$match": {
                    "status": "completed",
                    "stats.duration_seconds": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "avg_duration": {"$avg": "$stats.duration_seconds"},
                    "min_duration": {"$min": "$stats.duration_seconds"},
                    "max_duration": {"$max": "$stats.duration_seconds"}
                }
            }
        ]
        duration_stats_cursor = db.tasks.aggregate(avg_duration_pipeline)
        duration_stats_list = await duration_stats_cursor.to_list(length=1)
        duration_stats = duration_stats_list[0] if duration_stats_list else {
            "avg_duration": 0,
            "min_duration": 0,
            "max_duration": 0
        }

        # 7. 標點符號服務使用統計
        punct_pipeline = [
            {
                "$group": {
                    "_id": "$config.punct_provider",
                    "count": {"$sum": 1}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ]
        punct_stats_cursor = db.tasks.aggregate(punct_pipeline)
        punct_stats = await punct_stats_cursor.to_list(length=None)

        return {
            "overview": {
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "processing_tasks": processing_tasks,
                "failed_tasks": failed_tasks,
                "success_rate": round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0
            },
            "token_usage": {
                "total_tokens": token_stats.get("total_tokens", 0),
                "prompt_tokens": token_stats.get("total_prompt_tokens", 0),
                "completion_tokens": token_stats.get("total_completion_tokens", 0),
                "tasks_with_tokens": token_stats.get("tasks_with_tokens", 0),
                "avg_tokens_per_task": round(token_stats.get("total_tokens", 0) / token_stats.get("tasks_with_tokens", 1), 2) if token_stats.get("tasks_with_tokens", 0) > 0 else 0
            },
            "model_usage": [
                {
                    "model": stat["_id"] or "未知",
                    "count": stat["count"],
                    "total_tokens": stat.get("total_tokens", 0)
                }
                for stat in model_stats
            ],
            "daily_stats": [
                {
                    "date": stat["_id"],
                    "tasks_count": stat["tasks_count"],
                    "tokens_used": stat["tokens_used"]
                }
                for stat in daily_stats
            ],
            "top_users": [
                {
                    "user_id": stat["_id"],
                    "tasks_count": stat["tasks_count"],
                    "tokens_used": stat["tokens_used"]
                }
                for stat in top_users
            ],
            "performance": {
                "avg_duration_seconds": round(duration_stats.get("avg_duration", 0), 2),
                "min_duration_seconds": round(duration_stats.get("min_duration", 0), 2),
                "max_duration_seconds": round(duration_stats.get("max_duration", 0), 2)
            },
            "punct_provider_usage": [
                {
                    "provider": stat["_id"] or "none",
                    "count": stat["count"]
                }
                for stat in punct_stats
            ]
        }

    except Exception as e:
        print(f"❌ 獲取統計資料失敗：{e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"獲取統計失敗：{str(e)}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Whisper 轉錄服務")
    parser.add_argument("--host", default="0.0.0.0", help="綁定的 IP 地址")
    parser.add_argument("--port", type=int, default=8000, help="綁定的端口")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Whisper 模型名稱")
    args = parser.parse_args()

    # 更新預設模型
    DEFAULT_MODEL = args.model

    print(f"""
╔══════════════════════════════════════╗
║   Whisper 轉錄服務 - FastAPI 版本   ║
╚══════════════════════════════════════╝

服務地址: http://{args.host}:{args.port}
API 文檔: http://{args.host}:{args.port}/docs
Whisper 模型: {args.model}
Google API Keys: {len(GOOGLE_API_KEYS)} 個已載入

""")

    uvicorn.run(app, host=args.host, port=args.port)
 