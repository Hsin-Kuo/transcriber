"""
TranscriptionService - 轉錄協調服務
職責：
- 協調轉錄流程（音檔 → 轉錄 → 標點 → 儲存）
- 管理轉錄任務生命週期
- 處理檔案上傳和儲存
- 更新任務進度
"""

from pathlib import Path
from typing import Optional, Dict, Any, Callable
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import json
from datetime import datetime, timezone, timedelta

from .task_service import TaskService
from .utils.whisper_processor import WhisperProcessor
from .utils.punctuation_processor import PunctuationProcessor
from .utils.diarization_processor import DiarizationProcessor


# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))


class TranscriptionService:
    """轉錄協調服務

    協調 Whisper 轉錄、標點處理、說話者辨識等功能
    """

    def __init__(
        self,
        task_service: TaskService,
        whisper_processor: WhisperProcessor,
        punctuation_processor: PunctuationProcessor,
        diarization_processor: Optional[DiarizationProcessor] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        output_dir: Optional[Path] = None
    ):
        """初始化 TranscriptionService

        Args:
            task_service: TaskService 實例
            whisper_processor: WhisperProcessor 實例
            punctuation_processor: PunctuationProcessor 實例
            diarization_processor: DiarizationProcessor 實例（可選）
            executor: 線程池執行器（可選）
            output_dir: 輸出目錄（可選）
        """
        self.task_service = task_service
        self.whisper = whisper_processor
        self.punctuation = punctuation_processor
        self.diarization = diarization_processor
        self.executor = executor or ThreadPoolExecutor(max_workers=3)
        self.output_dir = output_dir or Path("output")
        self.output_dir.mkdir(exist_ok=True)

    async def start_transcription(
        self,
        task_id: str,
        audio_file_path: Path,
        language: Optional[str] = None,
        use_chunking: bool = False,
        use_punctuation: bool = True,
        punctuation_provider: str = "gemini",
        use_diarization: bool = False,
        max_speakers: Optional[int] = None
    ) -> None:
        """啟動轉錄任務（異步執行）

        Args:
            task_id: 任務 ID
            audio_file_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）
            use_chunking: 是否使用分段模式
            use_punctuation: 是否使用標點處理
            punctuation_provider: 標點處理提供商（"gemini" 或 "openai"）
            use_diarization: 是否使用說話者辨識
            max_speakers: 最大講者人數（2-10）
        """
        # 在背景執行轉錄
        print(f"🚀 [start_transcription] 準備提交任務 {task_id} 到線程池")
        print(f"🔧 [start_transcription] 線程池狀態: {self.executor._threads if hasattr(self.executor, '_threads') else 'unknown'}")

        try:
            future = self.executor.submit(
                self._process_transcription,
                task_id,
                audio_file_path,
                language,
                use_chunking,
                use_punctuation,
                punctuation_provider,
                use_diarization,
                max_speakers
            )
            print(f"✅ [start_transcription] 任務 {task_id} 已成功提交到線程池")
            print(f"🔧 [start_transcription] Future 狀態: {future}")
        except Exception as e:
            print(f"❌ [start_transcription] 提交任務到線程池失敗：{e}")
            import traceback
            traceback.print_exc()

    def _process_transcription(
        self,
        task_id: str,
        audio_file_path: Path,
        language: Optional[str],
        use_chunking: bool,
        use_punctuation: bool,
        punctuation_provider: str,
        use_diarization: bool,
        max_speakers: Optional[int]
    ) -> None:
        """轉錄流程協調（同步執行，在背景線程中調用）

        Args:
            task_id: 任務 ID
            audio_file_path: 音檔路徑
            language: 語言代碼
            use_chunking: 是否使用分段模式
            use_punctuation: 是否使用標點處理
            punctuation_provider: 標點處理提供商
            use_diarization: 是否使用說話者辨識
            max_speakers: 最大講者人數
        """
        print(f"🎬 [_process_transcription] 開始處理任務 {task_id}")
        print(f"🔧 [_process_transcription] 音檔路徑: {audio_file_path}")
        print(f"🔧 [_process_transcription] 音檔是否存在: {audio_file_path.exists()}")

        try:
            # 1. 音訊轉換（轉為 WAV 格式）
            print(f"🔄 [_process_transcription] 開始轉換音檔格式")
            self._update_progress(task_id, "正在轉換音檔格式...", {"audio_converted": False})
            wav_path = self._convert_audio_to_wav(audio_file_path)
            print(f"✅ [_process_transcription] 音檔轉換完成: {wav_path}")
            self._update_progress(task_id, "音檔轉換完成", {"audio_converted": True})

            # 檢查是否已取消
            if self._is_cancelled(task_id):
                self._cleanup_temp_files(task_id, wav_path)
                return

            # 2. 執行轉錄
            print(f"🎤 [_process_transcription] 開始 Whisper 轉錄 (chunking={use_chunking})")
            if use_chunking:
                self._update_progress(task_id, "正在分段轉錄音檔...")
                full_text, segments, detected_language = self.whisper.transcribe_in_chunks(
                    wav_path,
                    language=language,
                    progress_callback=lambda idx, total: self._update_chunk_progress(
                        task_id, idx, total
                    )
                )
            else:
                self._update_progress(task_id, "正在轉錄音檔...")
                full_text, segments, detected_language = self.whisper.transcribe(
                    wav_path,
                    language=language
                )
            print(f"✅ [_process_transcription] Whisper 轉錄完成 (文字長度: {len(full_text)}, 語言: {detected_language})")

            # 檢查是否已取消
            if self._is_cancelled(task_id):
                self._cleanup_temp_files(task_id, wav_path)
                return

            # 3. 標點處理（可選）
            if use_punctuation:
                self._update_progress(task_id, "正在添加標點符號...", {
                    "punctuation_started": True
                })

                try:
                    punctuated_text = self.punctuation.process(
                        full_text,
                        provider=punctuation_provider,
                        language=detected_language or language or "zh",
                        progress_callback=lambda idx, total: self._update_punctuation_progress(
                            task_id, idx, total
                        )
                    )

                    self._update_progress(task_id, "標點處理完成", {
                        "punctuation_completed": True
                    })

                    final_text = punctuated_text
                except Exception as punct_error:
                    print(f"⚠️ [_process_transcription] 標點處理失敗：{punct_error}")
                    print(f"   將使用原始轉錄文字（無標點）繼續完成任務")
                    # 使用原始文字繼續，不中斷整個轉錄流程
                    final_text = full_text
                    self._update_progress(task_id, f"標點處理失敗（{str(punct_error)[:100]}），使用原始文字", {
                        "punctuation_failed": True,
                        "punctuation_error": str(punct_error)[:200]
                    })
            else:
                final_text = full_text

            # 檢查是否已取消
            if self._is_cancelled(task_id):
                self._cleanup_temp_files(task_id, wav_path)
                return

            # 4. 儲存結果
            self._update_progress(task_id, "正在儲存結果...")
            result_file_path = self._save_results(task_id, final_text)
            segments_file_path = self._save_segments(task_id, segments)

            # 5. 標記完成
            self._mark_completed(
                task_id,
                result_file_path,
                segments_file_path,
                detected_language or language
            )

            # 6. 清理臨時檔案
            self._cleanup_temp_files(task_id, wav_path)

            print(f"✅ 任務 {task_id} 完成！")

        except Exception as e:
            print(f"❌ 轉錄失敗：{e}")
            self._mark_failed(task_id, str(e))
            self._cleanup_temp_files(task_id, None)

    # ========== 私有輔助方法 ==========

    def _convert_audio_to_wav(self, audio_path: Path) -> Path:
        """轉換音檔為 WAV 格式

        Args:
            audio_path: 原始音檔路徑

        Returns:
            WAV 檔案路徑
        """
        # 如果已經是 WAV，直接返回
        if audio_path.suffix.lower() == '.wav':
            return audio_path

        # 使用 ffmpeg 轉換
        wav_path = audio_path.with_suffix('.wav')

        subprocess.run([
            'ffmpeg', '-y', '-i', str(audio_path),
            '-acodec', 'pcm_s16le',  # WAV 格式
            '-ar', '16000',  # 16kHz 採樣率（Whisper 推薦）
            '-ac', '1',  # 單聲道
            str(wav_path)
        ], check=True, capture_output=True, timeout=300)

        return wav_path

    def _save_results(self, task_id: str, text: str) -> Path:
        """儲存轉錄結果

        Args:
            task_id: 任務 ID
            text: 轉錄文字

        Returns:
            結果檔案路徑
        """
        result_file = self.output_dir / f"{task_id}.txt"
        result_file.write_text(text, encoding='utf-8')
        return result_file

    def _save_segments(self, task_id: str, segments: list) -> Path:
        """儲存 segments 資料

        Args:
            task_id: 任務 ID
            segments: Segments 列表

        Returns:
            Segments 檔案路徑
        """
        segments_file = self.output_dir / f"{task_id}_segments.json"
        segments_file.write_text(
            json.dumps(segments, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        return segments_file

    def _update_progress(
        self,
        task_id: str,
        progress_text: str,
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> None:
        """更新任務進度

        Args:
            task_id: 任務 ID
            progress_text: 進度文字
            extra_fields: 額外欄位
        """
        updates = {"progress": progress_text}
        if extra_fields:
            updates.update(extra_fields)

        self.task_service.update_memory_state(task_id, updates)

    def _update_chunk_progress(
        self,
        task_id: str,
        chunk_idx: int,
        total_chunks: int
    ) -> None:
        """更新分段轉錄進度

        Args:
            task_id: 任務 ID
            chunk_idx: 當前 chunk 索引
            total_chunks: 總 chunk 數
        """
        self._update_progress(
            task_id,
            f"正在轉錄第 {chunk_idx}/{total_chunks} 段...",
            {
                "total_chunks": total_chunks,
                "completed_chunks": chunk_idx - 1
            }
        )

    def _update_punctuation_progress(
        self,
        task_id: str,
        chunk_idx: int,
        total_chunks: int
    ) -> None:
        """更新標點處理進度

        Args:
            task_id: 任務 ID
            chunk_idx: 當前段落索引
            total_chunks: 總段落數
        """
        self._update_progress(
            task_id,
            f"正在添加標點（第 {chunk_idx}/{total_chunks} 段）...",
            {
                "punctuation_current_chunk": chunk_idx,
                "punctuation_total_chunks": total_chunks
            }
        )

    def _get_task_sync(self, task_id: str) -> Optional[dict]:
        """同步獲取任務（避免 event loop 衝突）"""
        from pymongo import MongoClient
        import os

        try:
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
            client = MongoClient(mongo_uri)
            db = client.transcriber

            task = db.tasks.find_one({"_id": task_id})
            client.close()
            return task
        except Exception as e:
            print(f"⚠️ 同步獲取任務失敗：{e}")
            return None

    def _update_task_sync(self, task_id: str, updates: dict) -> bool:
        """同步更新任務（避免 event loop 衝突）

        Returns:
            bool: 是否更新成功
        """
        from pymongo import MongoClient
        import os

        try:
            # 創建同步的 MongoDB 客戶端
            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client.transcriber

            # 添加 updated_at
            updates["updated_at"] = datetime.utcnow()

            # 執行更新
            result = db.tasks.update_one(
                {"_id": task_id},
                {"$set": updates}
            )

            print(f"✅ 同步更新任務 {task_id}，修改了 {result.modified_count} 條記錄")
            client.close()
            return result.modified_count > 0
        except Exception as e:
            print(f"❌ [CRITICAL] 同步更新任務失敗：{e}")
            import traceback
            traceback.print_exc()
            return False

    def _mark_completed(
        self,
        task_id: str,
        result_file_path: Path,
        segments_file_path: Path,
        language: Optional[str]
    ) -> None:
        """標記任務完成

        Args:
            task_id: 任務 ID
            result_file_path: 結果檔案路徑
            segments_file_path: Segments 檔案路徑
            language: 偵測到的語言
        """
        from src.services.utils.async_utils import run_async_in_thread

        # 1. 使用同步方法更新任務狀態
        self._update_task_sync(task_id, {
            "status": "completed",
            "result.transcription_file": str(result_file_path),
            "result.transcription_filename": result_file_path.name,
            "result.segments_file": str(segments_file_path),
            "config.language": language,
            "timestamps.completed_at": datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S"),
            "progress": "轉錄完成"
        })

        # 2. 獲取任務信息並處理配額扣除（使用同步方法）
        try:
            task = self._get_task_sync(task_id)
            if task:
                # 提取用戶 ID
                if isinstance(task.get("user"), dict):
                    user_id = task["user"].get("user_id")
                else:
                    user_id = task.get("user_id")

                # 扣除配額
                if user_id:
                    try:
                        audio_duration_seconds = task.get("stats", {}).get("audio_duration_seconds", 0)
                        if audio_duration_seconds > 0:
                            # 使用同步方式更新配額
                            from pymongo import MongoClient
                            from bson import ObjectId
                            import os

                            mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
                            client = MongoClient(mongo_uri)
                            db = client.transcriber

                            db.users.update_one(
                                {"_id": ObjectId(user_id)},
                                {
                                    "$inc": {
                                        "usage.transcriptions": 1,
                                        "usage.duration_minutes": audio_duration_seconds / 60,
                                        "usage.total_transcriptions": 1,
                                        "usage.total_duration_minutes": audio_duration_seconds / 60
                                    },
                                    "$set": {
                                        "updated_at": datetime.utcnow()
                                    }
                                }
                            )
                            client.close()
                            print(f"✅ 已扣除配額：用戶 {user_id}，時長 {audio_duration_seconds:.2f} 秒")
                    except Exception as quota_error:
                        print(f"⚠️ 扣除配額失敗：{quota_error}")

                    # Audit log 保持異步（較不重要，失敗也沒關係）
                    try:
                        from src.utils.audit_logger import get_audit_logger
                        audit_logger = get_audit_logger()
                        run_async_in_thread(
                            audit_logger.log_background_task(
                                log_type="transcription",
                                action="completed",
                                user_id=user_id,
                                task_id=task_id,
                                status_code=200,
                                message=f"轉錄完成（語言：{language}）"
                            )
                        )
                    except Exception as log_error:
                        print(f"⚠️ 記錄 audit log 失敗：{log_error}")
        except Exception as e:
            print(f"⚠️ 處理任務完成後續作業失敗：{e}")

    def _mark_failed(self, task_id: str, error: str) -> None:
        """標記任務失敗

        Args:
            task_id: 任務 ID
            error: 錯誤訊息
        """
        print(f"❌ [_mark_failed] 標記任務 {task_id} 為失敗狀態")
        print(f"   錯誤信息: {error}")

        # 使用同步方法更新任務狀態
        success = self._update_task_sync(task_id, {
            "status": "failed",
            "error": error,
            "progress": f"轉錄失敗：{error}"
        })

        if not success:
            print(f"❌ [CRITICAL] 無法將任務 {task_id} 標記為失敗！請檢查 MongoDB 連接")
            # 嘗試使用 task_service 的內存狀態更新
            try:
                self.task_service.update_memory_state(task_id, {
                    "status": "failed",
                    "error": error,
                    "progress": f"轉錄失敗：{error}"
                })
                print(f"✅ 已更新任務 {task_id} 的內存狀態")
            except Exception as mem_err:
                print(f"❌ 更新內存狀態也失敗：{mem_err}")

        # 記錄 audit log（轉錄失敗）
        try:
            # 獲取任務信息以取得 user_id（使用同步方法）
            task = self._get_task_sync(task_id)
            if task:
                user_id = task.get("user", {}).get("user_id") if isinstance(task.get("user"), dict) else None
                if user_id:
                    # Audit log 可以保持異步（較不重要）
                    from src.services.utils.async_utils import run_async_in_thread
                    from src.utils.audit_logger import get_audit_logger
                    audit_logger = get_audit_logger()
                    run_async_in_thread(
                        audit_logger.log_background_task(
                            log_type="transcription",
                            action="failed",
                            user_id=user_id,
                            task_id=task_id,
                            status_code=500,
                            message="轉錄失敗",
                            error=error
                        )
                    )
        except Exception as e:
            print(f"⚠️ 記錄 audit log 失敗：{e}")

    def _is_cancelled(self, task_id: str) -> bool:
        """檢查任務是否已取消

        Args:
            task_id: 任務 ID

        Returns:
            是否已取消
        """
        return self.task_service.is_cancelled(task_id)

    def _save_audio_file_sync(self, task_id: str, temp_dir: Path, audio_files: list) -> None:
        """同步處理音檔保存和更新（避免 event loop 衝突）"""
        print(f"🔧 [_save_audio_file_sync] 開始處理，audio_files 數量: {len(audio_files)}")

        if not audio_files:
            print(f"⚠️ [_save_audio_file_sync] 沒有找到音檔文件")
            return

        try:
            original_audio = audio_files[0]
            print(f"🔧 [_save_audio_file_sync] 原始音檔: {original_audio}")
            print(f"🔧 [_save_audio_file_sync] 音檔是否存在: {original_audio.exists()}")

            uploads_dir = Path("uploads")
            uploads_dir.mkdir(exist_ok=True)
            permanent_audio = uploads_dir / f"{task_id}{original_audio.suffix}"
            print(f"🔧 [_save_audio_file_sync] 目標路徑: {permanent_audio}")

            # 移動音檔到永久目錄
            shutil.move(str(original_audio), str(permanent_audio))
            print(f"💾 已保存音檔：{permanent_audio}")

            # 使用同步方法更新任務的 audio_file 路徑
            self._update_task_sync(task_id, {
                "result.audio_file": str(permanent_audio),
                "result.audio_filename": original_audio.name
            })
            print(f"✅ [_save_audio_file_sync] 已更新資料庫")
        except Exception as e:
            print(f"❌ [_save_audio_file_sync] 保存音檔時發生錯誤: {e}")
            import traceback
            traceback.print_exc()

    def _cleanup_temp_files(self, task_id: str, wav_path: Optional[Path]) -> None:
        """清理臨時檔案

        Args:
            task_id: 任務 ID
            wav_path: WAV 檔案路徑（可選）
        """
        # 清理 WAV 檔案（如果是轉換生成的）
        if wav_path and wav_path.exists():
            try:
                wav_path.unlink()
                print(f"🗑️ 已清理臨時 WAV 檔案：{wav_path.name}")
            except Exception as e:
                print(f"⚠️ 清理 WAV 檔案失敗：{e}")

        # 檢查是否需要保留音檔（使用同步方法）
        task = self._get_task_sync(task_id)
        keep_audio = task.get("keep_audio", True) if task else True  # 默認改為 True

        print(f"🔍 任務 {task_id} 的 keep_audio 設定: {keep_audio}")
        if task:
            print(f"🔍 任務數據中的 keep_audio: {task.get('keep_audio', '【不存在】')}")

        temp_dir = self.task_service.get_temp_dir(task_id)
        if temp_dir and temp_dir.exists():
            print(f"📁 臨時目錄: {temp_dir}")
            audio_files = list(temp_dir.glob("input.*"))
            print(f"🎵 找到的音檔: {[f.name for f in audio_files]}")

            if keep_audio:
                # 保留音檔：將原始音檔移動到永久儲存目錄
                try:
                    # 使用同步方法處理音檔保存（避免 event loop 衝突）
                    self._save_audio_file_sync(task_id, temp_dir, audio_files)

                    # 清理臨時目錄（不包含已移動的音檔）
                    shutil.rmtree(temp_dir)
                    print(f"🗑️ 已清理臨時目錄：{temp_dir.name}")
                except Exception as e:
                    print(f"⚠️ 保存音檔失敗：{e}")
                    # 如果保存失敗，還是清理臨時目錄
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass
            else:
                # 不保留音檔：直接刪除臨時目錄
                try:
                    shutil.rmtree(temp_dir)
                    print(f"🗑️ 已清理臨時目錄（含音檔）：{temp_dir.name}")
                except Exception as e:
                    print(f"⚠️ 清理臨時目錄失敗：{e}")
