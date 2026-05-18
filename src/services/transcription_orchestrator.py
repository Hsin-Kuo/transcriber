"""TranscriptionOrchestrator — 單次 transcription run 的 Phase 機器 + 取消 + 終態協調。

對應 CONTEXT.md「TranscriptionOrchestrator」與「TranscriptionCancelled」。

職責邊界（B 範圍）：
- 持有 processors（whisper / punctuation / diarization）與 progress_store
- 跑 PREPARATION → TRANSCRIPTION → PUNCTUATION 三 phase
- 取消檢查：DB poll → raise TranscriptionCancelled
- 終態寫入：成功 _mark_completed（含 quota consume + audit）、失敗 _mark_failed
- 臨時檔清理（_cleanup_temp_files）

不在範圍：
- 音檔 I/O（_convert_audio_to_mp3 / _save_audio_file_sync）—— 留在 Service，注入 callback
- DB transcription 寫入（_save_transcription_results）—— 留在 Service，注入 callback
- 任務啟動進 executor —— Service.start_transcription 負責
"""
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.database.sync_client import get_sync_db
from src.utils.text_utils import align_segments_to_punctuated_text, convert_segments_punctuation
from src.utils.time_utils import get_utc_timestamp

from .progress_store import Phase, ProgressStore
from .task_service import TaskService
from .utils.diarization_processor import DiarizationProcessor
from .utils.punctuation_processor import PunctuationProcessor
from .utils.whisper_processor import WhisperProcessor


class TranscriptionCancelled(Exception):
    """使用者透過 cancel endpoint 將 Task status 設為 canceling/cancelled 時拋出。

    Orchestrator.run() 的 top-level except 統一處理 cleanup；status 已被
    cancel endpoint 設過，**不要**再被 _mark_failed 覆蓋。
    """


def _resolve_punct_language(
    language: Optional[str], detected_language: Optional[str], ui_language: Optional[str]
) -> str:
    """決定標點處理用的語言代碼。

    優先順序：
    1. 使用者明確指定繁/簡體 → 直接用
    2. Whisper 偵測到 zh（包含自動偵測）→ 依 UI 語言決定繁/簡，其他 UI 語言預設繁體
    3. 其他語言 → 用偵測到的語言或指定語言
    """
    if language in ("zh-TW", "zh-CN"):
        return language
    if detected_language == "zh":
        return "zh-CN" if ui_language == "zh-CN" else "zh-TW"
    return detected_language or language or "zh"


class TranscriptionOrchestrator:
    """單次 run 的 Phase 機器。Service.start_transcription 用 executor submit run()。"""

    def __init__(
        self,
        *,
        whisper: WhisperProcessor,
        punctuation: PunctuationProcessor,
        diarization: Optional[DiarizationProcessor],
        progress_store: ProgressStore,
        task_service: TaskService,
        # 留在 Service 的 callbacks（避免循環依賴）
        convert_audio_to_mp3: Callable[[Path], Path],
        save_audio_file_sync: Callable[[str, Path, list], None],
        save_transcription_results: Callable[[str, str, list], None],
    ):
        self.whisper = whisper
        self.punctuation = punctuation
        self.diarization = diarization
        self.progress_store = progress_store
        self.task_service = task_service
        self._convert_audio_to_mp3 = convert_audio_to_mp3
        self._save_audio_file_sync = save_audio_file_sync
        self._save_transcription_results = save_transcription_results

    # ── public：主流程 ─────────────────────────────

    def run(
        self,
        task_id: str,
        audio_file_path: Path,
        language: Optional[str],
        use_chunking: bool,
        use_punctuation: bool,
        punctuation_provider: str,
        use_diarization: bool,
        max_speakers: Optional[int],
        ui_language: Optional[str] = None,
    ) -> None:
        """執行整個 run（sync）。三條 exit 路徑都統一 cleanup。"""
        print(f"🎬 [Orchestrator] 開始處理任務 {task_id}")
        print(f"🔧 [Orchestrator] 音檔路徑: {audio_file_path}")
        print(f"🔧 [Orchestrator] 音檔是否存在: {audio_file_path.exists()}")

        mp3_path: Optional[Path] = None
        try:
            # ── PREPARATION ─────────────────────────
            mp3_path = self._run_preparation_phase(task_id, audio_file_path)
            self.check_cancelled(task_id)

            # ── TRANSCRIPTION (+ optional parallel diarization) ──
            full_text, segments, detected_language = self._run_transcription_phase(
                task_id, mp3_path, language, use_chunking, use_diarization, max_speakers
            )
            self.check_cancelled(task_id)

            # ── 繁簡清洗 + PUNCTUATION ────────────────
            final_text, segments, punct_model, punct_tokens = self._run_punctuation_phase(
                task_id,
                full_text,
                segments,
                language,
                detected_language,
                ui_language,
                use_punctuation,
                punctuation_provider,
            )
            self.check_cancelled(task_id)

            # ── 成功收尾 ─────────────────────────────
            converted_segments = convert_segments_punctuation(segments)
            self._save_transcription_results(task_id, final_text, converted_segments)
            self._mark_completed(
                task_id, detected_language or language, final_text, punct_model, punct_tokens
            )
            self._cleanup_temp_files(task_id, mp3_path, save_audio=True)
            self.task_service.cleanup_task_memory(task_id)
            print(f"🧹 已清理任務 {task_id} 的記憶體狀態", flush=True)
            print(f"✅ 任務 {task_id} 完成！")

        except TranscriptionCancelled:
            print(f"🛑 [Orchestrator] 任務 {task_id} 已取消，中止處理")
            self._cleanup_temp_files(task_id, mp3_path, save_audio=False)
            self.task_service.cleanup_task_memory(task_id)
            # status 已被 cancel endpoint 設了，不覆蓋

        except Exception as e:
            print(f"❌ 轉錄失敗：{e}")
            self._mark_failed(task_id, str(e))
            self._cleanup_temp_files(task_id, mp3_path, save_audio=False)
            self.task_service.cleanup_task_memory(task_id)
            print(f"🧹 已清理任務 {task_id} 的記憶體狀態", flush=True)

    # ── public：Phase 機器（測試 surface）─────────────

    def enter_phase(self, task_id: str, phase: Phase, message: str) -> None:
        """Phase 開始：set 0%。"""
        self.report_progress(task_id, phase, 0.0, message=message)

    def report_progress(
        self,
        task_id: str,
        phase: Phase,
        phase_progress: float,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """更新 phase 內部進度 0.0~1.0。"""
        print(
            f"📡 [SSE] {phase.value}@{phase_progress:.0%}: {message}", flush=True
        )
        self.progress_store.set_phase(
            task_id, phase, phase_progress, message=message, details=details
        )

    def complete_phase(
        self, task_id: str, phase: Phase, message: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Phase 收尾：set 1.0。"""
        self.report_progress(task_id, phase, 1.0, message=message, details=details)

    def check_cancelled(self, task_id: str) -> None:
        """若 Task 已被 cancel endpoint 設成 cancelled，raise TranscriptionCancelled。"""
        if self.task_service.is_cancelled(task_id):
            raise TranscriptionCancelled(f"task {task_id} cancelled by user")

    # ── private：phase 實作 ───────────────────────────

    def _run_preparation_phase(self, task_id: str, audio_file_path: Path) -> Path:
        """PREPARATION：音訊轉 MP3。"""
        print("🔄 [Orchestrator] 開始轉換音檔為 MP3 格式")
        self.report_progress(
            task_id,
            Phase.PREPARATION,
            0.3,
            message="正在轉換音檔格式...",
            details={"audio_converted": False},
        )
        mp3_path = self._convert_audio_to_mp3(audio_file_path)
        print(f"✅ [Orchestrator] 音檔轉換完成: {mp3_path}")
        self.report_progress(
            task_id,
            Phase.PREPARATION,
            0.8,
            message="音檔轉換完成",
            details={"audio_converted": True},
        )
        return mp3_path

    def _run_transcription_phase(
        self,
        task_id: str,
        mp3_path: Path,
        language: Optional[str],
        use_chunking: bool,
        use_diarization: bool,
        max_speakers: Optional[int],
    ) -> Tuple[str, list, Optional[str]]:
        """TRANSCRIPTION：Whisper（+ 可選並行 diarization）+ 合併。

        Returns:
            (full_text, segments, detected_language)
        """
        print("🎤 [Orchestrator] 開始並行處理：轉錄 + 說話者辨識")

        full_text: Optional[str] = None
        segments: Optional[list] = None
        detected_language: Optional[str] = None
        diarization_segments: Optional[list] = None

        if use_diarization and self.diarization:
            self.report_progress(
                task_id,
                Phase.TRANSCRIPTION,
                0.0,
                message="正在並行執行轉錄和說話者辨識...",
                details={"diarization_started": True},
            )

            with ThreadPoolExecutor(max_workers=2) as parallel_executor:
                transcription_future = parallel_executor.submit(
                    self._run_transcription, task_id, mp3_path, language, use_chunking
                )
                diarization_future = parallel_executor.submit(
                    self._run_diarization, task_id, mp3_path, max_speakers
                )

                try:
                    for _future in as_completed([transcription_future, diarization_future]):
                        if _future == transcription_future:
                            full_text, segments, detected_language = _future.result()
                            if full_text is not None:
                                print(f"✅ [並行] Whisper 轉錄完成 (文字長度: {len(full_text)})")
                            else:
                                print("⚠️ [並行] Whisper 轉錄返回空結果")
                        elif _future == diarization_future:
                            diarization_segments = _future.result()
                            if diarization_segments:
                                num_speakers = len(set(s["speaker"] for s in diarization_segments))
                                print(f"✅ [並行] 說話者辨識完成，識別到 {num_speakers} 位說話者")
                            else:
                                print("⚠️ [並行] 說話者辨識失敗或無結果")
                except Exception as e:
                    print(f"❌ [並行] 並行執行出錯：{e}")
                    import traceback
                    traceback.print_exc()

            # 合併
            if diarization_segments and segments:
                task = get_sync_db().tasks.find_one({"_id": task_id})
                task_type = task.get("task_type", "paragraph") if task else "paragraph"
                num_speakers = len(set(s["speaker"] for s in diarization_segments))

                if task_type == "subtitle":
                    print("🎬 [字幕模式] 將說話者資訊整合到 segments...")
                    segments = self.whisper._merge_speaker_to_segments(segments, diarization_segments)
                    print(f"✅ [字幕模式] 已將 {num_speakers} 位說話者資訊加入 segments")
                else:
                    print("📝 [段落模式] 合併轉錄和說話者辨識到文字...")
                    merged_text = self.whisper._merge_transcription_with_diarization(
                        segments, diarization_segments
                    )
                    print(f"✅ [段落模式] 已合併 {num_speakers} 位說話者到文字")
                    full_text = merged_text

                self.complete_phase(
                    task_id,
                    Phase.TRANSCRIPTION,
                    "語者辨識完成",
                    details={"diarization_completed": True, "num_speakers": num_speakers},
                )
            else:
                print(
                    f"⚠️ [合併] 無法合併：diarization_segments={diarization_segments is not None}, segments={segments is not None}"
                )
                self.complete_phase(
                    task_id,
                    Phase.TRANSCRIPTION,
                    "語者辨識失敗，使用原始文字",
                    details={"diarization_failed": True},
                )
        else:
            # 純 Whisper（無 diarization）
            print(f"🎤 [Orchestrator] 開始 Whisper 轉錄 (chunking={use_chunking})")
            full_text, segments, detected_language = self._run_transcription(
                task_id, mp3_path, language, use_chunking
            )

        # full_text 為 None 的兩種來源
        if full_text is None:
            # Whisper 在 chunk callback 內被 cancel_check 中斷會回 None
            self.check_cancelled(task_id)  # 若已取消會 raise
            raise ValueError("轉錄結果為空")

        print(f"✅ [Orchestrator] 轉錄完成 (文字長度: {len(full_text)}, 語言: {detected_language})")
        return full_text, segments, detected_language

    def _run_punctuation_phase(
        self,
        task_id: str,
        full_text: str,
        segments: list,
        language: Optional[str],
        detected_language: Optional[str],
        ui_language: Optional[str],
        use_punctuation: bool,
        punctuation_provider: str,
    ) -> Tuple[str, list, Optional[str], Optional[Dict[str, int]]]:
        """繁簡清洗（zh） + PUNCTUATION（可選 + fallback）。

        Returns:
            (final_text, segments, punctuation_model, punctuation_token_usage)
        """
        # 1. 繁簡清洗（標點前先統一字型）
        punct_language = _resolve_punct_language(language, detected_language, ui_language)
        if punct_language in ("zh-TW", "zh-CN"):
            from .utils.whisper_processor import _convert_chinese_script
            full_text = _convert_chinese_script(full_text, punct_language)
            segments = [
                {**seg, "text": _convert_chinese_script(seg["text"], punct_language)}
                for seg in segments
            ]

        # 2. 標點處理（可選 + 失敗 fallback）
        punctuation_model: Optional[str] = None
        punctuation_token_usage: Optional[Dict[str, int]] = None
        if not use_punctuation:
            return full_text, segments, None, None

        self.report_progress(
            task_id,
            Phase.PUNCTUATION,
            0.0,
            message="正在添加標點符號...",
            details={"punctuation_started": True},
        )
        try:
            punctuated_text, punctuation_model, punctuation_token_usage = self.punctuation.process(
                full_text,
                provider=punctuation_provider,
                language=punct_language,
                progress_callback=lambda idx, total: self._update_punctuation_progress(
                    task_id, idx, total
                ),
            )
            self.complete_phase(
                task_id,
                Phase.PUNCTUATION,
                "標點處理完成",
                details={
                    "punctuation_completed": True,
                    "punctuation_model": punctuation_model,
                },
            )
            aligned_segments = align_segments_to_punctuated_text(segments, punctuated_text)
            if aligned_segments is not segments:
                print(f"✅ [Orchestrator] segments 已同步標點（{len(aligned_segments)} 個）")
            else:
                print("⚠️ [Orchestrator] segments 對齊失敗，保留原始文字")
            return punctuated_text, aligned_segments, punctuation_model, punctuation_token_usage
        except Exception as punct_error:
            print(f"⚠️ [Orchestrator] 標點處理失敗：{punct_error}")
            print("   將使用原始轉錄文字（無標點）繼續完成任務")
            self.complete_phase(
                task_id,
                Phase.PUNCTUATION,
                f"標點處理失敗（{str(punct_error)[:100]}），使用原始文字",
                details={
                    "punctuation_failed": True,
                    "punctuation_error": str(punct_error)[:200],
                },
            )
            return full_text, segments, None, None

    # ── private：processor 包裝（保留進度 callback）──

    def _run_transcription(
        self, task_id: str, mp3_path: Path, language: Optional[str], use_chunking: bool
    ) -> tuple:
        """執行 Whisper 轉錄。Returns (full_text, segments, detected_language)。"""
        if use_chunking:
            self.report_progress(
                task_id,
                Phase.TRANSCRIPTION,
                0.0,
                message="正在並行分段轉錄音檔（多進程）...",
            )
            full_text, segments, detected_language = self.whisper.transcribe_in_chunks_parallel(
                mp3_path,
                language=language,
                max_workers=3,
                progress_callback=lambda completed, total, processing=0: self._update_chunk_progress(
                    task_id, completed, total, processing
                ),
                cancel_check=lambda: self.task_service.is_cancelled(task_id),
            )
        else:
            self.report_progress(
                task_id,
                Phase.TRANSCRIPTION,
                0.0,
                message="正在轉錄音檔...",
            )
            full_text, segments, detected_language = self.whisper.transcribe(
                mp3_path, language=language
            )
        return full_text, segments, detected_language

    def _run_diarization(
        self, task_id: str, mp3_path: Path, max_speakers: Optional[int]
    ) -> Optional[list]:
        """執行說話者辨識。進度由 _run_transcription_phase 在合併段落後統一更新。"""
        try:
            print("🔊 [並行] 開始說話者辨識")
            print(f"🔊 [並行] max_speakers 參數: {max_speakers}")
            return self.diarization.perform_diarization(mp3_path, max_speakers=max_speakers)
        except Exception as diarize_error:
            print(f"⚠️ [並行] 說話者辨識失敗：{diarize_error}")
            return None

    # ── private：phase 內子進度 ───────────────────────

    def _update_chunk_progress(
        self,
        task_id: str,
        completed_chunks: int,
        total_chunks: int,
        processing_chunks: int = 0,
    ) -> None:
        """更新分段轉錄進度（屬於 TRANSCRIPTION phase 內部）"""
        denom = max(1, total_chunks)
        phase_progress = (completed_chunks + 0.5 * processing_chunks) / denom
        phase_progress = min(0.99, phase_progress)  # 留 0.01 給合併/收尾
        self.report_progress(
            task_id,
            Phase.TRANSCRIPTION,
            phase_progress,
            message=f"並行轉錄中（已完成 {completed_chunks}/{total_chunks} 段）...",
            details={
                "total_chunks": total_chunks,
                "completed_chunks": completed_chunks,
                "processing_chunks": processing_chunks,
            },
        )

    def _update_punctuation_progress(self, task_id: str, chunk_idx: int, total_chunks: int) -> None:
        """更新標點處理進度（屬於 PUNCTUATION phase 內部）"""
        denom = max(1, total_chunks)
        phase_progress = min(0.99, chunk_idx / denom)
        self.report_progress(
            task_id,
            Phase.PUNCTUATION,
            phase_progress,
            message=f"正在添加標點（第 {chunk_idx}/{total_chunks} 段）...",
            details={
                "punctuation_current_chunk": chunk_idx,
                "punctuation_total_chunks": total_chunks,
            },
        )

    # ── private：終態 + cleanup ──────────────────────

    def _mark_completed(
        self,
        task_id: str,
        language: Optional[str],
        transcription_text: str = "",
        punctuation_model: Optional[str] = None,
        punctuation_token_usage: Optional[Dict[str, int]] = None,
    ) -> None:
        """標記任務完成 + quota consume + audit log。"""
        from src.services.utils.async_utils import run_async_in_thread

        text_length = len(transcription_text)
        word_count = len(transcription_text.split())

        update_data = {
            "status": "completed",
            "result.text_length": text_length,
            "result.word_count": word_count,
            "config.language": language,
            "timestamps.completed_at": get_utc_timestamp(),
            "progress": "轉錄完成",
        }
        if punctuation_model:
            update_data["models.punctuation"] = punctuation_model
        if punctuation_token_usage:
            update_data["stats.token_usage"] = {
                "total": punctuation_token_usage.get("total", 0),
                "prompt": punctuation_token_usage.get("prompt", 0),
                "completion": punctuation_token_usage.get("completion", 0),
                "model": punctuation_model or "unknown",
            }
            print(f"📊 保存 Token 使用量: {punctuation_token_usage}")

        self._update_task_sync(task_id, update_data)
        print(f"📊 字數統計：{text_length} 字元，{word_count} 詞")

        try:
            task = self._get_task_sync(task_id)
            if not task:
                return

            user_id = (
                task["user"].get("user_id")
                if isinstance(task.get("user"), dict)
                else task.get("user_id")
            )

            # Quota consume（兩步式：刪預扣 → pipeline 扣款；論證見 reservation_repo.py）
            if user_id:
                audio_duration_seconds = task.get("stats", {}).get("audio_duration_seconds", 0)
                if audio_duration_seconds > 0:
                    from bson import ObjectId
                    from src.auth.quota import build_transcription_consumption_pipeline
                    from src.database.repositories.reservation_repo import consume_reservation_sync

                    db = get_sync_db()
                    duration_minutes = audio_duration_seconds / 60

                    try:
                        reservation = consume_reservation_sync(db, task_id)
                    except Exception as e:
                        print(
                            f"⚠️ 刪除預扣失敗（沒影響資料，會留下殘留預扣）：task={task_id} err={e}"
                        )
                        reservation = None

                    if reservation is None:
                        print(
                            f"ℹ️  任務 {task_id} 無預扣記錄，跳過配額扣除（可能是舊任務或重複完成通知）"
                        )
                    else:
                        try:
                            pipeline = build_transcription_consumption_pipeline(
                                duration_minutes=duration_minutes,
                                now_ts=get_utc_timestamp(),
                            )
                            db.users.update_one({"_id": ObjectId(user_id)}, pipeline)
                            print(
                                f"✅ 已扣除配額：用戶 {user_id}，時長 {audio_duration_seconds:.2f} 秒（pipeline 自動分流 plan/extra）"
                            )
                        except Exception as e:
                            # ⚠️ QUOTA_LEAK：監控訊號（grep [QUOTA_LEAK]）
                            print(
                                f"⚠️ [QUOTA_LEAK] 扣款失敗（漏算一次）："
                                f"user_id={user_id} task_id={task_id} "
                                f"duration_minutes={duration_minutes:.2f} "
                                f"reservation_minutes={reservation.get('duration_minutes')} "
                                f"err={e}"
                            )

                # Audit log（失敗不影響主流程）
                try:
                    from src.utils.audit_logger import get_audit_logger
                    audit_logger = get_audit_logger()

                    original_filename = (
                        task.get("original_filename")
                        or task.get("file", {}).get("original_filename", "未知")
                    )
                    audio_size = task.get("stats", {}).get("audio_size_bytes", 0)
                    processing_time = task.get("stats", {}).get("processing_time_seconds", 0)

                    run_async_in_thread(
                        audit_logger.log_background_task(
                            log_type="transcription",
                            action="completed",
                            user_id=user_id,
                            task_id=task_id,
                            status_code=200,
                            message=f"轉錄完成：{original_filename}",
                            request_body={
                                "language": language,
                                "audio_duration_seconds": audio_duration_seconds,
                                "audio_size_bytes": audio_size,
                                "processing_time_seconds": processing_time,
                                "quota_deducted_minutes": round(audio_duration_seconds / 60, 2),
                            },
                        )
                    )
                except Exception as log_error:
                    print(f"⚠️ 記錄 audit log 失敗：{log_error}")
        except Exception as e:
            print(f"⚠️ 處理任務完成後續作業失敗：{e}")

    def _mark_failed(self, task_id: str, error: str) -> None:
        """標記任務失敗 + 釋放預扣 + audit log。"""
        print(f"❌ [Orchestrator] 標記任務 {task_id} 為失敗狀態")
        print(f"   錯誤信息: {error}")

        success = self._update_task_sync(
            task_id,
            {"status": "failed", "error": error, "progress": f"轉錄失敗：{error}"},
        )
        if not success:
            print(f"❌ [CRITICAL] 無法將任務 {task_id} 標記為失敗！請檢查 MongoDB 連接")

        # 釋放預扣（idempotent）
        try:
            from src.database.repositories.reservation_repo import release_reservation_sync
            released = release_reservation_sync(get_sync_db(), task_id)
            if released:
                print(f"♻️  已釋放任務 {task_id} 的預扣配額")
        except Exception as release_error:
            print(f"⚠️ 釋放預扣失敗：{release_error}")

        try:
            task = self._get_task_sync(task_id)
            if not task:
                return

            user_id = (
                task["user"].get("user_id")
                if isinstance(task.get("user"), dict)
                else task.get("user_id")
            )
            if not user_id:
                return

            from src.services.utils.async_utils import run_async_in_thread
            from src.utils.audit_logger import get_audit_logger
            audit_logger = get_audit_logger()

            original_filename = (
                task.get("original_filename")
                or task.get("file", {}).get("original_filename", "未知")
            )
            task_status = task.get("status", "unknown")
            retry_count = task.get("retry_count", 0)

            run_async_in_thread(
                audit_logger.log_background_task(
                    log_type="transcription",
                    action="failed",
                    user_id=user_id,
                    task_id=task_id,
                    status_code=500,
                    message=f"轉錄失敗：{original_filename}",
                    request_body={
                        "error": error,
                        "error_type": type(error).__name__ if not isinstance(error, str) else "Error",
                        "task_status_before": task_status,
                        "retry_count": retry_count,
                        "original_filename": original_filename,
                    },
                )
            )
        except Exception as e:
            print(f"⚠️ 記錄 audit log 失敗：{e}")

    def _cleanup_temp_files(
        self, task_id: str, mp3_path: Optional[Path], save_audio: bool = True
    ) -> None:
        """清理臨時檔案。

        save_audio=True（成功）→ 移動音檔到永久位置 + 清 temp dir
        save_audio=False（取消/失敗）→ 只清 temp dir 與 MP3
        """
        # 失敗/取消時清掉中間 MP3
        if not save_audio and mp3_path and mp3_path.exists():
            try:
                mp3_path.unlink()
                print(f"🗑️ 已清理臨時 MP3 檔案：{mp3_path.name}")
            except Exception as e:
                print(f"⚠️ 清理 MP3 檔案失敗：{e}")

        temp_dir = self.task_service.get_temp_dir(task_id)
        if not (temp_dir and temp_dir.exists()):
            return

        print(f"📁 臨時目錄: {temp_dir}")
        audio_files = list(temp_dir.glob("input.*")) + list(temp_dir.glob("merged*.mp3"))
        print(f"🎵 找到的音檔: {[f.name for f in audio_files]}")

        if save_audio:
            task = self._get_task_sync(task_id)
            keep_audio = task.get("keep_audio", False) if task else False
            print(f"🔍 任務 {task_id} 的 keep_audio 設定: {keep_audio}")

            try:
                self._save_audio_file_sync(task_id, temp_dir, audio_files)
                shutil.rmtree(temp_dir)
                if keep_audio:
                    print("🗑️ 已清理臨時目錄，音檔已保存並標記為受保護")
                else:
                    print("🗑️ 已清理臨時目錄，音檔已保存（可被自動清理）")
            except Exception as e:
                print(f"⚠️ 保存音檔失敗：{e}")
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
        else:
            print("⚠️ 任務未成功完成，不保存音檔")
            try:
                shutil.rmtree(temp_dir)
                print("🗑️ 已清理臨時目錄和音檔（任務失敗/取消）")
            except Exception as e:
                print(f"⚠️ 清理臨時目錄失敗：{e}")

    # ── private：sync DB helpers（與 Service 共用 sync_client）──

    def _get_task_sync(self, task_id: str) -> Optional[dict]:
        try:
            return get_sync_db().tasks.find_one({"_id": task_id})
        except Exception as e:
            print(f"⚠️ 同步獲取任務失敗：{e}")
            return None

    def _update_task_sync(self, task_id: str, updates: dict) -> bool:
        try:
            updates["updated_at"] = get_utc_timestamp()
            result = get_sync_db().tasks.update_one({"_id": task_id}, {"$set": updates})
            print(f"✅ 同步更新任務 {task_id}，修改了 {result.modified_count} 條記錄")
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ [CRITICAL] 同步更新任務失敗：{e}")
            import traceback
            traceback.print_exc()
            return False
