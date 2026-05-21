"""TranscriptionOrchestrator 純函數單元測試(不需 Mongo,快)。

涵蓋從舊 src/services/transcription_orchestrator.py 搬過來、行為未變的
_resolve_punct_language。完整 pipeline 行為見 test_orchestrator_integration.py。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.transcription.orchestrator import _resolve_punct_language  # noqa: E402


class TestResolvePunctLanguage:
    """標點語言解析:明確繁/簡 > zh 時依 UI 語言 > 其他語言。"""

    def test_explicit_zh_tw(self):
        assert _resolve_punct_language("zh-TW", "en", None) == "zh-TW"

    def test_explicit_zh_cn(self):
        assert _resolve_punct_language("zh-CN", "en", None) == "zh-CN"

    def test_detected_zh_with_cn_ui(self):
        assert _resolve_punct_language(None, "zh", "zh-CN") == "zh-CN"

    def test_detected_zh_defaults_tw(self):
        assert _resolve_punct_language(None, "zh", None) == "zh-TW"
        assert _resolve_punct_language(None, "zh", "en") == "zh-TW"

    def test_other_language_passthrough(self):
        assert _resolve_punct_language(None, "en", None) == "en"
        assert _resolve_punct_language("ja", None, None) == "ja"

    def test_default_zh_when_all_none(self):
        assert _resolve_punct_language(None, None, None) == "zh"
