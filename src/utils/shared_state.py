"""
全局狀態管理
職責：提供運行時任務狀態追蹤的全局變數
"""

from threading import Lock
from pathlib import Path
from typing import Dict, Any, Set

# ==================== 運行時任務狀態（非持久化） ====================
# 這些狀態只在記憶體中維護，不寫入資料庫

# 任務的完整狀態（包含進度、chunks 等運行時資訊）
transcription_tasks: Dict[str, Any] = {}

# 任務的臨時目錄路徑
task_temp_dirs: Dict[str, Path] = {}

# 任務取消標記
task_cancelled: Dict[str, bool] = {}

# 任務的 Diarization 子進程
task_diarization_processes: Dict[str, Any] = {}

# ==================== 線程安全 ====================
# 用於保護全局狀態的鎖
tasks_lock = Lock()

# ==================== 記憶體專用欄位定義 ====================
# 這些欄位只存在於記憶體中，不應該寫入資料庫
MEMORY_ONLY_FIELDS: Set[str] = {
    # 進度相關
    "progress",
    "progress_percentage",

    # Chunks 相關
    "chunks",
    "total_chunks",
    "completed_chunks",
    "chunks_created",

    # 時間估算
    "estimated_completion_time",

    # 標點處理進度
    "punctuation_started",
    "punctuation_current_chunk",
    "punctuation_total_chunks",
    "punctuation_completed",

    # 說話者辨識進度
    "diarization_started",
    "diarization_completed",
    "diarization_status",

    # 音檔轉換狀態
    "audio_converted"
}
