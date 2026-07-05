"""
Whisper 與 Diarization 模型快取

模型只在首次呼叫時載入，之後重複使用同一實例，
避免每個任務都重新載入（載入時間約 30-60 秒）。
"""

from typing import Optional

from src.worker_core.config import DEFAULT_MODEL, LANGUAGE_MODEL_OVERRIDES
from src.utils.config_loader import get_parameter
from src.utils.logger import get_logger

log = get_logger(__name__)

# key = 解析後的模型名稱/路徑（非 language）：不同語言若解析到同一模型，共用同一實例
_cached_whisper_processors: dict = {}
_cached_diarization_pipeline = None
_diarization_load_attempted = False  # 防止無 HF_TOKEN 時每次呼叫都重試


def _resolve_model_path(language: Optional[str] = None) -> str:
    if language and language in LANGUAGE_MODEL_OVERRIDES:
        return LANGUAGE_MODEL_OVERRIDES[language]
    return DEFAULT_MODEL


def get_whisper_processor(language: Optional[str] = None):
    """依語言取得 WhisperProcessor。

    有 LANGUAGE_MODEL_OVERRIDES 對應的語言載入專用模型（lazy，首個該語言
    任務才載入），其餘語言（含 None）用 DEFAULT_MODEL。已載入的模型常駐
    不卸載——T4 16GB 實測 default+台語+diarization 三者常駐峰值僅 ~7.8GB。
    """
    model_path = _resolve_model_path(language)
    if model_path not in _cached_whisper_processors:
        from faster_whisper import WhisperModel
        from src.services.utils.whisper_processor import WhisperProcessor

        log.info(
            "whisper.model.loading",
            model=model_path,
            language=language,
            compute_type="float16",
        )
        whisper_model = WhisperModel(model_path, device="auto", compute_type="float16")
        _cached_whisper_processors[model_path] = WhisperProcessor(whisper_model, model_path)
        log.info("whisper.model.loaded", model=model_path)
    return _cached_whisper_processors[model_path]


def get_diarization_pipeline():
    global _cached_diarization_pipeline, _diarization_load_attempted
    if _diarization_load_attempted:
        return _cached_diarization_pipeline

    _diarization_load_attempted = True
    from src.services.utils.diarization_processor import DiarizationProcessor

    hf_token = get_parameter("/transcriber/hf-token", fallback_env="HF_TOKEN", default="")
    if not hf_token:
        log.warning("diarization.disabled", reason="no_hf_token")
        return None

    log.info("diarization.model.loading")
    _cached_diarization_pipeline = DiarizationProcessor.load_pipeline(hf_token)
    if _cached_diarization_pipeline:
        log.info("diarization.model.loaded")
    else:
        log.warning("diarization.model.load_failed")
    return _cached_diarization_pipeline
