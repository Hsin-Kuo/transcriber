"""統一的 API 錯誤契約 — 讓前端用 code 做 i18n，不必原樣透傳後端中文訊息。

為什麼存在：後端 HTTPException 過去多半 `detail="中文句子"`，前端只能原樣顯示，
英文 UI 的使用者會看到中文。改成「機器可讀 code + 中文 fallback + 插值參數」後，
前端用 code 查 i18n 對照表翻成當前語言（見 frontend/src/utils/apiError.ts）。

detail 形狀：
    {"code": str, "message": str, "params": dict}
- code:    機器可讀錯誤碼，前端查 i18n key
- message: 中文 fallback（前端無對應 code、非前端呼叫端、log 用）
- params:  i18n 插值參數（如 {"max": 3072} 給 "檔案超過 {max}MB 上限"）

漸進遷移：前端 resolver 在「無對應 code」時 fallback 到 message，所以可以一個
endpoint 一個 endpoint 慢慢遷，舊的字串 detail 不受影響、不必前後端同步發版。

用法：
    raise api_error("UPLOAD_DISK_FULL", "伺服器暫存空間不足，請稍後再試", 507)
    raise api_error("FILE_TOO_LARGE", f"檔案超過 {mb}MB 上限", 413, max=mb)
"""
from fastapi import HTTPException


# 後端錯誤碼登錄表。用常數而非散落字串，避免拼錯、方便 grep 找呼叫點。
# message 一律英文（fallback）；使用者常見的錯誤再由前端 apiError.ts 的 ERROR_I18N
# 對應 i18n key 翻成當前語言，邊緣/開發類錯誤則直接顯示英文 message。
class ErrorCode:
    # ── Uploads（分片上傳）────────────────────────────────
    INVALID_FILE_SIZE = "INVALID_FILE_SIZE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UPLOAD_DISK_FULL = "UPLOAD_DISK_FULL"
    UPLOAD_SESSION_NOT_FOUND = "UPLOAD_SESSION_NOT_FOUND"
    UPLOAD_SESSION_INVALIDATED = "UPLOAD_SESSION_INVALIDATED"
    UPLOAD_FORBIDDEN = "UPLOAD_FORBIDDEN"
    UPLOAD_CHUNK_INDEX_OUT_OF_RANGE = "UPLOAD_CHUNK_INDEX_OUT_OF_RANGE"
    UPLOAD_CHUNKS_MISSING = "UPLOAD_CHUNKS_MISSING"


def api_error(code: str, message: str, status_code: int, **params) -> HTTPException:
    """產生帶結構化 detail 的 HTTPException。

    Args:
        code: 機器可讀錯誤碼（建議用 ErrorCode 常數）
        message: 英文 fallback 訊息（前端有對應 i18n key 時會被覆蓋翻譯）
        status_code: HTTP 狀態碼
        **params: i18n 插值參數（可選）
    """
    detail = {"code": code, "message": message}
    if params:
        detail["params"] = params
    return HTTPException(status_code=status_code, detail=detail)
