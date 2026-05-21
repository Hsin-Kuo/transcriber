"""
Whisper 與 Diarization 模型快取

模型只在首次呼叫時載入，之後重複使用同一實例，
避免每個任務都重新載入（載入時間約 30-60 秒）。
"""

from src.worker_core.config import DEFAULT_MODEL
from src.utils.config_loader import get_parameter
from src.utils.logger import get_logger

log = get_logger(__name__)

_cached_whisper_processor = None
_cached_diarization_pipeline = None
_diarization_load_attempted = False  # 防止無 HF_TOKEN 時每次呼叫都重試


def get_whisper_processor():
    global _cached_whisper_processor
    if _cached_whisper_processor is None:
        from faster_whisper import WhisperModel
        from src.services.utils.whisper_processor import WhisperProcessor

        log.info("whisper.model.loading", model=DEFAULT_MODEL, compute_type="float16")
        whisper_model = WhisperModel(DEFAULT_MODEL, device="auto", compute_type="float16")
        _cached_whisper_processor = WhisperProcessor(whisper_model, DEFAULT_MODEL)
        log.info("whisper.model.loaded", model=DEFAULT_MODEL)
    return _cached_whisper_processor


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
