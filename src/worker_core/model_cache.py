"""
Whisper 與 Diarization 模型快取

模型只在首次呼叫時載入，之後重複使用同一實例，
避免每個任務都重新載入（載入時間約 30-60 秒）。
"""

from src.worker_core.config import DEFAULT_MODEL
from src.utils.config_loader import get_parameter

_cached_whisper_processor = None
_cached_diarization_pipeline = None
_diarization_load_attempted = False  # 防止無 HF_TOKEN 時每次呼叫都重試


def get_whisper_processor():
    global _cached_whisper_processor
    if _cached_whisper_processor is None:
        from faster_whisper import WhisperModel
        from src.services.utils.whisper_processor import WhisperProcessor

        print(f"🔄 [Worker] 載入 Whisper 模型: {DEFAULT_MODEL} (float16)...")
        whisper_model = WhisperModel(DEFAULT_MODEL, device="auto", compute_type="float16")
        _cached_whisper_processor = WhisperProcessor(whisper_model, DEFAULT_MODEL)
        print("✅ [Worker] Whisper 模型載入完成")
    return _cached_whisper_processor


def get_diarization_pipeline():
    global _cached_diarization_pipeline, _diarization_load_attempted
    if _diarization_load_attempted:
        return _cached_diarization_pipeline

    _diarization_load_attempted = True
    from src.services.utils.diarization_processor import DiarizationProcessor

    hf_token = get_parameter("/transcriber/hf-token", fallback_env="HF_TOKEN", default="")
    if not hf_token:
        print("⚠️ [Worker] 未設定 HF_TOKEN，Diarization 不可用")
        return None

    print("🔄 [Worker] 載入 Diarization 模型...")
    _cached_diarization_pipeline = DiarizationProcessor.load_pipeline(hf_token)
    if _cached_diarization_pipeline:
        print("✅ [Worker] Diarization 模型載入完成")
    else:
        print("⚠️ [Worker] Diarization 模型載入失敗")
    return _cached_diarization_pipeline
