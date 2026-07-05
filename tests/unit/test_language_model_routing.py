"""依語言路由 Whisper 模型的純函數單元測試(不載入實際模型,快)。

涵蓋 worker_core.model_cache._resolve_model_path 的 override/fallback 行為、
config.LANGUAGE_MODEL_OVERRIDES 的 env 解析,以及 _normalize_language 對台語
代碼的映射。實際模型載入與轉錄行為需在 staging GPU 實機驗證。
"""
import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.worker_core import model_cache  # noqa: E402
from src.services.utils.whisper_processor import _normalize_language  # noqa: E402


class TestResolveModelPath:
    """語言有 override 用專用模型,其餘一律 DEFAULT_MODEL。"""

    def test_no_language_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(model_cache, "LANGUAGE_MODEL_OVERRIDES", {"nan-TW": "/opt/models/breeze"})
        assert model_cache._resolve_model_path(None) == model_cache.DEFAULT_MODEL

    def test_language_without_override_falls_back(self, monkeypatch):
        monkeypatch.setattr(model_cache, "LANGUAGE_MODEL_OVERRIDES", {"nan-TW": "/opt/models/breeze"})
        assert model_cache._resolve_model_path("zh-TW") == model_cache.DEFAULT_MODEL
        assert model_cache._resolve_model_path("ja") == model_cache.DEFAULT_MODEL

    def test_language_with_override_routes(self, monkeypatch):
        monkeypatch.setattr(model_cache, "LANGUAGE_MODEL_OVERRIDES", {"nan-TW": "/opt/models/breeze"})
        assert model_cache._resolve_model_path("nan-TW") == "/opt/models/breeze"

    def test_empty_overrides_always_default(self, monkeypatch):
        # worker 未設 WHISPER_MODEL_NAN_TW 時的行為:台語任務退回預設模型
        monkeypatch.setattr(model_cache, "LANGUAGE_MODEL_OVERRIDES", {})
        assert model_cache._resolve_model_path("nan-TW") == model_cache.DEFAULT_MODEL


class TestConfigEnvParsing:
    """LANGUAGE_MODEL_OVERRIDES 由 env 建表:未設定的語言不進表。"""

    def _reload_config(self):
        import src.worker_core.config as cfg
        return importlib.reload(cfg)

    def test_env_set_creates_entry(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL_NAN_TW", "/opt/models/breeze-asr-26-ct2")
        try:
            cfg = self._reload_config()
            assert cfg.LANGUAGE_MODEL_OVERRIDES == {"nan-TW": "/opt/models/breeze-asr-26-ct2"}
        finally:
            monkeypatch.delenv("WHISPER_MODEL_NAN_TW")
            self._reload_config()

    def test_env_unset_empty_table(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MODEL_NAN_TW", raising=False)
        cfg = self._reload_config()
        assert cfg.LANGUAGE_MODEL_OVERRIDES == {}


class TestNormalizeLanguageTaiwanese:
    """nan-TW 與 zh-TW/zh-CN 一樣映到 whisper 唯一認得的 zh。"""

    def test_taiwanese_maps_to_zh(self):
        assert _normalize_language("nan-TW") == "zh"

    def test_existing_mappings_unchanged(self):
        assert _normalize_language("zh-TW") == "zh"
        assert _normalize_language("zh-CN") == "zh"
        assert _normalize_language("en") == "en"
        assert _normalize_language(None) is None
