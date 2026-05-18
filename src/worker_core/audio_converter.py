"""音檔格式轉換 — Worker 端 thin re-export。

實作放在 [src/utils/audio_converter.py](../utils/audio_converter.py)，兩個進程
共用同一份。Worker 因為歷史 import path 保留此檔當 forwarder，方便逐步遷移
（之後 Orchestrator 統一後可以拔掉，把 callers 直接指向 utils 版本）。

對應 CONTEXT.md「Compact audio」。
"""
from src.utils.audio_converter import convert_to_mp3, convert_to_wav

__all__ = ["convert_to_mp3", "convert_to_wav"]
