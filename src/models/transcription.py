"""轉錄內容資料模型"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class TranscriptionInDB(BaseModel):
    """轉錄內容資料模型（獨立 collection）"""
    id: str = Field(..., alias="_id", description="Task ID (作為主鍵)")
    content: str = Field(..., description="轉錄文字內容")
    text_length: int = Field(..., description="文字長度")
    created_at: datetime = Field(..., description="建立時間")
    updated_at: datetime = Field(..., description="更新時間")

    class Config:
        populate_by_name = True
        from_attributes = True


class TranscriptionCreate(BaseModel):
    """建立轉錄內容的請求模型"""
    task_id: str
    content: str


class TranscriptionUpdate(BaseModel):
    """更新轉錄內容的請求模型"""
    content: str
