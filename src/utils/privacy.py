"""PII / 隱私敏感資料處理 helpers。"""
from __future__ import annotations


def mask_email(email: str) -> str:
    """把 email 部分遮蔽用於 log 輸出。

    保留首兩字 + domain，方便除錯時辨識但不暴露完整地址。

    >>> mask_email("alice@example.com")
    'al***@example.com'
    >>> mask_email("a@example.com")
    'a***@example.com'
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
    keep = local[:2] if len(local) >= 2 else local[:1]
    return f"{keep}***@{domain}"
