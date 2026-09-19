"""
DiarizationProcessor - 說話者辨識處理器
職責：使用 pyannote.audio 進行說話者辨識（Speaker Diarization）
"""

from pathlib import Path
from typing import Optional, List, Dict
import os

from src.utils.logger import get_logger

log = get_logger(__name__)

# 說話者辨識模型名稱（單一來源；載入與記錄任務 models.diarization 都引用此常數）
# community-1（pyannote.audio 4.x）：staging POC 2026-09-19 實測——同性別相近聲音
# 可分離（3.1 做不到）、過切大幅收斂（同支難錄音 15→8 人，真實 ~7）、
# 自動偵測可自行收斂到正確人數；T4 峰值 VRAM 1.71GB、48 分鐘音檔 112 秒。
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"


class DiarizationProcessor:
    """說話者辨識處理器

    使用 pyannote.audio 的 speaker diarization 模型
    """

    def __init__(self, pipeline=None, hf_token: Optional[str] = None):
        """初始化 DiarizationProcessor

        Args:
            pipeline: pyannote.audio Pipeline 實例（可選）
            hf_token: Hugging Face Token（用於加載模型）
        """
        self.pipeline = pipeline
        self.hf_token = hf_token or os.getenv("HF_TOKEN")
        self.model_name = DIARIZATION_MODEL  # 供 orchestrator 回寫 task models.diarization

    def is_available(self) -> bool:
        """檢查 diarization 功能是否可用

        Returns:
            是否可用
        """
        try:
            import pyannote.audio
            return self.pipeline is not None or self.hf_token is not None
        except ImportError:
            return False

    @staticmethod
    def _load_waveform(audio_path: Path) -> Dict:
        """把音檔載成 pyannote 4.x 的 waveform dict 輸入。

        **必須走記憶體 waveform、禁止把檔案路徑傳給 pipeline**：4.x 的檔案解碼
        改用 torchcodec（需要 FFmpeg 共享庫，GPU worker 的 DLAMI 沒有）。
        waveform dict 路徑完全不觸碰 torchcodec（4.0.6+ 對缺庫優雅降級，
        import 只 warning）。上游 orchestrator 已固定餵 16k WAV，soundfile 可直讀。
        """
        import soundfile as sf
        import torch

        data, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=True)
        return {"waveform": torch.from_numpy(data.T), "sample_rate": sample_rate}

    @staticmethod
    def _collect_segments(output) -> List[Dict]:
        """把 pyannote 4.x 的輸出物件轉成本專案 segments 格式。

        4.x breaking change：pipeline 不再回傳 Annotation（3.x 用
        `itertracks(yield_label=True)` 三元組），改回傳 output 物件，
        `output.speaker_diarization` 迭代出 (turn, speaker) 二元組。
        另有 output.exclusive_speaker_diarization（無重疊版本，對 ASR 對齊
        更友善）——尚未採用，見 memory diarization-exact-speaker-count 遺留。
        """
        return [
            {"start": turn.start, "end": turn.end, "speaker": speaker}
            for turn, speaker in output.speaker_diarization
        ]

    @staticmethod
    def _build_speaker_kwargs(max_speakers) -> Dict:
        """把講者人數轉成 pyannote pipeline kwargs（單一來源，兩條執行路徑共用）。

        語意變更（2026-09-19）：人數 = 確切人數（num_speakers=N，強制聚成 N 簇），
        不再是上限（min=1, max=N）。原因：max 只是上限，pipeline 可自行輸出更少
        人——同性別相近聲音常被聚成一簇（實際回報：2 女 1 男被辨識成 2 人），
        使用者填人數時強制簇數是 pyannote 3.1 下最有效的解法。UI 文案同步改為
        「說話者人數」並說明此語意；留空維持自動偵測。

        越界（<2 或 >10）一律回自動偵測，與 HTTP 層白名單一致。
        """
        if max_speakers is None or not (2 <= max_speakers <= 10):
            return {}
        return {"num_speakers": max_speakers}

    def perform_diarization(
        self,
        audio_path: Path,
        max_speakers: Optional[int] = None
    ) -> Optional[List[Dict]]:
        """執行說話者辨識

        Args:
            audio_path: 音檔路徑
            max_speakers: 最大講者人數（可選，2-10）

        Returns:
            Diarization segments 列表，格式：
            [{"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"}, ...]
            如果失敗則返回 None
        """
        if not self.pipeline:
            log.warning("diarization.pipeline_not_initialized")
            return None

        try:
            log.debug("diarization.started")

            # 準備 diarization 參數
            diarization_kwargs = self._build_speaker_kwargs(max_speakers)
            log.debug("diarization.params", max_speakers=max_speakers, diarization_kwargs=diarization_kwargs)
            output = self.pipeline(self._load_waveform(audio_path), **diarization_kwargs)

            segments = self._collect_segments(output)
            num_speakers = len(set(s['speaker'] for s in segments))
            log.info("diarization.completed", num_speakers=num_speakers)
            return segments

        except Exception as e:
            log.error("diarization.failed", error=str(e), exc_info=True)
            return None

    def perform_diarization_in_process(
        self,
        audio_path: Path,
        max_speakers: Optional[int] = None
    ) -> Optional[List[Dict]]:
        """在獨立進程中執行說話者辨識（可被強制終止）

        此方法會在獨立進程中重新載入 pipeline，
        避免跨進程傳遞對象的問題，且可以被強制終止

        Args:
            audio_path: 音檔路徑
            max_speakers: 最大講者人數（可選，2-10）

        Returns:
            Diarization segments 列表，格式：
            [{"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"}, ...]
            如果失敗則返回 None
        """
        try:
            # 在進程中重新載入 pipeline（因為無法跨進程傳遞）
            from pyannote.audio import Pipeline

            log.debug("diarization.pipeline_loading", in_process=True)
            import torch
            # 4.x + huggingface_hub 1.x：直接傳 token=，不再走全域 login()
            pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=self.hf_token or None)

            # GPU 加速：優先 CUDA，其次 MPS
            if torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))
                log.debug("diarization.device_selected", in_process=True, device="cuda", device_name=torch.cuda.get_device_name(0))
            elif torch.backends.mps.is_available():
                pipeline.to(torch.device("mps"))
                log.debug("diarization.device_selected", in_process=True, device="mps")

            log.debug("diarization.started", in_process=True)

            # 準備 diarization 參數
            diarization_kwargs = self._build_speaker_kwargs(max_speakers)
            log.debug("diarization.params", in_process=True, max_speakers=max_speakers, diarization_kwargs=diarization_kwargs)
            output = pipeline(self._load_waveform(audio_path), **diarization_kwargs)

            segments = self._collect_segments(output)
            num_speakers = len(set(s['speaker'] for s in segments))
            log.info("diarization.completed", in_process=True, num_speakers=num_speakers)
            return segments

        except Exception as e:
            log.error("diarization.failed", in_process=True, error=str(e), exc_info=True)
            return None

    @staticmethod
    def load_pipeline(hf_token: Optional[str] = None):
        """載入 diarization pipeline

        Args:
            hf_token: Hugging Face Token

        Returns:
            Pipeline 實例，失敗則返回 None
        """
        try:
            from pyannote.audio import Pipeline
            import torch

            hf_token = hf_token or os.getenv("HF_TOKEN")

            if not hf_token:
                log.warning("diarization.hf_token_missing")
                return None

            log.debug("diarization.model.loading")
            # 4.x + huggingface_hub 1.x：直接傳 token=，不再走全域 login()
            pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=hf_token)

            # GPU 加速：優先 CUDA，其次 MPS
            if torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))
                log.info("diarization.model.loaded", device="cuda", device_name=torch.cuda.get_device_name(0))
            elif torch.backends.mps.is_available():
                pipeline.to(torch.device("mps"))
                log.info("diarization.model.loaded", device="mps")
            else:
                log.warning("diarization.model.loaded", device="cpu")

            return pipeline

        except ImportError:
            log.warning("diarization.pyannote_not_installed")
            return None
        except Exception as e:
            log.error(
                "diarization.model.load_failed",
                error=str(e),
                hint="請確認 HF_TOKEN 的帳號已同意條款：https://huggingface.co/pyannote/speaker-diarization-community-1",
                exc_info=True,
            )
            return None
