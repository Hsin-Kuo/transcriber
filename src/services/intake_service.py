"""TranscriptionIntakeService — 「從音檔到 Task dispatch」的完整 workflow。

封裝：音檔驗證 → 配額預留 → tag 自動建立 → task 寫入 DB → dispatch。
失敗時自動回滾（release reservation + 清 temp dir）。

Router 的殘留責任：解析 upload → 組裝 file_path → 呼叫 intake() → 回傳 HTTP response。
"""

import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

from ..database.repositories.reservation_repo import ReservationRepository
from ..database.repositories.task_repo import TaskRepository
from ..database.repositories.user_repo import UserRepository
from ..models.intake import IntakeConfig, IntakeResult
from ..models.worker_job import TranscriptionJob
from ..services.audio_service import AudioService
from ..services.tag_service import TagService
from ..services.task_dispatch import get_task_dispatch
from ..utils.logger import get_logger
from ..utils.storage_service import is_aws
from ..utils.time_utils import get_utc_timestamp

log = get_logger(__name__)


class TranscriptionIntakeService:
    """一次呼叫完成：驗證 → 配額預留 → tag 建立 → task 寫入 → dispatch。"""

    def __init__(
        self,
        *,
        task_repo: TaskRepository,
        user_repo: UserRepository,
        reservation_repo: ReservationRepository,
        tag_service: TagService,
        diarization_available: bool = False,
    ):
        self.task_repo = task_repo
        self.user_repo = user_repo
        self.reservation_repo = reservation_repo
        self.tag_service = tag_service
        self._diarization_available = diarization_available

    def set_diarization_available(self, available: bool) -> None:
        self._diarization_available = available

    async def intake(
        self,
        *,
        user_id: str,
        user_email: str,
        file_path: Path,
        filename: str,
        config: IntakeConfig,
        temp_dir: Path,
    ) -> IntakeResult:
        """執行完整 intake workflow。

        Args:
            user_id: 使用者 ID
            user_email: 使用者 email
            file_path: 已組裝好的音檔路徑
            filename: 原始檔名（顯示用）
            config: 轉錄配置
            temp_dir: 此任務的暫存目錄（失敗時由本方法清理）

        Returns:
            IntakeResult 含 task_id 和 dispatch 狀態

        Raises:
            HTTPException: 驗證失敗、配額不足、dispatch 失敗等
        """
        task_id = str(uuid.uuid4())
        reservation_made = False

        try:
            # 1. 音檔資訊
            audio_service = AudioService()
            try:
                audio_duration_ms = audio_service.get_audio_duration(file_path)
                audio_duration_seconds = audio_duration_ms / 1000.0
                audio_size_mb = round(file_path.stat().st_size / 1024 / 1024, 2)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"無法讀取音檔資訊：{str(e)}",
                )

            # 2. 取得用戶資料（含 quota tier）
            full_user = await self.user_repo.get_by_id(user_id)
            if not full_user:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="無法獲取用戶資訊",
                )

            # 3. 配額預留
            await self.reservation_repo.reserve_transcription(
                user_id=user_id,
                task_id=task_id,
                duration_minutes=audio_duration_seconds / 60,
            )
            reservation_made = True

            # 4. Diarization 可用性檢查（僅 local 模式）
            if config.diarize and not is_aws() and not self._diarization_available:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Speaker diarization 功能未啟用。請設定 HF_TOKEN 環境變數並重啟服務。",
                )

            # 5. Tag 自動建立
            if config.tags:
                await self._auto_create_tags(user_id, config.tags)

            # 6. 建立 task 記錄
            user_tier = full_user.get("quota", {}).get("tier", "free")
            current_time = get_utc_timestamp()

            task_data = {
                "_id": task_id,
                "task_id": task_id,
                "task_type": config.task_type,
                "user": {
                    "user_id": user_id,
                    "user_email": user_email,
                    "tier": user_tier,
                },
                "file": {
                    "filename": filename,
                    "size_mb": audio_size_mb,
                },
                "config": {
                    "punct_provider": config.punct_provider,
                    "chunk_audio": config.chunk_audio,
                    "chunk_minutes": config.chunk_minutes,
                    "diarize": config.diarize,
                    "max_speakers": config.max_speakers,
                    "language": config.language,
                    "ui_language": config.ui_language,
                },
                "status": "pending",
                "stats": {
                    "audio_duration_seconds": audio_duration_seconds,
                },
                "tags": config.tags,
                "keep_audio": False,
                "speaker_names": {},
                "subtitle_settings": {
                    "density_threshold": 3.0,
                },
                "timestamps": {
                    "created_at": current_time,
                    "updated_at": current_time,
                },
            }
            if config.custom_name:
                task_data["custom_name"] = config.custom_name
            if config.batch_id:
                task_data["batch_id"] = config.batch_id

            await self.task_repo.create(task_data)

            # 7. Dispatch
            dispatch_result = await get_task_dispatch().submit(
                job=TranscriptionJob(
                    task_id=task_id,
                    language=None if config.language == "auto" else config.language,
                    use_chunking=config.chunk_audio,
                    use_punctuation=config.punct_provider != "none",
                    punctuation_provider=config.punct_provider,
                    use_diarization=config.diarize,
                    max_speakers=config.max_speakers,
                    ui_language=config.ui_language,
                    handoff_ext=file_path.suffix.lstrip(".").lower(),
                ),
                audio_local_path=file_path,
                temp_dir=temp_dir,
                user_tier=user_tier,
            )

            log.info("task.created", task_id=task_id, status=dispatch_result.status)

            return IntakeResult(
                task_id=task_id,
                status=dispatch_result.status,
                queue_position=dispatch_result.queue_position or 0,
                filename=filename,
                size_mb=audio_size_mb,
            )

        except HTTPException:
            await self._rollback(temp_dir, task_id if reservation_made else None)
            raise
        except Exception as e:
            await self._rollback(temp_dir, task_id if reservation_made else None)
            log.error("intake.failed", task_id=task_id, error=str(e), exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"建立轉錄任務失敗：{str(e)}",
            )

    async def _rollback(self, temp_dir: Path, task_id_for_release: Optional[str]) -> None:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        if task_id_for_release:
            try:
                await self.reservation_repo.release_by_task_id(task_id_for_release)
            except Exception as e:
                log.warning("intake.reservation.release_failed", task_id=task_id_for_release, error=str(e))

    async def _auto_create_tags(self, user_id: str, tags: list) -> None:
        try:
            existing_tags = await self.tag_service.get_all_tags(user_id)
            existing_names = {t["name"] for t in existing_tags}
            for tag_name in tags:
                if tag_name and tag_name not in existing_names:
                    try:
                        await self.tag_service.create_tag(user_id=user_id, name=tag_name)
                    except (ValueError, Exception):
                        pass
        except Exception as e:
            log.warning("tag.auto_create.failed", error=str(e))
