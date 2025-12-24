"""
異步工具函數
職責：提供異步編程的輔助函數
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Coroutine

# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))


def get_current_time() -> str:
    """取得 UTC+8 當前時間

    Returns:
        格式化的時間字串 (YYYY-MM-DD HH:MM:SS)
    """
    return datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")


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
