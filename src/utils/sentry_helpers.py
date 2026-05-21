"""Sentry-aware async helpers。

未捕獲的 asyncio task 例外：在 Python 中，若 task 因 GC 被回收前沒 await，
其 exception 預設只會印到 stderr。Sentry FastAPI integration 只 hook HTTP
request 路徑，背景 task 默默吞掉的錯誤抓不到。

本模組提供 create_background_task：
- 等價 asyncio.create_task
- task done 後若有 exception，呼叫 sentry_sdk.capture_exception
- 同時印 stderr，保留原始除錯資訊
"""
import asyncio
from typing import Any, Coroutine, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


def _capture_task_exception(task: "asyncio.Task[Any]") -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return

    # 記錄背景 task 例外，無論 Sentry 是否啟用都看得到
    name = task.get_name()
    logger.error(
        "sentry.background_task_failed",
        task_name=name,
        error_type=type(exc).__name__,
        error=str(exc),
        exc_info=exc,
    )

    # Sentry capture（未初始化時為 no-op）
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("task_name", name)
            scope.set_context("background_task", {"name": name})
            sentry_sdk.capture_exception(exc)
    except ImportError:
        pass
    except Exception as e:
        # Sentry 自己壞掉也不能影響主流程
        logger.warning("sentry.capture_failed", error=str(e))


def create_background_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: Optional[str] = None,
) -> "asyncio.Task[Any]":
    """像 asyncio.create_task，但 task 失敗時會送 Sentry。

    Args:
        coro: 要 schedule 的 coroutine
        name: task 名稱（會出現在 Sentry tag 與 stderr）
    """
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_capture_task_exception)
    return task
