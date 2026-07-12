"""轉錄內容資料模型"""
from pydantic import BaseModel, Field, RootModel, field_validator
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


class SpeakerNamesUpdate(RootModel[dict[str, str]]):
    """更新講者名稱對應的請求模型。

    PUT body 是扁平字典（{"SPEAKER_00": "張三", ...}），不包一層 key，故用
    RootModel 直接驗證整個 body，維持既有 wire contract 不變。只限制長度/
    數量/型別——講者名稱允許任意合法字元（含 `<` `>`），逃逸是輸出端責任，
    這裡不做 HTML sanitize。
    """
    @field_validator("root")
    @classmethod
    def _validate_entries(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            raise ValueError("Too many speakers (max 50)")
        for key, name in v.items():
            if len(key) > 50:
                raise ValueError("Speaker key too long (max 50 characters)")
            if len(name) > 100:
                raise ValueError("Speaker name too long (max 100 characters)")
        return v
