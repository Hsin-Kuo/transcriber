"""Worker job 訊息合約。

Web Server 與 Worker 之間透過 SQS 傳遞的 typed payload。簽章
（`_signature`）是 envelope concern，不在本 model 內——見 WorkerDispatch。

Forward compat：`extra="ignore"`，舊 Worker 可安全消費新 Server 多送的欄位。
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionWorkerJob(BaseModel):
    """Worker 收到的單一轉錄任務指令。

    從 Web Server 端建構（router 收到 HTTP 後）、序列化成 JSON 發進 SQS、
    Worker 端反序列化執行。Field 名稱直接對應 SQS body key，已部署的 worker
    向後相容無痛。
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
    """diarization 最大說話者數；None = 自動"""

    handoff_ext: Optional[str] = None
    """Handoff audio 副檔名（不含 dot），例如 "wav"。Worker 用此推 S3 key
    `handoff/{task_id}.{ext}`。None = 來自舊版 Server（Layer 2 前），Worker
    fallback 到 `uploads/{tier}/{task_id}.mp3` 下載——SQS 排空後可拔。"""
