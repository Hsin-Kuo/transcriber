"""AI 摘要相關資料模型"""
from pydantic import BaseModel, Field
from typing import Optional, List


class SummaryMeta(BaseModel):
    """摘要元資訊"""
    type: str = Field("General", description="內容類型: Meeting | Lecture | Interview | General")
    detected_topic: str = Field("", description="自動生成的標題或主題")


class SummarySegment(BaseModel):
    """內容段落"""
    topic: str = Field("", description="該段落的小標題")
    content: str = Field("", description="該段落的詳細摘要")
    keywords: List[str] = Field(default_factory=list, description="該段落的關鍵字")


class ActionItem(BaseModel):
    """待辦事項"""
    owner: Optional[str] = Field(None, description="負責人")
    task: str = Field("", description="任務內容")
    deadline: Optional[str] = Field(None, description="提及的期限")


class SummaryContent(BaseModel):
    """摘要內容"""
    meta: SummaryMeta = Field(default_factory=SummaryMeta, description="元資訊")
    summary: str = Field("", description="執行摘要 (200 字以內)")
    key_points: List[str] = Field(default_factory=list, description="條列式重點 (3-5 點)")
    segments: List[SummarySegment] = Field(default_factory=list, description="邏輯分段")
    action_items: List[ActionItem] = Field(default_factory=list, description="待辦事項")
    # 保留舊欄位以保持向後兼容
    highlights: List[str] = Field(default_factory=list, description="重點列表 (已棄用，使用 key_points)")
    keywords: List[str] = Field(default_factory=list, description="關鍵詞 (已棄用，從 segments 取得)")


class SummaryMetadata(BaseModel):
    """摘要元數據"""
    model: str = Field("gemini-2.0-flash", description="使用的 AI 模型")
    language: str = Field("zh", description="語言代碼")
    source_length: int = Field(0, description="原文長度")


class SummaryInDB(BaseModel):
    """資料庫中的摘要模型"""
    id: str = Field(..., alias="_id", description="摘要 ID (等於 task_id)")
    content: SummaryContent = Field(..., description="摘要內容")
    metadata: SummaryMetadata = Field(..., description="元數據")
    created_at: int = Field(..., description="建立時間 (UTC Unix timestamp)")
    updated_at: int = Field(..., description="更新時間 (UTC Unix timestamp)")

    class Config:
        populate_by_name = True
        from_attributes = True


class SummaryCreate(BaseModel):
    """建立摘要的請求模型"""
    # 不需要任何欄位，只需要 task_id (從路徑參數獲取)
    pass


class SummaryResponse(BaseModel):
    """摘要回應模型"""
    task_id: str = Field(..., description="任務 ID")
    content: SummaryContent = Field(..., description="摘要內容")
    metadata: SummaryMetadata = Field(..., description="元數據")
    created_at: int = Field(..., description="建立時間")
    updated_at: int = Field(..., description="更新時間")

    class Config:
        from_attributes = True


class GenerateSummaryResponse(BaseModel):
    """生成摘要的回應"""
    task_id: str
    status: str  # "completed" | "failed"
    summary: Optional[SummaryResponse] = None
    error: Optional[str] = None
