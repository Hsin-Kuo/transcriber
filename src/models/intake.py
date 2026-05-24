"""Transcription intake models — IntakeConfig + IntakeResult."""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class IntakeConfig:
    """Router 解析完 HTTP 後傳給 IntakeService 的配置包。"""

    task_type: str = "paragraph"
    punct_provider: str = "gemini"
    chunk_audio: bool = True
    chunk_minutes: int = 10
    diarize: bool = False
    max_speakers: Optional[int] = None
    language: str = "zh"
    ui_language: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    custom_name: Optional[str] = None
    batch_id: Optional[str] = None


@dataclass
class IntakeResult:
    """intake() 的回傳值。"""

    task_id: str
    status: str
    queue_position: int = 0
    filename: str = ""
    size_mb: float = 0.0
