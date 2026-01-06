"""Segments 資料模型"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class SegmentItem(BaseModel):
    """單個 segment 項目"""
    start: float = Field(..., description="開始時間（秒）")
    end: float = Field(..., description="結束時間（秒）")
    text: str = Field(..., description="文字內容")
    speaker: Optional[str] = Field(None, description="說話者 ID")


class SegmentsInDB(BaseModel):
    """Segments 資料模型（獨立 collection）"""
    id: str = Field(..., alias="_id", description="Task ID (作為主鍵)")
    segments: List[Dict[str, Any]] = Field(..., description="Segments 陣列")
    segment_count: int = Field(..., description="Segment 數量")
    created_at: datetime = Field(..., description="建立時間")
    updated_at: datetime = Field(..., description="更新時間")

    class Config:
        populate_by_name = True
        from_attributes = True


class SegmentsCreate(BaseModel):
    """建立 segments 的請求模型"""
    task_id: str
    segments: List[Dict[str, Any]]


class SegmentsUpdate(BaseModel):
    """更新 segments 的請求模型"""
    segments: List[Dict[str, Any]]
