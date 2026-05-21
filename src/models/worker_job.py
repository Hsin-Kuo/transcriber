"""Task dispatch payload — 對應 CONTEXT.md「TranscriptionJob」。

[[Task dispatch]] 的 typed payload。Web Server 建構，AWS 模式序列化成 SQS body、
local 模式直接交給 LocalDispatch。簽章（`_signature`）是 envelope concern，不在
本 model 內——見 WorkerDispatch。

class 名為 `TranscriptionJob`，但檔案維持 `worker_job.py`（不改檔名，避免跟
worker 薄殼 `src/worker_core/transcription_job.py` 撞名）。

Forward compat：`extra="ignore"`，舊 Worker 可安全消費新 Server 多送的欄位。
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptionJob(BaseModel):
    """[[Task dispatch]] 的單一轉錄任務指令。

    從 Web Server 端建構（router 收到 HTTP 後）。AWS 模式序列化成 JSON 發進
    SQS、Worker 端反序列化執行；local 模式直接交給 LocalDispatch。Field 名稱
    直接對應 SQS body key，已部署的 worker 向後相容無痛。
    """

    model_config = ConfigDict(extra="ignore")

    task_id: str
    """MongoDB tasks._id"""

    language: Optional[str] = None
    """ISO 語言代碼；None 代表 Whisper 自動偵測"""

    use_chunking: bool = True
    """是否將長音檔切段平行處理"""

    use_punctuation: bool = True
    """是否在轉錄後跑標點 enhance"""

    punctuation_provider: str = Field(default="gemini")
    """標點 provider：gemini / openai / none"""

    use_diarization: bool = False
    """是否啟用 speaker diarization (pyannote)"""

    max_speakers: Optional[int] = None
    """diarization 最大說話者數；None = 自動。為 1 時 diarization 無意義，
    `_normalize_single_speaker` 會強制 use_diarization=False。"""

    ui_language: Optional[str] = None
    """使用者介面語言；影響繁/簡標點與訊息語系。None = 預設。"""

    handoff_ext: Optional[str] = None
    """Handoff audio 副檔名（不含 dot），例如 "wav"。Worker 用此推 S3 key
    `handoff/{task_id}.{ext}`。local 模式不使用。None = 來自舊版 Server（Layer
    2 前），Worker fallback 到 `uploads/{tier}/{task_id}.mp3` 下載——SQS 排空後可拔。"""

    @model_validator(mode="after")
    def _normalize_single_speaker(self) -> "TranscriptionJob":
        """max_speakers == 1 時 diarization 無意義，強制關閉。

        放在 model 層讓兩個 dispatch adapter 行為一致（舊版只有 local 端做）。
        """
        if self.max_speakers == 1:
            self.use_diarization = False
        return self
