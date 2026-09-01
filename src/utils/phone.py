"""電話號碼正規化。

91APP 正式環境對 `initCardTokenType=BindingCard` 交易的 cardHolder.phoneNumber 為必填
（prod 400 CardHolderPhoneNumberRequired；sandbox 不驗）。目前系統完全沒收過電話，
這裡提供台灣手機號碼正規化的純函式，供結帳/加購/換卡等綁卡交易入口共用。
"""
import re

# 本地格式：09 開頭 10 碼數字（e.g. 0912345678）
_TW_MOBILE_LOCAL_RE = re.compile(r"^09\d{8}$")
# 國際碼格式：+886 9 開頭 + 8 碼數字（e.g. +886912345678）
_TW_MOBILE_INTL_RE = re.compile(r"^\+8869\d{8}$")


def normalize_tw_phone(raw: str) -> str:
    """正規化台灣手機號碼為 91APP cardHolder.phoneNumber 要求的 `+8869xxxxxxxx` 格式。

    接受 `09xxxxxxxx`（本地 10 碼）或 `+8869xxxxxxxx`（國際碼），中間允許空白/dash
    （先剝除再驗證）。格式不符（含空值）一律 raise ValueError，由呼叫端轉換成
    422 API 錯誤。
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("phone number is required")
    cleaned = re.sub(r"[\s\-]", "", raw)
    if _TW_MOBILE_LOCAL_RE.fullmatch(cleaned):
        return "+886" + cleaned[1:]
    if _TW_MOBILE_INTL_RE.fullmatch(cleaned):
        return cleaned
    raise ValueError(f"invalid TW mobile phone number: {raw!r}")
