"""認證相關資料模型"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List


# RFC 5321: email 總長 ≤ 254 chars，部分系統用 320（local 64 + @ + domain 255）
# 我們採寬鬆值 320 以兼容 edge case
MAX_EMAIL_LENGTH = 320


class UserRegister(BaseModel):
    """用戶註冊請求"""
    email: EmailStr
    password: str = Field(..., min_length=8, description="密碼至少 8 個字元")


class UserLogin(BaseModel):
    """用戶登入請求"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token 響應。

    refresh_token 已改用 httpOnly cookie 傳遞，不再放在 response body。
    保留欄位為 Optional 僅供舊客戶端解析時不會炸；新前端應只讀 access_token。

    access_token 遷移中：這個階段 access_token 仍同時「種 cookie + 回
    body」雙軌並存（body 供尚未切換的前端相容），下一階段前端全部改用
    cookie 後，這裡會停止回傳有意義的 access_token 值（field 保留
    Optional，理由同 refresh_token）。

    expires_at：access token 的絕對過期時間（UTC epoch 毫秒）。前端用
    這個時間戳判斷是否該主動 refresh（大檔上傳分片前），取代原本解析
    JWT payload 的 exp claim 的做法——httpOnly cookie 下 JS 讀不到
    token 內容，這個值不是機密，明文回傳無妨。
    """
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_at: Optional[int] = None


class RefreshTokenRequest(BaseModel):
    """刷新 Token 請求"""
    refresh_token: str


class ResendVerificationRequest(BaseModel):
    """重新發送驗證郵件請求"""
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    """Email 驗證請求（用於 POST /verify-email）"""
    token: str = Field(..., min_length=10, max_length=128)


class AbandonRegistrationRequest(BaseModel):
    """放棄註冊請求（用戶在 verify-pending 偵測到 email bounce 後可呼叫）

    刻意用 str 而非 EmailStr — 與 GET /registration-status 一致：
    格式錯誤的 email 也應靜默回 200，避免 422 vs 200 變成「字串是否為
    合法 email 格式」的部分 enumeration oracle。
    """
    email: str = Field(..., max_length=MAX_EMAIL_LENGTH)


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
    tipsEnabled: bool = True


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
    tipsEnabled: Optional[bool] = None

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
    extra_quota: dict = {}  # 額外購買的額度（不隨月份重置）
    created_at: int  # UTC Unix timestamp
    auth_providers: List[str] = []  # ["password", "google", "apple"]
    preferences: dict = {}
    subscription: Optional[dict] = None

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


class DeleteAccountRequest(BaseModel):
    """刪除帳號請求"""
    password: Optional[str] = Field(None, description="密碼驗證（密碼用戶必填）")
    confirmation: str = Field(..., description="用戶輸入的 email 確認")
