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
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 載入環境變數
from dotenv import load_dotenv
load_dotenv()

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

# 進度階段時間權重（用於計算進度百分比）
PROGRESS_WEIGHTS = {
    "audio_conversion": 2.2,      # 音訊轉檔：30s
    "audio_chunking": 2.2,        # 音訊切分：30s
    "chunk_start": 0.4,           # 每個 chunk 開始：30s / 6 = 0.4% per chunk
    "chunk_complete": 14.5,       # 每個 chunk 完成：5min / 6 = 14.5% per chunk
    "punctuation": 13.0,          # 加標點：3min
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
    """根據任務狀態計算進度百分比（基於時間權重）"""
    progress = 0.0

    # 1. 音訊轉檔完成
    if task_data.get("audio_converted", False):
        progress += PROGRESS_WEIGHTS["audio_conversion"]

    # 2. 音訊切分完成
    if task_data.get("chunks_created", False):
        progress += PROGRESS_WEIGHTS["audio_chunking"]

    # 3. Chunks 處理
    chunks = task_data.get("chunks", [])
    for chunk in chunks:
        if chunk.get("status") == "processing":
            progress += PROGRESS_WEIGHTS["chunk_start"]
        elif chunk.get("status") == "completed":
            progress += PROGRESS_WEIGHTS["chunk_start"]
            progress += PROGRESS_WEIGHTS["chunk_complete"]

    # 4. 標點處理
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
transcription_tasks: Dict[str, Dict[str, Any]] = {}  # 儲存任務狀態
task_temp_dirs: Dict[str, Path] = {}  # 儲存任務的暫存目錄路徑
task_cancelled: Dict[str, bool] = {}  # 標記已取消的任務
task_diarization_processes: Dict[str, Any] = {}  # 儲存任務的 diarization 進程
tasks_lock = Lock()  # 線程安全鎖
executor = ThreadPoolExecutor(max_workers=1)  # 線程池，最多 1 個並發轉錄

def save_tasks_to_disk():
    """將任務狀態保存到磁碟"""
    try:
        with tasks_lock:
            with open(TASKS_DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(transcription_tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ 保存任務狀態失敗：{e}")

def load_tasks_from_disk():
    """從磁碟載入任務狀態"""
    global transcription_tasks
    try:
        if TASKS_DB_FILE.exists():
            with open(TASKS_DB_FILE, 'r', encoding='utf-8') as f:
                loaded_tasks = json.load(f)

            # 過濾掉進行中的任務（因為重啟後無法繼續）
            # 只保留已完成、失敗、取消的任務
            with tasks_lock:
                for task_id, task in loaded_tasks.items():
                    if task["status"] in ["completed", "failed", "cancelled"]:
                        transcription_tasks[task_id] = task
                    else:
                        # 將進行中的任務標記為失敗
                        task["status"] = "failed"
                        task["error"] = "服務重啟，任務已中斷"
                        task["progress"] = "服務重啟，任務已中斷"
                        transcription_tasks[task_id] = task

            print(f"✅ 已從磁碟載入 {len(transcription_tasks)} 個任務記錄")
    except Exception as e:
        print(f"❌ 載入任務狀態失敗：{e}")
        print(f"   將從空白狀態開始")

app = FastAPI(
    title="Whisper 轉錄服務",
    description="上傳音檔進行轉錄，支援自動分段與標點",
    version="2.0.0"
)

# 添加 CORS 中間件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生產環境應該限制具體域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 工具函式 ----------

def cleanup_temp_dir(temp_dir: Path):
    """清理臨時目錄"""
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"🗑️ 已清理臨時目錄：{temp_dir.name}")
    except Exception as e:
        print(f"⚠️ 清理臨時目錄失敗：{e}")


def update_task_status(task_id: str, updates: Dict[str, Any]):
    """更新任務狀態（線程安全）"""
    with tasks_lock:
        if task_id in transcription_tasks:
            transcription_tasks[task_id].update(updates)
            transcription_tasks[task_id]["updated_at"] = get_current_time()

            # 自動計算並更新進度百分比
            progress_pct = calculate_progress_percentage(transcription_tasks[task_id])
            transcription_tasks[task_id]["progress_percentage"] = round(progress_pct, 1)

    # 當任務狀態變更為終止狀態時，保存到磁碟
    if updates.get("status") in ["completed", "failed", "cancelled"]:
        save_tasks_to_disk()


# ---------- 轉錄函式 (從原始 transcribe.py 移植) ----------

def transcribe_single_chunk(
    model,
    chunk_path: Path,
    language: Optional[str] = None,
    task_id: str = None,
    chunk_idx: int = None,
    time_offset: float = 0.0,
    return_segments: bool = False
) -> str:
    """轉錄單一音檔片段（用於並行處理）

    Args:
        model: Whisper 模型
        chunk_path: 音檔路徑
        language: 語言代碼（None 表示自動偵測，預設值）
        task_id: 任務 ID
        chunk_idx: Chunk 索引
        time_offset: 時間偏移（秒），用於計算相對於完整音檔的時間戳
        return_segments: 是否返回帶時間戳的 segments

    Returns:
        如果 return_segments=True，返回 (text, segments)
        否則返回 text
    """
    # 標記此 chunk 開始處理（實際開始執行時才標記）
    if task_id and chunk_idx:
        with tasks_lock:
            if task_id in transcription_tasks:
                chunks = transcription_tasks[task_id].get("chunks", [])
                if chunk_idx - 1 < len(chunks) and chunks[chunk_idx - 1]["status"] == "pending":
                    chunks[chunk_idx - 1]["status"] = "processing"
                    chunks[chunk_idx - 1]["started_at"] = get_current_time()
        update_task_status(task_id, {})  # 觸發進度計算

    segments, info = model.transcribe(str(chunk_path), language=language, beam_size=5)

    # 收集 segments
    segments_list = []
    text_parts = []

    for segment in segments:
        text_parts.append(segment.text)
        if return_segments:
            segments_list.append({
                "start": segment.start + time_offset,  # 加上時間偏移
                "end": segment.end + time_offset,
                "text": segment.text
            })

    text = "".join(text_parts).strip()

    if return_segments:
        return text, segments_list
    return text


def transcribe_with_timestamps(model, audio_path: Path, language: Optional[str] = None) -> List[Dict]:
    """
    轉錄音檔並返回帶時間戳的 segments

    Args:
        model: Whisper 模型
        audio_path: 音檔路徑
        language: 語言代碼（None 表示自動偵測，預設值）

    Returns:
        List of segments with format:
        [{"start": 0.0, "end": 5.2, "text": "hello"}, ...]
    """
    segments_list = []
    segments, info = model.transcribe(str(audio_path), language=language, beam_size=5)

    for segment in segments:
        segments_list.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text
        })

    return segments_list


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
    print(f"🔊 載入音檔：{audio_path.name}")
    audio = AudioSegment.from_file(audio_path)
    total_duration_ms = len(audio)
    total_minutes = total_duration_ms / 1000 / 60

    print(f"📊 音檔總長度：{total_minutes:.1f} 分鐘")

    # 如果音檔不長，直接轉錄
    if total_duration_ms <= chunk_duration_ms:
        print(f"📝 音檔長度在 {chunk_duration_ms/1000/60:.0f} 分鐘內，直接轉錄...")
        return transcribe_single_chunk(model, audio_path, language=language)

    # 步驟 1：如果啟用 diarization，在背景並行執行說話者辨識
    diarization_future = None
    diarization_start_time = None
    diarization_executor = None

    if diarize and diarization_pipeline:
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

    # 第一步：準備所有 chunks（切分音檔）
    print(f"📦 準備切分音檔...")
    chunk_info_list = []  # 儲存 (chunk_idx, start_ms, end_ms, temp_path)
    start_ms = 0
    chunk_idx = 1

    while start_ms < total_duration_ms:
        end_ms = min(start_ms + chunk_duration_ms, total_duration_ms)

        # 如果不是最後一段，嘗試在靜音處切分
        if end_ms < total_duration_ms:
            search_start = max(end_ms - 30000, start_ms)
            search_end = min(end_ms + 30000, total_duration_ms)
            search_segment = audio[search_start:search_end]

            nonsilent_ranges = detect_nonsilent(
                search_segment,
                min_silence_len=500,
                silence_thresh=-40
            )

            if nonsilent_ranges:
                target_pos = end_ms - search_start
                best_split = end_ms
                min_diff = float('inf')

                for i in range(len(nonsilent_ranges) - 1):
                    gap_start = nonsilent_ranges[i][1]
                    gap_end = nonsilent_ranges[i + 1][0]
                    gap_mid = (gap_start + gap_end) // 2

                    diff = abs(gap_mid - target_pos)
                    if diff < min_diff:
                        min_diff = diff
                        best_split = search_start + gap_mid

                if abs(best_split - end_ms) < 60000:
                    end_ms = best_split

        print(f"   準備第 {chunk_idx}/{num_chunks} 段 ({start_ms/1000/60:.1f}-{end_ms/1000/60:.1f} 分鐘)...")

        # 檢查是否已被取消
        if task_id and task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        # 導出 chunk 到臨時檔案
        chunk_audio = audio[start_ms:end_ms]
        temp_path = audio_path.parent / f"_temp_{audio_path.stem}_chunk_{chunk_idx}.wav"
        chunk_audio.export(temp_path, format="wav")

        chunk_info_list.append((chunk_idx, start_ms, end_ms, temp_path))

        start_ms = end_ms
        chunk_idx += 1

    print(f"✅ 已準備 {len(chunk_info_list)} 個音檔片段")

    # 標記切分完成並計算預估完成時間
    if task_id:
        import math
        # 如果啟用 diarization，使用較低的並行度
        num_workers = 2 if diarize else 4
        rounds = math.ceil(num_chunks / num_workers)
        estimated_minutes = rounds * 14 * 1.1

        # 取得任務開始時間並計算預估完成時間
        with tasks_lock:
            if task_id in transcription_tasks:
                started_at_str = transcription_tasks[task_id].get("started_at")
                if started_at_str:
                    started_at = datetime.strptime(started_at_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_UTC8)
                    estimated_completion = started_at + timedelta(minutes=estimated_minutes)
                    estimated_completion_str = estimated_completion.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    estimated_completion_str = None

        update_task_status(task_id, {
            "chunks_created": True,
            "progress": f"已切分為 {num_chunks} 個片段，開始轉錄...",
            "estimated_completion_time": estimated_completion_str
        })

    # 第二步：並行轉錄所有 chunks（與 diarization 同時進行）
    # 如果同時執行 diarization，降低轉錄並行度以減少資源競爭
    transcribe_workers = 2 if diarization_future else 4
    print(f"🚀 開始並行轉錄（並行數：{transcribe_workers}）{'，同時進行說話者辨識' if diarization_future else ''}...")
    chunks_text = [None] * num_chunks  # 預先分配陣列保持順序
    all_segments = [] if diarization_future else None  # 如果啟用 diarization，收集所有 segments

    try:
        with ThreadPoolExecutor(max_workers=transcribe_workers) as executor:
            # 提交所有轉錄任務到線程池
            future_to_chunk = {}
            for chunk_idx, start_ms, end_ms, temp_path in chunk_info_list:
                # 計算這個 chunk 的時間偏移（相對於完整音檔的秒數）
                time_offset_seconds = start_ms / 1000.0

                # 如果啟用 diarization，需要返回帶時間戳的 segments
                future = executor.submit(
                    transcribe_single_chunk,
                    model,
                    temp_path,
                    language,  # 使用指定的語言
                    task_id,
                    chunk_idx,
                    time_offset_seconds,
                    bool(diarization_future)  # return_segments
                )
                future_to_chunk[future] = (chunk_idx, temp_path, time_offset_seconds)

            # 等待完成並更新進度
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
                    chunk_start_time = None
                    if task_id:
                        with tasks_lock:
                            if task_id in transcription_tasks:
                                chunks = transcription_tasks[task_id].get("chunks", [])
                                if chunk_idx - 1 < len(chunks):
                                    start_str = chunks[chunk_idx - 1].get("started_at")
                                    if start_str:
                                        chunk_start_time = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")

                    result = future.result()

                    # 處理返回結果（可能是純文字或(文字, segments)元組）
                    if diarization_future and isinstance(result, tuple):
                        chunk_text, chunk_segments = result
                        all_segments.extend(chunk_segments)  # 收集所有 segments
                    else:
                        chunk_text = result

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
                        with tasks_lock:
                            if task_id in transcription_tasks:
                                chunks = transcription_tasks[task_id].get("chunks", [])
                                if chunk_idx - 1 < len(chunks):
                                    chunks[chunk_idx - 1]["status"] = "completed"
                                    chunks[chunk_idx - 1]["completed_at"] = get_current_time()
                                    if chunk_duration:
                                        chunks[chunk_idx - 1]["duration_seconds"] = round(chunk_duration, 1)
                        update_task_status(task_id, {
                            "progress": f"正在轉錄音訊... ({completed}/{num_chunks} 段完成)",
                            "completed_chunks": completed
                        })

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
    if diarization_future and all_segments:
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
                return final_text
            else:
                print(f"⚠️  說話者辨識失敗，返回純文字轉錄")
                if task_id:
                    update_task_status(task_id, {
                        "diarization_status": "failed"
                    })
                return " ".join(chunks_text)

        except Exception as e:
            print(f"⚠️  等待說話者辨識時發生錯誤：{e}")
            print(f"   將返回純文字轉錄")
            if task_id:
                update_task_status(task_id, {
                    "diarization_status": "failed"
                })
            return " ".join(chunks_text)
    else:
        # 沒有 diarization，返回純文字
        return " ".join(chunks_text)


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
        language: 語言代碼 (zh/en/ja/ko/auto)
        text: 要處理的文字

    Returns:
        (system_message, user_message) 元組
    """
    # 如果是自動偵測，先辨識語言
    if language == "auto":
        language = detect_language_with_llm(text, provider="gemini")
        print(f"🔍 自動辨識語言: {language}")

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


def call_gemini_with_retry(prompt: str, max_retries: int = None) -> str:
    """調用 Gemini API，支援自動重試和 Key 切換"""
    import google.generativeai as genai

    if max_retries is None:
        max_retries = len(GOOGLE_API_KEYS)

    last_error = None

    for attempt in range(max_retries):
        try:
            # 獲取下一個 API Key
            api_key = get_next_google_api_key()
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(GEMINI_MODEL)

            # 調用 API
            resp = model.generate_content(
                [{"role": "user", "parts": [prompt]}],
                generation_config={"temperature": 0.2}
            )

            return (resp.text or "").strip()

        except Exception as e:
            last_error = e
            error_msg = str(e)
            print(f"⚠️ Google API Key 調用失敗 (嘗試 {attempt + 1}/{max_retries}): {error_msg}")

            # 如果還有 key 可用，繼續嘗試
            if attempt < max_retries - 1:
                print(f"🔄 切換到下一個 API Key...")
                continue
            else:
                print(f"❌ 所有 API Keys 都已嘗試，失敗")
                raise RuntimeError(f"所有 Google API Keys 都調用失敗。最後錯誤: {error_msg}") from last_error

    raise RuntimeError("無法調用 Gemini API") from last_error


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
        task_id: 任務 ID（用於更新進度）
        language: 語言代碼 (zh/en/ja/ko/auto)，auto 會自動辨識
    """
    if not GOOGLE_API_KEYS:
        raise RuntimeError("未設定任何 GOOGLE_API_KEY")

    # 如果是自動偵測，先辨識語言
    actual_language = language
    if language == "auto":
        actual_language = detect_language_with_llm(text, provider="gemini")
        print(f"🔍 自動辨識語言: {actual_language}")

    # 根據語言決定合適的分段大小
    if chunk_size is None:
        if actual_language in ['en', 'es', 'fr', 'de', 'it', 'pt']:
            # 英文等字母語言：使用較大的字元數（因為單詞包含空格，字元數較多）
            chunk_size = 8000  # 約 1300-1600 個英文單詞
        else:
            # 中文、日文、韓文等：使用標準字元數
            chunk_size = 3000  # 約 3000 個字符
        print(f"📏 根據語言 '{actual_language}' 設定分段大小：{chunk_size} 字元")

    # 如果文本不長，直接處理
    if len(text) <= chunk_size:
        system_msg, user_msg = get_punctuation_prompt(actual_language, text)
        prompt = system_msg + "\n\n" + user_msg
        return call_gemini_with_retry(prompt)

    # 長文本：分段處理
    print(f"📊 文本長度 {len(text)} 字，將分段處理（每段約 {chunk_size} 字）...")
    chunks = []
    start = 0

    # 根據語言選擇分段標記
    split_markers = '。？！\n' if actual_language in ['zh', 'ja'] else '.?!\n'

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
            })

        # 使用語言感知的提示語
        system_msg, user_msg = get_chunked_punctuation_prompt(actual_language, chunk, idx, len(chunks))

        prompt = system_msg + "\n\n" + user_msg
        result = call_gemini_with_retry(prompt)
        results.append(result)

    print("✅ 所有段落處理完成，正在合併...")
    return "\n\n".join(results)


def process_transcription_task(
    task_id: str,
    temp_audio_path: Path,
    filename: str,
    punct_provider: str,
    chunk_audio: bool,
    chunk_minutes: int,
    diarize: bool = False,
    max_speakers: Optional[int] = None,
    language: str = "zh"
):
    """
    在背景線程中執行轉錄任務
    這個函數會更新任務狀態，並處理所有轉錄邏輯

    注意：diarization 僅在非分段模式下可用，分段模式會忽略此參數
    max_speakers: 最大講者人數（可選，2-10）
    """
    temp_dir = temp_audio_path.parent

    try:
        # 記錄暫存目錄
        with tasks_lock:
            task_temp_dirs[task_id] = temp_dir

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
        AudioSegment.from_file(temp_audio_path).export(wav_path, format="wav")

        # 標記音訊轉檔完成
        update_task_status(task_id, {
            "audio_converted": True,
            "progress": "音訊轉檔完成，準備轉錄..."
        })

        # 檢查是否已被取消
        if task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        # 執行轉錄
        update_task_status(task_id, {"progress": "正在轉錄音訊..."})

        if chunk_audio:
            # 分段模式：現在支援 diarization（先對完整音檔做說話者辨識，再分段轉錄）
            chunk_duration_ms = chunk_minutes * 60 * 1000
            raw_text = transcribe_audio_in_chunks(
                wav_path,
                whisper_model,
                chunk_duration_ms,
                task_id=task_id,
                diarize=diarize,
                max_speakers=max_speakers,
                language=language
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
                transcription_segments = transcribe_with_timestamps(whisper_model, wav_path, language=language)

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
                raw_text = transcribe_single_chunk(whisper_model, wav_path, language=language)

        # 檢查是否已被取消
        if task_cancelled.get(task_id, False):
            raise RuntimeError("任務已被使用者取消")

        print(f"✅ [{task_id}] 轉錄完成（{len(raw_text)} 字）")

        # 加標點
        final_text = raw_text
        if punct_provider == "gemini":
            update_task_status(task_id, {
                "punctuation_started": True,
                "progress": "正在添加標點符號（Gemini）..."
            })
            print(f"✨ [{task_id}] 使用 Gemini 加標點與分段...")
            final_text = punctuate_with_gemini(raw_text, task_id=task_id, language=language)
            update_task_status(task_id, {"punctuation_completed": True})
        elif punct_provider == "openai":
            update_task_status(task_id, {
                "punctuation_started": True,
                "progress": "正在添加標點符號（OpenAI）..."
            })
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("未設定 OPENAI_API_KEY")
            print(f"✨ [{task_id}] 使用 OpenAI 加標點與分段...")
            final_text = punctuate_with_openai(raw_text, language=language)
            update_task_status(task_id, {"punctuation_completed": True})

        print(f"🎉 [{task_id}] 處理完成！")

        # 保存文字檔到 output/ 目錄
        update_task_status(task_id, {"progress": "正在保存結果..."})
        timestamp = datetime.now(TZ_UTC8).strftime("%Y%m%d_%H%M%S")
        safe_filename = Path(filename).stem.replace(" ", "_")
        output_filename = f"{safe_filename}_{timestamp}_transcript.txt"
        permanent_output = OUTPUT_DIR / output_filename
        permanent_output.write_text(final_text, encoding="utf-8")
        print(f"💾 [{task_id}] 文字檔已保存：{permanent_output.relative_to(OUTPUT_DIR.parent)}")

        # 計算總處理時間
        end_time = datetime.now(TZ_UTC8)
        duration_seconds = (end_time - start_time).total_seconds()

        # 更新狀態：完成
        update_task_status(task_id, {
            "status": "completed",
            "progress": "轉錄完成",
            "result_file": str(permanent_output),
            "result_filename": output_filename,
            "text_length": len(final_text),
            "completed_at": get_current_time(),
            "duration_seconds": round(duration_seconds, 1)
        })

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


# ---------- API Endpoints ----------

@app.on_event("startup")
async def startup_event():
    """啟動時載入 Whisper 模型和任務記錄"""
    global whisper_model, current_model_name

    # 載入任務記錄
    print(f"📂 正在載入任務記錄...")
    load_tasks_from_disk()

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


@app.get("/")
async def root():
    """服務狀態"""
    with tasks_lock:
        active_count = sum(1 for t in transcription_tasks.values() if t["status"] in ["pending", "processing"])

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
    language: str = Form("zh", description="轉錄語言 (zh/en/ja/ko/auto)")
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

        # 創建任務記錄
        with tasks_lock:
            transcription_tasks[task_id] = {
                "task_id": task_id,
                "status": "pending",
                "filename": file.filename,
                "file_size_mb": round(len(content) / 1024 / 1024, 2),
                "progress": "等待處理...",
                "punct_provider": punct_provider,
                "chunk_audio": chunk_audio,
                "chunk_minutes": chunk_minutes,
                "diarize": diarize,
                "max_speakers": max_speakers,
                "language": language,
                "diarization_status": None,  # "running" | "completed" | "failed" | None
                "diarization_num_speakers": None,  # 識別到的講者人數
                "created_at": get_current_time(),
                "updated_at": get_current_time()
            }

        # 立即保存新任務
        save_tasks_to_disk()

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
            language
        )

        # 立即返回任務資訊
        return JSONResponse({
            "task_id": task_id,
            "status": "pending",
            "message": "轉錄任務已提交，請使用 task_id 查詢狀態",
            "filename": file.filename,
            "created_at": transcription_tasks[task_id]["created_at"],
            "status_url": f"/transcribe/{task_id}",
            "download_url": f"/transcribe/{task_id}/download"
        })

    except Exception as e:
        # 發生錯誤時清理
        cleanup_temp_dir(temp_dir)
        print(f"❌ 提交任務失敗：{e}")
        raise HTTPException(status_code=500, detail=f"提交任務失敗：{str(e)}")


@app.get("/transcribe/{task_id}")
async def get_task_status(task_id: str):
    """查詢轉錄任務狀態"""
    with tasks_lock:
        task = transcription_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在")

    # 使用統一的函數添加計算欄位
    return JSONResponse(enrich_task_data(task))


@app.get("/transcribe/{task_id}/download")
async def download_task_result(task_id: str):
    """下載轉錄結果"""
    with tasks_lock:
        task = transcription_tasks.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任務不存在")

    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"任務尚未完成（當前狀態：{task['status']}）"
        )

    result_file = Path(task["result_file"])
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="結果檔案不存在")

    return FileResponse(
        result_file,
        media_type="text/plain",
        filename=task["result_filename"]
    )


@app.post("/transcribe/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消正在執行的任務"""
    with tasks_lock:
        task = transcription_tasks.get(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="任務不存在")

        # 只能取消進行中或等待中的任務
        if task["status"] not in ["pending", "processing"]:
            raise HTTPException(
                status_code=400,
                detail=f"無法取消已結束的任務（當前狀態：{task['status']}）"
            )

        # 標記任務為已取消
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

    print(f"🛑 任務 {task_id} 已被標記為取消")

    return {
        "message": "任務取消指令已發送",
        "task_id": task_id,
        "note": "任務將在當前步驟完成後停止"
    }


@app.delete("/transcribe/{task_id}")
async def delete_task(task_id: str):
    """刪除任務及其相關檔案"""
    with tasks_lock:
        task = transcription_tasks.get(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="任務不存在")

        # 不允許刪除進行中的任務
        if task["status"] in ["pending", "processing"]:
            raise HTTPException(
                status_code=400,
                detail=f"無法刪除進行中的任務（當前狀態：{task['status']}），請先取消任務"
            )

        # 刪除結果檔案（如果存在）
        if task["status"] == "completed" and "result_file" in task:
            result_file = Path(task["result_file"])
            try:
                if result_file.exists():
                    result_file.unlink()
                    print(f"🗑️ 已刪除檔案：{result_file.name}")
            except Exception as e:
                print(f"⚠️ 刪除檔案失敗：{e}")

        # 從任務列表中移除
        del transcription_tasks[task_id]

    # 保存到磁碟
    save_tasks_to_disk()

    return {
        "message": "任務已刪除",
        "task_id": task_id
    }


def enrich_task_data(task: Dict[str, Any]) -> Dict[str, Any]:
    """為任務資料添加計算欄位（預估時間、格式化時長等）"""
    task_copy = task.copy()

    # 添加預估剩餘時間
    if task["status"] == "processing":
        # 使用固定的預估完成時間（在切分完成時計算一次）
        estimated_completion_time = task.get("estimated_completion_time")

        if estimated_completion_time:
            # 格式化完成時間為 MM/DD HH:MM
            try:
                completion_dt = datetime.strptime(estimated_completion_time, "%Y-%m-%d %H:%M:%S")
                task_copy["estimated_completion_text"] = completion_dt.strftime("%m/%d %H:%M")
            except:
                task_copy["estimated_completion_text"] = "計算中......"
        else:
            # 尚未切分完成，顯示計算中
            task_copy["estimated_completion_text"] = "計算中......"

    # 添加格式化的總處理時長（如果已完成）
    if task["status"] == "completed" and "duration_seconds" in task:
        task_copy["duration_text"] = format_duration(task["duration_seconds"])

    return task_copy


@app.get("/transcribe/active/list")
async def list_active_tasks():
    """列出所有進行中的轉錄任務"""
    with tasks_lock:
        active = [
            task for task in transcription_tasks.values()
            if task["status"] in ["pending", "processing"]
        ]
        all_tasks = list(transcription_tasks.values())

    # 為所有任務添加計算欄位
    active_enriched = [enrich_task_data(task) for task in active]
    all_tasks_enriched = [enrich_task_data(task) for task in all_tasks]

    return {
        "active_count": len(active_enriched),
        "total_count": len(all_tasks_enriched),
        "active_tasks": sorted(active_enriched, key=lambda x: x["created_at"], reverse=True),
        "all_tasks": sorted(all_tasks_enriched, key=lambda x: x["created_at"], reverse=True)[:20]  # 最近 20 個
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
