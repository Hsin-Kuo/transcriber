"""TranscriptionOrchestrator — Web Server 與 Worker 共用的單次轉錄 run。

對應 CONTEXT.md「TranscriptionOrchestrator」「TranscriptionCancelled」。

職責:跑 PREPARATION → TRANSCRIPTION → PUNCTUATION 三 Phase、DB-poll 取消、
終態寫入(成功 _mark_completed / 失敗 _mark_failed)、run temp_dir 生命週期。

兩進程之間唯一的變化點(「音檔從哪來」)由注入的 AudioSource 抽掉。processor
與 db 也是注入——orchestrator 不知道自己跑在 server 還是 worker。
"""
import gc
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from structlog.contextvars import bind_contextvars, clear_contextvars

from src.services.progress_store import Phase
from src.utils.audio_converter import convert_to_mp3, convert_to_wav
from src.utils.config_loader import get_temp_dir
from src.utils.logger import get_logger
from src.utils.text_utils import (
    align_segments_to_punctuated_text,
    split_segments_at_sentence_punctuation,
    convert_segments_punctuation,
    strip_subtitle_punctuation,
)
from src.utils.storage.compact import save_audio
from src.utils.time_utils import get_utc_timestamp

log = get_logger(__name__)

_CANCEL_STATUSES = {"canceling", "cancelled"}


class TranscriptionCancelled(Exception):
    """使用者透過 cancel endpoint 把 Task status 設成 canceling/cancelled 時拋出。

    兩進程共用同一個 class。run() 的 top-level except 統一 cleanup;status 已被
    cancel endpoint 寫過,**不**再被 _mark_failed 覆蓋。
    """


def _resolve_punct_language(
    language: Optional[str], detected_language: Optional[str], ui_language: Optional[str]
) -> str:
    """決定標點處理用的語言代碼。

    1. 使用者明確指定繁/簡 → 直接用
    2. 台語（nan-TW）→ 模型輸出為繁體漢字,標點/繁簡處理沿用 zh-TW 鏈
    3. 偵測到 zh → 依 UI 語言決定繁/簡,其他預設繁體
    4. 其他語言 → 用偵測到的語言或指定語言
    """
    if language == "nan-TW":
        return "zh-TW"
    if language in ("zh-TW", "zh-CN"):
        return language
    if detected_language == "zh":
        return "zh-CN" if ui_language == "zh-CN" else "zh-TW"
    return detected_language or language or "zh"


class TranscriptionOrchestrator:
    """單次轉錄 run 的 Phase 機器。Web Server 與 Worker 共用。"""

    def __init__(self, *, db, progress_store, whisper, punctuation, diarization=None):
        self.db = db
        self.progress_store = progress_store
        self.whisper = whisper
        self.punctuation = punctuation
        self.diarization = diarization

    # ── public:主流程 ────────────────────────────────

    def run(
        self,
        task_id: str,
        audio_source,
        language: Optional[str],
        use_chunking: bool,
        use_punctuation: bool,
        punctuation_provider: str,
        use_diarization: bool,
        max_speakers: Optional[int],
        ui_language: Optional[str] = None,
    ) -> None:
        """執行整個 run(sync)。cleanup 由 finally 統一處理。"""
        # 綁定 task_id 到 log context:本 run 內所有 log 都帶 task_id。
        # local 模式 run() 在 executor thread 跑、不繼承 request contextvars,故在此自綁。
        bind_contextvars(task_id=task_id)
        log.info("transcription.run.started")
        temp_dir = get_temp_dir(prefix="run_")
        succeeded = False
        try:
            audio_path = audio_source.acquire(temp_dir)

            # ── PREPARATION ──────────────────────────
            mp3_path = self._run_preparation(task_id, audio_path)
            self.check_cancelled(task_id)

            # ── TRANSCRIPTION (+ 可選並行 diarization) ──
            full_text, segments, detected_language = self._run_transcription_phase(
                task_id, mp3_path, temp_dir, language, use_chunking,
                use_diarization, max_speakers,
            )
            self.check_cancelled(task_id)

            # ── 繁簡清洗 + PUNCTUATION ────────────────
            final_text, segments, punct_model, punct_tokens = self._run_punctuation_phase(
                task_id, full_text, segments, language, detected_language,
                ui_language, use_punctuation, punctuation_provider,
            )
            self.check_cancelled(task_id)

            # ── 成功收尾 ─────────────────────────────
            task = self._get_task(task_id)
            if task and task.get("task_type") == "subtitle":
                # 字幕任務一律去標點（含 Whisper 原生標點）；不可再做半形→全形轉換，
                # 否則會把保護的 3.14 / 1,000 / 12:30 變成 3。14 / 1，000 / 12：30
                final_text = strip_subtitle_punctuation(final_text)
                converted_segments = [
                    {**s, "text": strip_subtitle_punctuation(s.get("text", ""))}
                    for s in segments
                ]
            else:
                converted_segments = convert_segments_punctuation(segments)
            self._save_transcription_results(task_id, final_text, converted_segments)
            self._save_compact_audio(task_id, mp3_path)
            self._mark_completed(
                task_id, detected_language or language, final_text,
                punct_model, punct_tokens,
            )
            succeeded = True
            log.info("transcription.run.completed")

        except TranscriptionCancelled:
            log.info("transcription.run.cancelled")
            # status 已被 cancel endpoint 設,不覆蓋

        except Exception as e:
            log.error("transcription.run.failed", error=str(e), exc_info=True)
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("task_id", task_id)
                    sentry_sdk.capture_exception(e)
            except Exception:
                pass
            self._mark_failed(task_id, str(e))

        finally:
            try:
                audio_source.cleanup(succeeded)
            except Exception as e:
                log.warning("audio_source.cleanup_failed", error=str(e))
            self._cleanup_temp_dir(temp_dir)
            self.progress_store.clear(task_id)
            self._release_run_memory()
            clear_contextvars()

    def _release_run_memory(self) -> None:
        """每次 run 收尾時主動回收記憶體。

        模型是常駐單例(load 一次),這裡釋放的是「單次 run 累積」的暫態:
        whisper/ctranslate2 與 pyannote 留下的中間張量、segments 中間態等。
        常駐進程(local 模式 / GPU worker)若不主動回收,記憶體會隨運行時間單調成長。

        - gc.collect():強制回收 Python 層大物件(segments / full_text 等)。
        - torch.cuda.empty_cache():把 CUDA caching allocator 的空閒區塊還給 driver,
          避免長時間多任務後 VRAM 碎片化 OOM。CPU(int8)環境下 torch 不一定存在,
          故 import 失敗或無 GPU 時皆安全略過(no-op)。
        """
        try:
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
        except Exception as e:
            log.warning("transcription.run.release_memory_failed", error=str(e))

    # ── public:Phase 機器(測試 surface)───────────────

    def report_progress(
        self, task_id: str, phase: Phase, phase_progress: float,
        message: str = "", details: Optional[Dict[str, Any]] = None,
    ) -> None:
        log.debug(
            "progress.update", phase=phase.value, phase_progress=phase_progress, msg=message
        )
        self.progress_store.set_phase(
            task_id, phase, phase_progress, message=message, details=details
        )

    def complete_phase(
        self, task_id: str, phase: Phase, message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.report_progress(task_id, phase, 1.0, message=message, details=details)

    def check_cancelled(self, task_id: str) -> None:
        """DB-poll:Task status 已被 cancel endpoint 設成 canceling/cancelled 即 raise。"""
        doc = self.db.tasks.find_one({"_id": task_id}, {"status": 1})
        if doc and doc.get("status") in _CANCEL_STATUSES:
            raise TranscriptionCancelled(f"task {task_id} cancelled by user")

    # ── private:phase 實作 ───────────────────────────

    def _run_preparation(self, task_id: str, audio_path: Path) -> Path:
        """PREPARATION:音訊轉 Compact audio MP3。"""
        self.report_progress(
            task_id, Phase.PREPARATION, 0.3, message="正在轉換音檔格式...",
            details={"audio_converted": False},
        )
        mp3_path, _transcoded = convert_to_mp3(audio_path)
        self.report_progress(
            task_id, Phase.PREPARATION, 0.8, message="音檔轉換完成",
            details={"audio_converted": True},
        )
        return mp3_path

    def _run_transcription_phase(
        self, task_id: str, mp3_path: Path, temp_dir: Path, language: Optional[str],
        use_chunking: bool, use_diarization: bool, max_speakers: Optional[int],
    ) -> Tuple[str, list, Optional[str]]:
        """TRANSCRIPTION:Whisper(+ 可選並行 diarization)+ 合併。"""
        if use_diarization and self.diarization:
            self.report_progress(
                task_id, Phase.TRANSCRIPTION, 0.0,
                message="正在並行轉錄與說話者辨識...",
                details={"diarization_started": True},
            )
            # 裁決:diarization 餵 WAV(不是 MP3)
            wav_path = convert_to_wav(mp3_path, temp_dir / f"{task_id}.wav")

            with ThreadPoolExecutor(max_workers=2) as ex:
                t_future = ex.submit(
                    self._run_transcription, task_id, mp3_path, language, use_chunking
                )
                d_future = ex.submit(self._run_diarization, wav_path, max_speakers)
                for _ in as_completed([t_future, d_future]):
                    pass

            # 轉錄失敗 → 整個任務失敗(無可用結果);此處讓例外傳播
            full_text, segments, detected_language = t_future.result()
            # diarization 失敗 → 降級為純轉錄
            try:
                diar_segments = d_future.result()
            except Exception as e:
                log.warning("diarization.failed_degraded", error=str(e))
                diar_segments = None

            if diar_segments and segments:
                task = self._get_task(task_id)
                task_type = task.get("task_type", "paragraph") if task else "paragraph"
                num_speakers = len(set(s["speaker"] for s in diar_segments))
                if task_type == "subtitle":
                    segments = self.whisper._merge_speaker_to_segments(
                        segments, diar_segments
                    )
                else:
                    full_text = self.whisper._merge_transcription_with_diarization(
                        segments, diar_segments
                    )
                self._update_task(task_id, {"stats.diarization.num_speakers": num_speakers})
                self.complete_phase(
                    task_id, Phase.TRANSCRIPTION, "語者辨識完成",
                    details={"diarization_completed": True, "num_speakers": num_speakers},
                )
            else:
                self.complete_phase(
                    task_id, Phase.TRANSCRIPTION, "語者辨識失敗,使用純轉錄結果",
                    details={"diarization_failed": True},
                )
        else:
            full_text, segments, detected_language = self._run_transcription(
                task_id, mp3_path, language, use_chunking
            )

        if full_text is None:
            self.check_cancelled(task_id)  # 取消造成的 None 會在這裡 raise
            raise ValueError("轉錄結果為空")
        # words 只供 transcription phase 內部 word 級語者對齊使用，單點剝除、絕不外流
        # （覆蓋無 diar / diar 失敗降級 / 段落模式 / 字幕模式四條路；字幕模式核心已剝，此處 no-op）
        segments = [{k: v for k, v in s.items() if k != "words"} for s in segments]
        return full_text, segments, detected_language

    def _run_transcription(
        self, task_id: str, mp3_path: Path, language: Optional[str], use_chunking: bool
    ) -> tuple:
        """Whisper 轉錄。單一進度 callback 同時回報進度與檢查取消。"""
        self.report_progress(
            task_id, Phase.TRANSCRIPTION, 0.0, message="正在轉錄音檔..."
        )

        def _on_progress(elapsed_s, total_s):
            self.check_cancelled(task_id)
            if total_s and total_s > 0:
                pp = min(0.99, elapsed_s / total_s)
                self.report_progress(
                    task_id, Phase.TRANSCRIPTION, pp,
                    message=f"轉錄中（{int(elapsed_s)}s / {int(total_s)}s）...",
                )

        if use_chunking:
            return self.whisper.transcribe_in_chunks(
                mp3_path, language=language, progress_callback=_on_progress
            )
        return self.whisper.transcribe(
            mp3_path, language=language, progress_callback=_on_progress
        )

    def _run_diarization(self, wav_path: Path, max_speakers: Optional[int]):
        """說話者辨識。失敗讓例外傳播,由 caller 降級。"""
        return self.diarization.perform_diarization(wav_path, max_speakers=max_speakers)

    def _run_punctuation_phase(
        self, task_id: str, full_text: str, segments: list, language: Optional[str],
        detected_language: Optional[str], ui_language: Optional[str],
        use_punctuation: bool, punctuation_provider: str,
    ) -> Tuple[str, list, Optional[str], Optional[Dict[str, int]]]:
        """繁簡清洗(zh)+ PUNCTUATION(可選 + 失敗 fallback)。"""
        punct_language = _resolve_punct_language(language, detected_language, ui_language)
        if punct_language in ("zh-TW", "zh-CN"):
            from src.services.utils.whisper_processor import _convert_chinese_script
            full_text = _convert_chinese_script(full_text, punct_language)
            segments = [
                {**seg, "text": _convert_chinese_script(seg["text"], punct_language)}
                for seg in segments
            ]

        if not use_punctuation:
            return full_text, segments, None, None

        self.report_progress(
            task_id, Phase.PUNCTUATION, 0.0, message="正在添加標點符號...",
            details={"punctuation_started": True},
        )
        try:
            punctuated_text, punct_model, punct_tokens = self.punctuation.process(
                full_text,
                provider=punctuation_provider,
                language=punct_language,
                progress_callback=lambda idx, total: self._update_punctuation_progress(
                    task_id, idx, total
                ),
            )
            self.complete_phase(
                task_id, Phase.PUNCTUATION, "標點處理完成",
                details={"punctuation_completed": True, "punctuation_model": punct_model},
            )
            aligned = align_segments_to_punctuated_text(segments, punctuated_text)
            # 依 Gemini 加的句末標點把段切成句子級（中文唯一的句子邊界來源）
            aligned = split_segments_at_sentence_punctuation(aligned)
            return punctuated_text, aligned, punct_model, punct_tokens
        except TranscriptionCancelled:
            # 取消不是「標點失敗」——不可被 fallback 吞掉,往上拋給 run() 收
            raise
        except Exception as e:
            log.warning("punctuation.failed_fallback", error=str(e))
            self.complete_phase(
                task_id, Phase.PUNCTUATION,
                f"標點處理失敗（{str(e)[:100]}）,使用原始文字",
                details={"punctuation_failed": True, "punctuation_error": str(e)[:200]},
            )
            return full_text, segments, None, None

    def _update_punctuation_progress(self, task_id: str, idx: int, total: int) -> None:
        self.check_cancelled(task_id)  # PUNCTUATION 階段也要能即時取消
        denom = max(1, total)
        pp = min(0.99, idx / denom)
        self.report_progress(
            task_id, Phase.PUNCTUATION, pp,
            message=f"正在添加標點（第 {idx}/{total} 段）...",
            details={"punctuation_current_chunk": idx, "punctuation_total_chunks": total},
        )

    # ── private:結果與終態 ───────────────────────────

    def _save_transcription_results(
        self, task_id: str, text: str, segments: list
    ) -> None:
        """轉錄文字與 segments 寫入 MongoDB。"""
        now = get_utc_timestamp()
        self.db.transcriptions.replace_one(
            {"_id": task_id},
            {"_id": task_id, "content": text, "text_length": len(text),
             "created_at": now, "updated_at": now},
            upsert=True,
        )
        if segments:
            self.db.segments.replace_one(
                {"_id": task_id},
                {"_id": task_id, "segments": segments, "segment_count": len(segments),
                 "created_at": now, "updated_at": now},
                upsert=True,
            )

    def _save_compact_audio(self, task_id: str, mp3_path: Path) -> None:
        """Compact audio 落地永久區,寫 result.audio_file / audio_filename。"""
        task = self._get_task(task_id)
        user = task.get("user") if task else None
        tier = user.get("tier", "free") if isinstance(user, dict) else "free"
        stored = save_audio(task_id, mp3_path, tier=tier)
        original = (task.get("file") or {}).get("filename") if task else None
        audio_filename = f"{Path(original).stem}.mp3" if original else f"{task_id}.mp3"
        self._update_task(task_id, {
            "result.audio_file": stored,
            "result.audio_filename": audio_filename,
        })

    def _mark_completed(
        self, task_id: str, language: Optional[str], transcription_text: str,
        punctuation_model: Optional[str], punctuation_token_usage: Optional[Dict[str, int]],
    ) -> None:
        """標記完成 + quota consume。完成時順帶 unset 殘留 error。"""
        text_length = len(transcription_text)
        update_data = {
            "status": "completed",
            "result.text_length": text_length,
            "result.word_count": len(transcription_text.split()),
            "config.language": language,
            "timestamps.completed_at": get_utc_timestamp(),
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
        # unset error:Worker orphan-sweep 可能在跑到一半誤標 SERVER_RESTART,完成後清掉
        self._update_task(task_id, update_data, unset_fields=["error"])

        task = self._get_task(task_id)
        if not task:
            return
        user = task.get("user")
        user_id = user.get("user_id") if isinstance(user, dict) else task.get("user_id")
        if not user_id:
            return

        self._consume_quota(task_id, task, user_id, language)

    def _consume_quota(self, task_id, task, user_id, language) -> None:
        """兩步式扣款:刪預扣 → 套 consumption pipeline。論證見 reservation_repo。"""
        audio_duration_seconds = (task.get("stats") or {}).get("audio_duration_seconds", 0)
        if audio_duration_seconds <= 0:
            return
        from bson import ObjectId
        from src.auth.quota import build_transcription_consumption_pipeline
        from src.database.repositories.reservation_repo import consume_reservation_sync

        try:
            reservation = consume_reservation_sync(self.db, task_id)
        except Exception as e:
            log.warning("quota.reservation.consume_failed", error=str(e))
            return
        if reservation is None:
            log.info("quota.reservation.absent")
            return
        try:
            duration_minutes = audio_duration_seconds / 60
            pipeline = build_transcription_consumption_pipeline(
                duration_minutes=duration_minutes, now_ts=get_utc_timestamp(),
            )
            self.db.users.update_one({"_id": ObjectId(user_id)}, pipeline)
        except Exception as e:
            # quota.leak 是監控訊號:預扣已刪、扣款未套用 = 漏算一次
            log.error(
                "quota.leak", user_id=user_id,
                duration_minutes=audio_duration_seconds / 60, error=str(e),
            )

    def _mark_failed(self, task_id: str, error: str) -> None:
        """標記失敗 + 釋放預扣(idempotent)。"""
        log.info("task.marked_failed", error=error)
        self._update_task(
            task_id, {"status": "failed", "error": {"code": "SYSTEM_ERROR", "message": error}}
        )
        try:
            from src.database.repositories.reservation_repo import release_reservation_sync
            release_reservation_sync(self.db, task_id)
        except Exception as e:
            log.warning("quota.reservation.release_failed", error=str(e))

    # ── private:DB helpers ───────────────────────────

    def _get_task(self, task_id: str) -> Optional[dict]:
        try:
            return self.db.tasks.find_one({"_id": task_id})
        except Exception as e:
            log.warning("task.fetch_failed", error=str(e))
            return None

    def _update_task(self, task_id: str, updates: dict, unset_fields=None) -> bool:
        try:
            updates["updated_at"] = get_utc_timestamp()
            op = {"$set": updates}
            if unset_fields:
                op["$unset"] = {f: "" for f in unset_fields}
            self.db.tasks.update_one({"_id": task_id}, op)
            return True
        except Exception as e:
            log.error("task.update_failed", error=str(e))
            return False

    def _cleanup_temp_dir(self, temp_dir: Path) -> None:
        try:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            log.warning("temp_dir.cleanup_failed", error=str(e))
