"""使用者同意條款（服務條款 / 隱私權政策）版本與同意軌跡。

同意存證的單一來源：條款版本號由後端維護，不採信前端傳入的版本或時間戳；
`accepted_at` 一律用 server 端 UTC，避免竄改。條款內容有實質變動時，更新
`CURRENT_TERMS_VERSION`，之後新建立的帳號會快照當下版本。
"""
from typing import Optional

from .time_utils import get_utc_timestamp

# 目前生效的服務條款 / 隱私權政策版本（YYYY-MM-DD）。
# 條款內容有實質變動時更新此值——同意紀錄會快照使用者建帳當下的版本。
CURRENT_TERMS_VERSION = "2026-07-19"


def build_consent_record(method: str, ip: Optional[str] = None) -> dict:
    """建立同意軌跡快照（寫入 user document 的 `consent` 欄位）。

    Args:
        method: 同意來源（"register" | "google"）。
        ip: 用戶端 IP（best-effort，供稽核；取不到給 None）。

    版本與時間一律由 server 決定，不採信前端。
    """
    return {
        "agreed": True,
        "terms_version": CURRENT_TERMS_VERSION,
        "accepted_at": get_utc_timestamp(),
        "method": method,
        "ip": ip,
    }
