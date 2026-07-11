"""後端安全 headers middleware 回歸測試（XSS audit TODO-6）。

nginx 是主力防線（見 deploy/nginx-*.conf 的 CSP/HSTS），這裡驗證的是
defense-in-depth 那層：本地開發、未來容器化、或 SG 誤開 8000 對外時，
後端本身也不能完全裸奔。

SSE streaming 相容性（BaseHTTPMiddleware 是否會 buffer StreamingResponse）
無法用 TestClient 驗證——httpx 的 ASGITransport 本身會把整個 streaming
response 收完才一次回傳，跟真實 uvicorn+socket 的行為不同，會產生假陽性
的「有 buffer」訊號。改用真的 uvicorn process + 真實 socket 手動驗證過：
四個間隔 0.3s 的 SSE chunk 確實以 ~0.3s 間隔逐塊送達（見 PR 說明），
不是等整個 generator 跑完才一次送出。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from src.main import app  # noqa: E402

client = TestClient(app)


def test_docs_response_has_security_headers():
    r = client.get("/docs")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_404_response_still_has_security_headers():
    # middleware 對所有 response 生效，不只是 2xx——確認錯誤路徑也有 header
    r = client.get("/this-route-does-not-exist")
    assert r.status_code == 404
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


def test_middleware_does_not_set_csp():
    # CSP 刻意留給 nginx 管，後端不下 CSP header（見 TODO-6 說明）
    r = client.get("/docs")
    assert "content-security-policy" not in {k.lower() for k in r.headers.keys()}
