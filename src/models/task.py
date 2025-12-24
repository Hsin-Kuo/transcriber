"""任務相關資料模型 - 巢狀結構設計"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class UserInfo(BaseModel):
    """使用者資訊"""
    user_id: str = Field(..., description="用戶 ID")
    user_email: str = Field(..., description="用戶 Email")


class FileInfo(BaseModel):
    """檔案資訊"""
    filename: str = Field(..., description="原始檔名")
    size_mb: float = Field(..., description="檔案大小 (MB)")


class TranscriptionConfig(BaseModel):
    """轉錄配置"""
    punct_provider: str = Field("gemini", description="標點符號服務")
    chunk_audio: bool = Field(False, description="是否分塊處理")
    chunk_minutes: int = Field(10, description="分塊時長（分鐘）")
    diarize: bool = Field(False, description="是否辨識說話者")
    max_speakers: Optional[int] = Field(None, description="最大說話者數")
    language: Optional[str] = Field(None, description="語言代碼")


class ResultFiles(BaseModel):
    """結果檔案"""
    audio_file: Optional[str] = Field(None, description="音檔路徑")
    audio_filename: Optional[str] = Field(None, description="音檔檔名")
    transcription_file: Optional[str] = Field(None, description="轉錄結果檔案路徑")
    transcription_filename: Optional[str] = Field(None, description="轉錄結果檔案名稱")
    segments_file: Optional[str] = Field(None, description="Segments 檔案路徑")
    text_length: Optional[int] = Field(None, description="文字長度")


class TokenUsage(BaseModel):
    """Token 使用量"""
    total: Optional[int] = Field(None, description="總 token 使用量")
    prompt: Optional[int] = Field(None, description="輸入 token 使用量")
    completion: Optional[int] = Field(None, description="輸出 token 使用量")
    model: Optional[str] = Field(None, description="使用的 LLM 模型名稱")


class DiarizationStats(BaseModel):
    """說話者辨識統計"""
    num_speakers: Optional[int] = Field(None, description="辨識到的說話者數量")
    duration_seconds: Optional[float] = Field(None, description="說話者辨識耗時")


class TaskStats(BaseModel):
    """任務統計資訊"""
    audio_duration_seconds: Optional[float] = Field(None, description="音檔實際時長（秒）")
    duration_seconds: Optional[float] = Field(None, description="任務執行時長（秒）")
    token_usage: Optional[TokenUsage] = Field(None, description="Token 使用統計")
    diarization: Optional[DiarizationStats] = Field(None, description="說話者辨識統計")


class Timestamps(BaseModel):
    """時間戳記"""
    created_at: str = Field(..., description="建立時間")
    updated_at: Optional[str] = Field(None, description="更新時間")
    started_at: Optional[str] = Field(None, description="開始時間")
    completed_at: Optional[str] = Field(None, description="完成時間")


class TaskInDB(BaseModel):
    """資料庫中的任務模型（巢狀結構）"""
    # MongoDB 的 _id 欄位
    id: str = Field(..., alias="_id", description="MongoDB Document ID")

    # 基本資訊
    task_id: str = Field(..., description="任務 ID")

    # 巢狀結構
    user: UserInfo = Field(..., description="使用者資訊")
    file: FileInfo = Field(..., description="檔案資訊")
    config: TranscriptionConfig = Field(..., description="轉錄配置")

    # 狀態與進度
    status: str = Field(..., description="任務狀態")
    progress: Optional[str] = Field(None, description="進度描述（僅最終狀態）")

    # 結果與統計
    result: Optional[ResultFiles] = Field(None, description="結果檔案")
    stats: Optional[TaskStats] = Field(None, description="統計資訊")

    # 使用者設定與標籤
    tags: List[str] = Field(default_factory=list, description="標籤列表")
    custom_name: Optional[str] = Field(None, description="自訂名稱")
    keep_audio: bool = Field(False, description="是否保留音檔")

    # 時間戳記
    timestamps: Timestamps = Field(..., description="時間戳記")

    class Config:
        populate_by_name = True
        from_attributes = True
        protected_namespaces = ()


class TaskCreate(BaseModel):
    """建立任務的請求模型"""
    filename: str
    file_size_mb: float
    punct_provider: str = "gemini"
    chunk_audio: bool = False
    chunk_minutes: int = 10
    diarize: bool = False
    max_speakers: Optional[int] = None
    language: Optional[str] = None
    custom_name: Optional[str] = None


class TaskResponse(BaseModel):
    """任務回應模型（簡化版）"""
    task_id: str
    user_id: str
    user_email: str
    status: str
    filename: str
    file_size_mb: float
    progress: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_file: Optional[str] = None
    result_filename: Optional[str] = None
    text_length: Optional[int] = None
    tags: List[str] = []
    custom_name: Optional[str] = None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """任務列表響應"""
    total_count: int
    active_count: int
    active_tasks: List[Dict[str, Any]]
    all_tasks: List[Dict[str, Any]]
