"""
DiarizationProcessor - 說話者辨識處理器
職責：使用 pyannote.audio 進行說話者辨識（Speaker Diarization）
"""

from pathlib import Path
from typing import Optional, List, Dict
import os


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
            print("⚠️ Diarization pipeline 未初始化")
            return None

        try:
            print(f"🔊 正在分析說話者...")

            # 準備 diarization 參數
            diarization_kwargs = {}
            if max_speakers is not None and 2 <= max_speakers <= 10:
                # pyannote.audio 需要同時設定 min_speakers 和 max_speakers
                diarization_kwargs["min_speakers"] = 1
                diarization_kwargs["max_speakers"] = max_speakers
                print(f"   設定講者人數範圍：1-{max_speakers} 人")

            print(f"   Diarization 參數：{diarization_kwargs}")
            diarization = self.pipeline(str(audio_path), **diarization_kwargs)

            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start,
                    "end": turn.end,
                    "speaker": speaker
                })

            num_speakers = len(set(s['speaker'] for s in segments))
            print(f"✅ 說話者分析完成，識別到 {num_speakers} 位說話者")
            return segments

        except Exception as e:
            print(f"⚠️ Speaker diarization 失敗：{e}")
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
            from huggingface_hub import login

            if self.hf_token:
                login(token=self.hf_token, add_to_git_credential=False)

            print(f"🔊 [進程] 正在載入 diarization pipeline...")
            import torch
            pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

            # M1 Mac MPS 加速
            if torch.backends.mps.is_available():
                pipeline.to(torch.device("mps"))
                print(f"🔊 [進程] 使用 MPS 加速")

            print(f"🔊 [進程] 正在分析說話者...")

            # 準備 diarization 參數
            diarization_kwargs = {}
            if max_speakers is not None and 2 <= max_speakers <= 10:
                diarization_kwargs["min_speakers"] = 1
                diarization_kwargs["max_speakers"] = max_speakers
                print(f"   [進程] 設定講者人數範圍：1-{max_speakers} 人")

            print(f"   [進程] Diarization 參數：{diarization_kwargs}")
            diarization = pipeline(str(audio_path), **diarization_kwargs)

            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start,
                    "end": turn.end,
                    "speaker": speaker
                })

            num_speakers = len(set(s['speaker'] for s in segments))
            print(f"✅ [進程] 說話者分析完成，識別到 {num_speakers} 位說話者")
            return segments

        except Exception as e:
            print(f"⚠️ [進程] Speaker diarization 失敗：{e}")
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
            from huggingface_hub import login
            import torch

            hf_token = hf_token or os.getenv("HF_TOKEN")

            if not hf_token:
                print("ℹ️ 未設定 HF_TOKEN，speaker diarization 功能不可用")
                return None

            # 使用 huggingface_hub 登入
            login(token=hf_token, add_to_git_credential=False)

            print("🔊 正在載入 Speaker Diarization 模型...")
            pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

            # M1 Mac MPS 加速
            if torch.backends.mps.is_available():
                pipeline.to(torch.device("mps"))
                print("✅ Speaker Diarization 模型載入完成（使用 MPS 加速）！")
            else:
                print("✅ Speaker Diarization 模型載入完成！")

            return pipeline

        except ImportError:
            print("⚠️ pyannote.audio 未安裝，speaker diarization 功能不可用")
            return None
        except Exception as e:
            print(f"⚠️ Speaker Diarization 模型載入失敗：{e}")
            print("   請確認已在 Hugging Face 同意使用條款：https://huggingface.co/pyannote/speaker-diarization-3.1")
            return None
