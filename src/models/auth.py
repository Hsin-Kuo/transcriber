"""認證相關資料模型"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional


class UserRegister(BaseModel):
    """用戶註冊請求"""
    email: EmailStr
    password: str = Field(..., min_length=8, description="密碼至少 8 個字元")


class UserLogin(BaseModel):
    """用戶登入請求"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token 響應"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """刷新 Token 請求"""
    refresh_token: str


class ResendVerificationRequest(BaseModel):
    """重新發送驗證郵件請求"""
    email: EmailStr


class UserResponse(BaseModel):
    """用戶資訊響應"""
    id: str
    email: str
    role: str
    is_active: bool
    quota: dict
    usage: dict
    created_at: str

    class Config:
        from_attributes = True
