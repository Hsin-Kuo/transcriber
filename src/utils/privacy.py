"""PII / 隱私敏感資料處理 helpers。"""
from __future__ import annotations


def mask_email(email: str) -> str:
    """把 email 部分遮蔽用於 log 輸出。

    保留首字 + domain，方便除錯時辨識但不暴露完整地址。

    >>> mask_email("alice@example.com")
    'a***@example.com'
    >>> mask_email("ab@example.com")
    'a***@example.com'
    >>> mask_email("a@example.com")
    '***@example.com'
    >>> mask_email("not-an-email")
    '***'

    audit_logs 與 user.email DB 欄位仍保留完整 email；本 helper 僅用於
    應用層的 structured log（logs 較可能被廣泛 retain / 外送到第三方）。
    """
    if not isinstance(email, str) or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "***"
    # 只露首字 — 2 字 localpart（如 "ab"）會把整個 localpart 暴露
    # 超過 1 字以「首字 + ***」呈現；單字直接 "***" 避免唯一識別
    if len(local) <= 1:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"
