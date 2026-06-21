"""統一的 API 錯誤契約 — 讓前端用 code 做 i18n，不必原樣透傳後端中文訊息。

為什麼存在：後端 HTTPException 過去多半 `detail="中文句子"`，前端只能原樣顯示，
英文 UI 的使用者會看到中文。改成「機器可讀 code + 中文 fallback + 插值參數」後，
前端用 code 查 i18n 對照表翻成當前語言（見 frontend/src/utils/apiError.ts）。

detail 形狀：
    {"code": str, "message": str, "params": dict}
- code:    機器可讀錯誤碼，前端查 i18n key
- message: 英文 fallback（前端無對應 code、非前端呼叫端、log 用）
- params:  i18n 插值參數（如 {"max": 3072} 給 "File exceeds the {max}MB limit"）

code 命名慣例：`SCREAMING_SNAKE`，domain 前綴（AUTH_ / TASK_ / TRANSCRIPTION_ /
SUBSCRIPTION_ / UPLOAD_ / SHARED_ / TAG_ / SUMMARY_ / ADMIN_ / AUDIO_ / OAUTH_ /
WEBHOOK_）。code 用字串字面量即可；「需要翻成中文的使用者常見錯誤」其清單以前端
frontend/src/utils/apiError.ts 的 ERROR_I18N 為單一來源——未列入者前端顯示英文 message。

漸進遷移：前端 resolver 在「無對應 code」時 fallback 到 message，所以可以一個
endpoint 一個 endpoint 慢慢遷，舊的字串 detail 不受影響、不必前後端同步發版。

用法：
    raise api_error("UPLOAD_DISK_FULL", "Server storage is temporarily full", 507)
    raise api_error("FILE_TOO_LARGE", "File exceeds the {max}MB limit", 413, max=mb)
"""
from typing import Optional

from fastapi import HTTPException


def api_error(code: str, message: str, status_code: int, *, headers: Optional[dict] = None, **params) -> HTTPException:
    """產生帶結構化 detail 的 HTTPException。

    Args:
        code: 機器可讀錯誤碼（SCREAMING_SNAKE + domain 前綴）
        message: 英文 fallback 訊息（前端有對應 i18n key 時會被覆蓋翻譯）
        status_code: HTTP 狀態碼
        headers: 額外 response headers（如 401 的 WWW-Authenticate），keyword-only
        **params: i18n 插值參數（可選）
    """
    detail = {"code": code, "message": message}
    if params:
        detail["params"] = params
    return HTTPException(status_code=status_code, detail=detail, headers=headers)
