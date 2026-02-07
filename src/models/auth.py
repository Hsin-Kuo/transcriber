"""認證相關資料模型"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List


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


class ChangePasswordRequest(BaseModel):
    """更改密碼請求"""
    current_password: str = Field(..., description="目前密碼")
    new_password: str = Field(..., min_length=8, description="新密碼至少 8 個字元")


class UserPreferences(BaseModel):
    """用戶偏好設定"""
    summaryExpandMode: str = "follow-last"
    language: str = "zh-TW"
    timezone: str = "Asia/Taipei"
    theme: str = "light"


VALID_SUMMARY_EXPAND_MODES = ('always-open', 'always-collapsed', 'follow-last')
VALID_LANGUAGES = ('zh-TW', 'en')
VALID_THEMES = ('light', 'dark')
VALID_TIMEZONES = (
    'Asia/Taipei', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Hong_Kong',
    'America/New_York', 'America/Los_Angeles', 'Europe/London'
)


class UpdatePreferencesRequest(BaseModel):
    """更新偏好設定請求"""
    summaryExpandMode: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    theme: Optional[str] = None

    @validator('summaryExpandMode')
    def validate_summary_expand_mode(cls, v):
        if v is not None and v not in VALID_SUMMARY_EXPAND_MODES:
            raise ValueError(f'summaryExpandMode 必須是 {", ".join(VALID_SUMMARY_EXPAND_MODES)} 之一')
        return v

    @validator('language')
    def validate_language(cls, v):
        if v is not None and v not in VALID_LANGUAGES:
            raise ValueError(f'language 必須是 {", ".join(VALID_LANGUAGES)} 之一')
        return v

    @validator('timezone')
    def validate_timezone(cls, v):
        if v is not None and v not in VALID_TIMEZONES:
            raise ValueError(f'timezone 必須是 {", ".join(VALID_TIMEZONES)} 之一')
        return v

    @validator('theme')
    def validate_theme(cls, v):
        if v is not None and v not in VALID_THEMES:
            raise ValueError(f'theme 必須是 {", ".join(VALID_THEMES)} 之一')
        return v


class UserResponse(BaseModel):
    """用戶資訊響應"""
    id: str
    email: str
    role: str
    is_active: bool
    quota: dict
    usage: dict
    created_at: int  # UTC Unix timestamp
    auth_providers: List[str] = []  # ["password", "google", "apple"]
    preferences: dict = {}

    class Config:
        from_attributes = True


class ForgotPasswordRequest(BaseModel):
    """忘記密碼請求"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """重設密碼請求"""
    token: str
    new_password: str = Field(..., min_length=8, description="新密碼至少 8 個字元")


class GoogleAuthRequest(BaseModel):
    """Google OAuth 登入/註冊請求"""
    credential: str = Field(..., description="Google ID Token (從前端 Google Sign-In 取得)")


class GoogleBindRequest(BaseModel):
    """綁定 Google 帳號請求"""
    credential: str = Field(..., description="Google ID Token")


class SetPasswordRequest(BaseModel):
    """設定密碼請求（給 OAuth 用戶首次設定密碼）"""
    new_password: str = Field(..., min_length=8, description="新密碼至少 8 個字元")
