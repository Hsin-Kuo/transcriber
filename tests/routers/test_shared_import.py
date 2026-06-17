"""回歸:shared 路由的 import 必須完整解析。

bug 史:tasks.py 瘦身重構把 _is_audio_expired 改名 is_audio_expired 並搬到
task_query_helpers，但 shared.py 仍 `from .tasks import _is_audio_expired`（且是函式內
lazy import，CI 沒測到）→ 分享「有音檔」的任務時 ImportError → 500。
改成 module-level import 後，任何 import（含本測試 / app 啟動）都會在啟動期抓到斷裂。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_shared_router_imports_cleanly():
    from src.routers import shared
    # 曾漏改的 import：is_audio_expired（原 _is_audio_expired，已搬到 task_query_helpers）
    assert hasattr(shared, "is_audio_expired") and callable(shared.is_audio_expired)
    assert callable(shared.get_shared_task)
