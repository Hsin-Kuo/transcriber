"""structlog setup + RequestIdMiddleware 測試（M4）。"""
import os
import sys
from pathlib import Path

# 設一個有效的 JWT_SECRET_KEY 讓 import src.* 鏈不炸（main.py 不 import 但保險）
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
import structlog  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.utils.logger import (  # noqa: E402
    RequestIdMiddleware,
    get_logger,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _setup():
    setup_logging()
    yield
    structlog.contextvars.clear_contextvars()


def _make_app():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping():
        # 在這裡讀 contextvars，模擬 handler 內取得 request_id
        ctx = structlog.contextvars.get_contextvars()
        return {"context": ctx}

    return app


class TestRequestIdMiddleware:
    def test_generates_uuid_when_no_header(self):
        client = TestClient(_make_app())
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert "x-request-id" in {k.lower() for k in resp.headers}
        ctx = resp.json()["context"]
        assert "request_id" in ctx
        # UUID4 hex 長度 = 36（含 -）
        assert len(ctx["request_id"]) == 36
        assert ctx["path"] == "/ping"
        assert ctx["method"] == "GET"

    def test_honors_incoming_header(self):
        client = TestClient(_make_app())
        custom_id = "client-supplied-trace-123"
        resp = client.get("/ping", headers={"X-Request-Id": custom_id})
        assert resp.headers["X-Request-Id"] == custom_id
        assert resp.json()["context"]["request_id"] == custom_id

    def test_each_request_isolated(self):
        client = TestClient(_make_app())
        id1 = client.get("/ping").json()["context"]["request_id"]
        id2 = client.get("/ping").json()["context"]["request_id"]
        assert id1 != id2


class TestGetLogger:
    def test_returns_bound_logger(self):
        log = get_logger("test_module")
        # 不會 raise，且能呼叫 .info / .warning / .error
        log.info("test_event", value=1)
        log.warning("test_warn", error="x")
        log.error("test_err")
