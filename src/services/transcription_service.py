"""TranscriptionService — 本地(同進程)模式的轉錄協調。

把 router 已放在 disk 上的音檔包成 LocalFileSource,submit 統一的
TranscriptionOrchestrator.run 進線程池。AWS 模式由 worker_core 走 S3Source,
兩者共用同一個 Orchestrator(見 src/transcription/)。
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from src.database.sync_client import get_sync_db
from src.transcription.audio_source import LocalFileSource
from src.transcription.orchestrator import TranscriptionOrchestrator


class TranscriptionService:
    """本地模式轉錄協調服務。"""

    def __init__(
        self,
        task_service,
        whisper_processor,
        punctuation_processor,
        progress_store,
        diarization_processor=None,
        executor: Optional[ThreadPoolExecutor] = None,
    ):
        # task_service 供 router 透過 transcription_service.task_service 取用
        self.task_service = task_service
        self.progress_store = progress_store
        self.executor = executor or ThreadPoolExecutor(max_workers=3)
        self.orchestrator = TranscriptionOrchestrator(
            db=get_sync_db(),
            progress_store=progress_store,
            whisper=whisper_processor,
            punctuation=punctuation_processor,
            diarization=diarization_processor,
        )

    async def start_transcription(
        self,
        task_id: str,
        audio_file_path: Path,
        language: Optional[str] = None,
        use_chunking: bool = False,
        use_punctuation: bool = True,
        punctuation_provider: str = "gemini",
        use_diarization: bool = False,
        max_speakers: Optional[int] = None,
        ui_language: Optional[str] = None,
    ) -> None:
        """啟動轉錄任務(非阻擋)。submit orchestrator.run 進 executor,立即返回。"""
        if max_speakers == 1:
            use_diarization = False
            print("ℹ️  [start_transcription] max_speakers=1，停用說話者辨識")

        audio_source = LocalFileSource(audio_file_path)
        try:
            self.executor.submit(
                self.orchestrator.run,
                task_id, audio_source, language, use_chunking, use_punctuation,
                punctuation_provider, use_diarization, max_speakers, ui_language,
            )
            print(f"✅ [start_transcription] 任務 {task_id} 已提交線程池")
        except Exception as e:
            print(f"❌ [start_transcription] 提交任務到線程池失敗：{e}")
            import traceback
            traceback.print_exc()
