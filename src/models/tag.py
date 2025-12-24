"""標籤相關資料模型"""
from pydantic import BaseModel, Field
from typing import Optional


class TagInDB(BaseModel):
    """資料庫中的標籤模型"""
    # MongoDB 的 _id 欄位
    id: str = Field(..., alias="_id", description="MongoDB Document ID")

    # 基本資訊
    tag_id: str = Field(..., description="標籤 ID")
    user_id: str = Field(..., description="所屬使用者 ID")
    name: str = Field(..., description="標籤名稱")

    # 顯示屬性
    color: Optional[str] = Field(None, description="標籤顏色（HEX 格式）")
    order: int = Field(0, description="顯示順序（數字越小越前面）")

    # 時間戳記
    created_at: str = Field(..., description="建立時間")
    updated_at: Optional[str] = Field(None, description="更新時間")

    class Config:
        populate_by_name = True
        from_attributes = True


class TagCreate(BaseModel):
    """建立標籤的請求模型"""
    name: str = Field(..., min_length=1, max_length=50, description="標籤名稱")
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$", description="顏色（HEX 格式，如 #FF6B6B）")


class TagUpdate(BaseModel):
    """更新標籤的請求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=50, description="標籤名稱")
    color: Optional[str] = Field(None, pattern="^#[0-9A-Fa-f]{6}$", description="顏色（HEX 格式）")
    description: Optional[str] = Field(None, max_length=200, description="標籤描述")


class TagOrderUpdate(BaseModel):
    """更新標籤順序的請求模型"""
    tag_ids: list[str] = Field(..., description="標籤 ID 列表（按照新順序排列）")


class TagResponse(BaseModel):
    """標籤回應模型"""
    tag_id: str
    name: str
    color: Optional[str] = None
    order: int
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True
