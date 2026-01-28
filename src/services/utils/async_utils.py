"""
異步工具函數
職責：提供異步編程的輔助函數
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Coroutine, Union

# 從 time_utils 重新導出時間函數，保持向後相容
from src.utils.time_utils import (
    get_utc_timestamp,
    get_current_time,
    timestamp_to_datetime,
    format_timestamp
)


def run_async_in_thread(coro: Coroutine) -> Any:
    """在新的事件循環中執行異步函數

    用於在同步上下文（如線程池）中執行異步代碼

    Args:
        coro: 要執行的協程

    Returns:
        協程的返回值

    Example:
        >>> async def my_async_func():
        ...     return "result"
        >>> result = run_async_in_thread(my_async_func())
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
