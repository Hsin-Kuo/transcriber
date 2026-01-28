"""
時間工具函數
職責：提供統一的時間處理函數，支援多時區
"""

from datetime import datetime, timezone, timedelta
from typing import Union


def get_utc_timestamp() -> int:
    """取得當前 UTC Unix timestamp（秒）

    Returns:
        UTC Unix timestamp（整數秒）
    """
    return int(datetime.now(timezone.utc).timestamp())


def get_current_time() -> int:
    """取得當前 UTC Unix timestamp（秒）

    Returns:
        UTC Unix timestamp（整數秒）

    Note:
        此函數為 get_utc_timestamp 的別名，保持向後相容
    """
    return get_utc_timestamp()


def timestamp_to_datetime(ts: Union[int, float]) -> datetime:
    """將 Unix timestamp 轉換為 UTC datetime

    Args:
        ts: Unix timestamp（秒）

    Returns:
        UTC datetime 對象
    """
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def format_timestamp(ts: Union[int, float], tz_offset_hours: int = 8) -> str:
    """將 Unix timestamp 格式化為指定時區的字串

    Args:
        ts: Unix timestamp（秒）
        tz_offset_hours: 時區偏移（小時），預設 8（台北時間）

    Returns:
        格式化的時間字串 (YYYY-MM-DD HH:MM:SS)
    """
    tz = timezone(timedelta(hours=tz_offset_hours))
    dt = datetime.fromtimestamp(ts, tz=tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
