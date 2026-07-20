"""已刪除帳號的去識別化顯示標籤。

帳號刪除後 email 設為 None（去識別化，見 auth.delete_account）。後台各處若直接
印 email 會變空白，影響瀏覽。這裡提供「穩定假名」——由內部使用者 id 衍生，
同一帳號永遠對到同一標籤，可讓 admin 辨別關聯，且不含個資、不可逆推。
"""
from typing import Optional


def deleted_user_label(user_id) -> str:
    """已刪除帳號的穩定去識別假名，例如「已刪除用戶#a1b2c3」。"""
    uid = str(user_id) if user_id else ""
    return f"已刪除用戶#{uid[-6:]}" if uid else "已刪除用戶"


def user_email_or_label(email: Optional[str], user_id, *, deleted: bool = None) -> str:
    """顯示用 email：有 email 用 email；已刪除帳號回假名；其餘回 '—'。

    deleted 未指定時，以「無 email」推定為已刪除（正常帳號一律有 email）。
    """
    if email:
        return email
    if deleted is None:
        deleted = user_id is not None
    return deleted_user_label(user_id) if deleted else "—"
