"""任務相關資料模型"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class TaskChunk(BaseModel):
    """任務分段資料"""
    chunk_id: int
    start_time: int
    end_time: int
    status: str
    transcript: Optional[str] = None


class TaskSegment(BaseModel):
    """說話者分段資料"""
    start: float
    end: float
    speaker: str
    text: str


class TaskOptions(BaseModel):
    """轉錄配置"""
    model: str = "medium"
    language: str = "zh"
    enable_diarization: bool = False
    max_speakers: Optional[int] = None
    enable_punctuation: bool = True
    punct_provider: str = "gemini"


class TaskCreate(BaseModel):
    """建立任務請求"""
    filename: str
    custom_name: Optional[str] = None
    options: TaskOptions


class TaskResponse(BaseModel):
    """任務響應"""
    id: str = Field(alias="_id")
    user_id: str
    filename: str
    custom_name: Optional[str] = None
    status: str
    progress: str
    audio_duration: Optional[float] = None
    audio_path: Optional[str] = None
    keep_audio: bool = False
    transcript: Optional[str] = None
    segments: Optional[List[Dict[str, Any]]] = None
    chunks: Optional[List[Dict[str, Any]]] = None
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        from_attributes = True


class TaskListResponse(BaseModel):
    """任務列表響應"""
    total: int
    page: int
    page_size: int
    tasks: List[TaskResponse]
