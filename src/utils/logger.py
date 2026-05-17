"""結構化 logging 設定（structlog）+ FastAPI request_id middleware。

設計目標：
- 一個 request 內的所有 log 自動帶 request_id（contextvars，跨 async await 不丟）
- 線上輸出 JSON（CloudWatch / Datadog 直接 parse）
- 本地（DEPLOY_ENV=local）輸出彩色文字方便讀
- request_id 同時注入 Sentry tag，事故時可串前後 log

用法：
    from src.utils.logger import setup_logging, get_logger
    setup_logging()                                  # main.py 啟動時呼叫一次
    log = get_logger(__name__)
    log.info("user.created", user_id=str(uid))       # 結構化欄位
    log.warning("payment.failed", error=str(e), order_no=order_no)

請避免再寫 print()。
"""
import logging
import os
import sys
import uuid
from typing import Optional

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


def setup_logging() -> None:
    """app 啟動時呼叫一次。多次呼叫安全（冪等）。"""
    is_local = os.getenv("DEPLOY_ENV", "local") == "local"
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # 底層 stdlib logging：讓 uvicorn / 其他 lib 的 log 也走 stdout
    # force=True 會清掉先前 handler；前提是本函式在 main.py 所有 import 之前呼叫，
    # 確保 sentry FastApiIntegration（之後才 init）能正確 attach 到我們重設的 handler。
    # 順序：setup_logging → init_sentry → import routers/services
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if is_local:
        # 開發看人讀
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # 線上機讀
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None):
    return structlog.get_logger(name)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """為每個 HTTP request 注入 request_id 到 log context 與 Sentry tag。

    - 若 client 帶 X-Request-Id header 則沿用（方便外部追蹤）
    - 否則生成 uuid
    - response 回寫 X-Request-Id 讓 client 對應
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

        # structlog contextvars：跨 await 都會帶
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
        )

        # Sentry：失敗時 event 自動帶 request_id tag
        try:
            import sentry_sdk
            sentry_sdk.set_tag("request_id", request_id)
        except ImportError:
            pass

        try:
            response = await call_next(request)
        finally:
            # 清掉 contextvars 避免污染下個 request
            structlog.contextvars.clear_contextvars()

        response.headers["X-Request-Id"] = request_id
        return response
