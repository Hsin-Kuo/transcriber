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
from src.utils.time_utils import get_utc_timestamp
from src.utils.text_utils import convert_segments_punctuation


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
        executor: Optional[ThreadPoolExecutor] = None
    ):
        """初始化 TranscriptionService

        Args:
            task_service: TaskService 實例
            whisper_processor: WhisperProcessor 實例
            punctuation_processor: PunctuationProcessor 實例
            diarization_processor: DiarizationProcessor 實例（可選）
            executor: 線程池執行器（可選）
        """
        self.task_service = task_service
        self.whisper = whisper_processor
        self.punctuation = punctuation_processor
        self.diarization = diarization_processor
        self.executor = executor or ThreadPoolExecutor(max_workers=3)

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
        # 如果 max_speakers 為 1，視為不需要辨識（只有一個講者無需辨識）
        if max_speakers == 1:
            use_diarization = False
            print(f"ℹ️  [start_transcription] max_speakers=1，停用說話者辨識")

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
            # 更新任務狀態為 processing
            self.task_service.update_memory_state(task_id, {"status": "processing"})

            # 1. 音訊轉換（轉為 MP3 格式，用於轉錄和保存）
            print(f"🔄 [_process_transcription] 開始轉換音檔為 MP3 格式")
            self._update_progress(task_id, "正在轉換音檔格式...", {"audio_converted": False})
            mp3_path = self._convert_audio_to_mp3(audio_file_path)
            print(f"✅ [_process_transcription] 音檔轉換完成: {mp3_path}")
            self._update_progress(task_id, "音檔轉換完成", {"audio_converted": True})

            # 檢查是否已取消
            if self._is_cancelled(task_id):
                self._cleanup_temp_files(task_id, mp3_path, save_audio=False)  # 取消時不保存音檔
                self.task_service.cleanup_task_memory(task_id)
                return

            # 2. 並行執行轉錄和說話者辨識（如果啟用）
            print(f"🎤 [_process_transcription] 開始並行處理：轉錄 + 說話者辨識")

            # 準備並行任務
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # 初始化變數
            full_text = None
            segments = None
            detected_language = None
            diarization_segments = None

            if use_diarization and self.diarization:
                # 並行模式：同時執行轉錄和說話者辨識
                self._update_progress(task_id, "正在並行執行轉錄和說話者辨識...", {
                    "diarization_started": True
                })

                with ThreadPoolExecutor(max_workers=2) as parallel_executor:
                    # 提交轉錄任務
                    transcription_future = parallel_executor.submit(
                        self._run_transcription,
                        task_id,
                        mp3_path,
                        language,
                        use_chunking
                    )

                    # 提交說話者辨識任務
                    diarization_future = parallel_executor.submit(
                        self._run_diarization,
                        task_id,
                        mp3_path,
                        max_speakers
                    )

                    # 等待兩個任務完成（使用 result() 會阻塞直到完成）
                    try:
                        # 並行等待兩個任務
                        for future in as_completed([transcription_future, diarization_future]):
                            if future == transcription_future:
                                full_text, segments, detected_language = future.result()
                                if full_text is not None:
                                    print(f"✅ [並行] Whisper 轉錄完成 (文字長度: {len(full_text)})")
                                else:
                                    print(f"⚠️ [並行] Whisper 轉錄返回空結果")
                            elif future == diarization_future:
                                diarization_segments = future.result()
                                if diarization_segments:
                                    num_speakers = len(set(s['speaker'] for s in diarization_segments))
                                    print(f"✅ [並行] 說話者辨識完成，識別到 {num_speakers} 位說話者")
                                else:
                                    print(f"⚠️ [並行] 說話者辨識失敗或無結果")
                    except Exception as e:
                        print(f"❌ [並行] 並行執行出錯：{e}")
                        import traceback
                        traceback.print_exc()

                # 合併結果
                if diarization_segments and segments:
                    # 獲取任務類型以決定處理方式
                    task = self._get_task_sync(task_id)
                    task_type = task.get("task_type", "paragraph") if task else "paragraph"

                    num_speakers = len(set(s['speaker'] for s in diarization_segments))

                    if task_type == "subtitle":
                        # 字幕模式：將 speaker 整合到 segments，文字不變
                        print(f"🎬 [字幕模式] 將說話者資訊整合到 segments...")
                        print(f"🎬 [字幕模式] 轉錄 segments 數量: {len(segments)}")
                        print(f"🎬 [字幕模式] 說話者 segments 數量: {len(diarization_segments)}")

                        segments = self.whisper._merge_speaker_to_segments(
                            segments, diarization_segments
                        )
                        # full_text 保持原樣（無說話者標記）

                        print(f"✅ [字幕模式] 已將 {num_speakers} 位說話者資訊加入 segments")
                        print(f"✅ [字幕模式] Segments 預覽: {segments[0] if segments else 'N/A'}")

                    else:
                        # 段落模式：合併到文字（現有行為）
                        print(f"📝 [段落模式] 合併轉錄和說話者辨識到文字...")
                        print(f"📝 [段落模式] 轉錄 segments 數量: {len(segments)}")
                        print(f"📝 [段落模式] 說話者 segments 數量: {len(diarization_segments)}")

                        merged_text = self.whisper._merge_transcription_with_diarization(
                            segments, diarization_segments
                        )

                        print(f"✅ [段落模式] 合併完成，文字長度: {len(merged_text)}")
                        print(f"✅ [段落模式] 已合併 {num_speakers} 位說話者到文字")
                        print(f"✅ [段落模式] 合併文字預覽: {merged_text[:200]}...")

                        full_text = merged_text

                    self._update_progress(task_id, "語者辨識完成", {
                        "diarization_completed": True,
                        "num_speakers": num_speakers
                    })
                else:
                    print(f"⚠️ [合併] 無法合併：diarization_segments={diarization_segments is not None}, segments={segments is not None}")
                    self._update_progress(task_id, "語者辨識失敗，使用原始文字", {
                        "diarization_failed": True
                    })
            else:
                # 只執行轉錄（無說話者辨識）
                print(f"🎤 [_process_transcription] 開始 Whisper 轉錄 (chunking={use_chunking})")
                full_text, segments, detected_language = self._run_transcription(
                    task_id,
                    mp3_path,
                    language,
                    use_chunking
                )

            # 檢查轉錄結果是否有效（可能因取消而為 None）
            if full_text is None:
                if self._is_cancelled(task_id):
                    print(f"🛑 [_process_transcription] 任務 {task_id} 已取消，中止處理")
                    self._cleanup_temp_files(task_id, mp3_path, save_audio=False)
                    self.task_service.cleanup_task_memory(task_id)
                    return
                else:
                    raise ValueError("轉錄結果為空")

            print(f"✅ [_process_transcription] 轉錄完成 (文字長度: {len(full_text)}, 語言: {detected_language})")

            # 檢查是否已取消
            if self._is_cancelled(task_id):
                self._cleanup_temp_files(task_id, mp3_path, save_audio=False)  # 取消時不保存音檔
                self.task_service.cleanup_task_memory(task_id)
                return

            # 3. 標點處理（可選）
            punctuation_model = None
            punctuation_token_usage = None
            if use_punctuation:
                self._update_progress(task_id, "正在添加標點符號...", {
                    "punctuation_started": True
                })

                try:
                    punctuated_text, punctuation_model, punctuation_token_usage = self.punctuation.process(
                        full_text,
                        provider=punctuation_provider,
                        language=detected_language or language or "zh",
                        progress_callback=lambda idx, total: self._update_punctuation_progress(
                            task_id, idx, total
                        )
                    )

                    self._update_progress(task_id, "標點處理完成", {
                        "punctuation_completed": True,
                        "punctuation_model": punctuation_model
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
                self._cleanup_temp_files(task_id, wav_path, save_audio=False)  # 取消時不保存音檔
                self.task_service.cleanup_task_memory(task_id)
                return

            # 4. 保存轉錄結果到 MongoDB
            # 將 segments 中的半形標點符號轉換為全形（中文適用）
            converted_segments = convert_segments_punctuation(segments)
            self._save_transcription_results(task_id, final_text, converted_segments)

            # 5. 標記完成
            self._mark_completed(
                task_id,
                detected_language or language,
                final_text,  # 传递文本用于计算字数
                punctuation_model,  # 传递标点符号模型信息
                punctuation_token_usage  # 传递 token 使用量
            )

            # 6. 清理臨時檔案（包含保存音檔）
            self._cleanup_temp_files(task_id, mp3_path)

            # 7. 清理超出限制的舊音檔（在新音檔保存後才執行）
            # ⚠️ 已停用：不再自動刪除音檔，未來由 AWS S3 Lifecycle Policy 管理
            # self._cleanup_old_audio_files(task_id)

            # 8. 清理記憶體狀態（在所有檔案操作完成後）
            self.task_service.cleanup_task_memory(task_id)
            print(f"🧹 已清理任務 {task_id} 的記憶體狀態", flush=True)

            print(f"✅ 任務 {task_id} 完成！")

        except Exception as e:
            print(f"❌ 轉錄失敗：{e}")
            self._mark_failed(task_id, str(e))
            self._cleanup_temp_files(task_id, None, save_audio=False)  # 失敗時不保存音檔
            self.task_service.cleanup_task_memory(task_id)
            print(f"🧹 已清理任務 {task_id} 的記憶體狀態", flush=True)

    # ========== 私有輔助方法 ==========

    def _convert_audio_to_mp3(self, audio_path: Path) -> Path:
        """轉換音檔為 MP3 格式 (16kHz, mono, 128kbps)

        用於 Whisper 轉錄和最終保存，避免重複轉換

        Args:
            audio_path: 原始音檔路徑

        Returns:
            MP3 檔案路徑
        """
        # 如果已經是 MP3，直接返回（Whisper 和 pyannote 都支援 MP3）
        if audio_path.suffix.lower() == '.mp3':
            return audio_path

        # 使用 ffmpeg 轉換為 16kHz MP3
        mp3_path = audio_path.with_suffix('.mp3')

        subprocess.run([
            'ffmpeg', '-y', '-i', str(audio_path),
            '-vn',  # 不處理視頻（支援影片檔輸入）
            '-acodec', 'libmp3lame',  # MP3 編碼器
            '-b:a', '128k',  # 128kbps（語音品質足夠）
            '-ar', '16000',  # 16kHz 採樣率（Whisper 推薦）
            '-ac', '1',  # 單聲道
            str(mp3_path)
        ], check=True, capture_output=True, timeout=300)

        # 轉換成功後立即刪除原始檔案，釋放儲存空間
        audio_path.unlink()

        return mp3_path


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

        print(f"📡 [SSE] 更新進度: {progress_text}", flush=True)
        self.task_service.update_memory_state(task_id, updates)

    def _update_chunk_progress(
        self,
        task_id: str,
        completed_chunks: int,
        total_chunks: int,
        processing_chunks: int = 0
    ) -> None:
        """更新分段轉錄進度

        Args:
            task_id: 任務 ID
            completed_chunks: 已完成的 chunk 數量
            total_chunks: 總 chunk 數
            processing_chunks: 正在處理中的 chunk 數量
        """
        self._update_progress(
            task_id,
            f"並行轉錄中（已完成 {completed_chunks}/{total_chunks} 段）...",
            {
                "total_chunks": total_chunks,
                "completed_chunks": completed_chunks,
                "processing_chunks": processing_chunks
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
            # 使用與主應用相同的 MongoDB 配置
            mongo_uri = os.getenv("MONGODB_URL", os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
            db_name = os.getenv("MONGODB_DB_NAME", "transcriber")
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client[db_name]

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
            # 創建同步的 MongoDB 客戶端，使用與主應用相同的配置
            mongo_uri = os.getenv("MONGODB_URL", os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
            db_name = os.getenv("MONGODB_DB_NAME", "transcriber")
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client[db_name]

            # 添加 updated_at (UTC timestamp)
            updates["updated_at"] = get_utc_timestamp()

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

    def _save_transcription_results(
        self,
        task_id: str,
        transcription_text: str,
        segments: Optional[list] = None
    ) -> None:
        """保存轉錄結果到 MongoDB

        Args:
            task_id: 任務 ID
            transcription_text: 轉錄文本
            segments: Segments 陣列（可選）
        """
        try:
            from pymongo import MongoClient
            import os

            # 連接 MongoDB（使用同步客戶端）
            mongo_uri = os.getenv("MONGODB_URL", os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
            db_name = os.getenv("MONGODB_DB_NAME", "transcriber")
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client[db_name]

            # 1. 保存轉錄文本到 transcriptions collection
            now = get_utc_timestamp()
            transcription_doc = {
                "_id": task_id,
                "content": transcription_text,
                "text_length": len(transcription_text),
                "created_at": now,
                "updated_at": now
            }

            # 使用 replace_one 來確保不會重複插入
            db.transcriptions.replace_one(
                {"_id": task_id},
                transcription_doc,
                upsert=True
            )
            print(f"✅ 已保存轉錄文本到 MongoDB (task_id: {task_id}, 長度: {len(transcription_text)})")

            # 2. 保存 segments 到 segments collection（如果有）
            if segments is not None and len(segments) > 0:
                segment_doc = {
                    "_id": task_id,
                    "segments": segments,
                    "segment_count": len(segments),
                    "created_at": now,
                    "updated_at": now
                }

                db.segments.replace_one(
                    {"_id": task_id},
                    segment_doc,
                    upsert=True
                )
                print(f"✅ 已保存 segments 到 MongoDB (task_id: {task_id}, 數量: {len(segments)})")

            client.close()

        except Exception as e:
            print(f"⚠️ 保存轉錄結果到 MongoDB 失敗：{e}")
            import traceback
            traceback.print_exc()

    def _mark_completed(
        self,
        task_id: str,
        language: Optional[str],
        transcription_text: str = "",
        punctuation_model: Optional[str] = None,
        punctuation_token_usage: Optional[Dict[str, int]] = None
    ) -> None:
        """標記任務完成

        Args:
            task_id: 任務 ID
            language: 偵測到的語言
            transcription_text: 轉錄文本（用於計算字數）
            punctuation_model: 使用的標點符號模型
            punctuation_token_usage: 標點處理的 token 使用量
        """
        from src.services.utils.async_utils import run_async_in_thread

        # 計算字數統計
        text_length = len(transcription_text)
        word_count = len(transcription_text.split())

        # 準備更新數據
        update_data = {
            "status": "completed",
            "result.text_length": text_length,  # 字符數
            "result.word_count": word_count,    # 詞數
            "config.language": language,
            "timestamps.completed_at": get_utc_timestamp(),
            "progress": "轉錄完成"
        }

        # 如果有標點符號模型信息，保存到 models.punctuation
        if punctuation_model:
            update_data["models.punctuation"] = punctuation_model

        # 如果有 token 使用量，保存到 stats.token_usage
        if punctuation_token_usage:
            update_data["stats.token_usage"] = {
                "total": punctuation_token_usage.get("total", 0),
                "prompt": punctuation_token_usage.get("prompt", 0),
                "completion": punctuation_token_usage.get("completion", 0),
                "model": punctuation_model or "unknown"
            }
            print(f"📊 保存 Token 使用量: {punctuation_token_usage}")

        # 1. 使用同步方法更新任務狀態
        self._update_task_sync(task_id, update_data)

        print(f"📊 字數統計：{text_length} 字元，{word_count} 詞")

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

                            mongo_uri = os.getenv("MONGODB_URL", os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
                            db_name = os.getenv("MONGODB_DB_NAME", "transcriber")
                            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                            db = client[db_name]

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
                                        "updated_at": get_utc_timestamp()
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

                        # 取得更詳細的任務資訊
                        original_filename = task.get("original_filename") or task.get("file", {}).get("original_filename", "未知")
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
                                    "quota_deducted_minutes": round(audio_duration_seconds / 60, 2)
                                }
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

        # 記錄 audit log（轉錄失敗）- 詳細記錄
        try:
            # 獲取任務信息以取得 user_id（使用同步方法）
            task = self._get_task_sync(task_id)
            if task:
                user_id = task.get("user", {}).get("user_id") if isinstance(task.get("user"), dict) else None
                if not user_id:
                    user_id = task.get("user_id")

                if user_id:
                    # Audit log 可以保持異步（較不重要）
                    from src.services.utils.async_utils import run_async_in_thread
                    from src.utils.audit_logger import get_audit_logger
                    audit_logger = get_audit_logger()

                    # 取得任務詳細資訊
                    original_filename = task.get("original_filename") or task.get("file", {}).get("original_filename", "未知")
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
                                "original_filename": original_filename
                            }
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

    def _cleanup_old_audio_files(self, task_id: str) -> None:
        """清理超出限制的舊音檔

        ⚠️ 已棄用（2026-01-16）：
        此方法已停用，不再自動刪除音檔。
        未來將由 AWS S3 Lifecycle Policy 管理音檔生命週期。
        keep_audio 功能保留，供未來 S3 標籤使用。

        ⚠️ 原邏輯說明（僅供參考）：
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【自動清理規則】
        1. 每個用戶最多保留 4 個音檔
        2. 超過 4 個時：
           - 從最舊的開始刪除
           - 跳過 keep_audio = True 的音檔（用戶手動保留）
           - 直到剩餘 4 個或無法再刪除為止

        【範例】
        假設有 5 個音檔：
        - 音檔1（舊）keep_audio=False → 會被刪除
        - 音檔2      keep_audio=False → 會被刪除
        - 音檔3      keep_audio=True  → 跳過（受保護）
        - 音檔4      keep_audio=False → 保留
        - 音檔5（新）keep_audio=False → 保留
        結果：保留音檔 3, 4, 5

        【重要】
        - keep_audio 不影響音檔是否被保存
        - 所有音檔都會被保存（見 _cleanup_temp_files）
        - keep_audio 只影響是否可以被自動刪除
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        Args:
            task_id: 當前任務 ID
        """
        try:
            from pymongo import MongoClient
            import os

            # 獲取當前任務的用戶 ID
            task = self._get_task_sync(task_id)
            if not task:
                return

            if isinstance(task.get("user"), dict):
                user_id = task["user"].get("user_id")
            else:
                user_id = task.get("user_id")

            if not user_id:
                return

            # 連接數據庫
            mongo_uri = os.getenv("MONGODB_URL", os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
            db_name = os.getenv("MONGODB_DB_NAME", "transcriber")
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
            db = client[db_name]

            # 查詢該用戶所有有音檔的任務，按創建時間排序
            # ⚠️ 排除已刪除的任務（deleted: True），已刪除的任務不計入額度
            tasks_with_audio = list(db.tasks.find({
                "user.user_id": user_id,
                "status": "completed",
                "result.audio_file": {"$exists": True, "$ne": None},
                "deleted": {"$ne": True}  # 排除已刪除的任務
            }).sort("timestamps.created_at", 1))  # 1 = 升序（舊到新）

            print(f"🔍 用戶 {user_id} 共有 {len(tasks_with_audio)} 個音檔")

            # S3 Lifecycle 會自動清理過期音檔，這裡只需清除 DB 中
            # 已被 Lifecycle 刪除的記錄（音檔不存在但 DB 還有路徑的情況）
            # 以及在 local 模式下保留原有的數量限制邏輯
            from src.utils.storage_service import delete_audio_by_path, audio_exists_by_path, is_aws as _is_aws

            if _is_aws():
                # AWS 模式：S3 Lifecycle 會處理過期，這裡只同步 DB 狀態
                for old_task in tasks_with_audio:
                    audio_file_path = old_task.get("result", {}).get("audio_file")
                    if audio_file_path and not audio_exists_by_path(audio_file_path):
                        # 音檔已被 S3 Lifecycle 刪除，清除 DB 記錄
                        db.tasks.update_one(
                            {"_id": old_task["_id"]},
                            {"$set": {
                                "result.audio_file": None,
                                "result.audio_filename": None
                            }}
                        )
                        print(f"🔄 音檔已過期（S3 Lifecycle），已清除 DB 記錄：{old_task['_id']}")
            else:
                # Local 模式：保留數量限制邏輯（最多 4 個）
                if len(tasks_with_audio) > 4:
                    to_delete_count = len(tasks_with_audio) - 4
                    deleted_count = 0

                    for old_task in tasks_with_audio:
                        if deleted_count >= to_delete_count:
                            break

                        if old_task.get("keep_audio", False):
                            print(f"⏭️  跳過任務 {old_task['_id']}（用戶已勾選保留）")
                            continue

                        audio_file_path = old_task.get("result", {}).get("audio_file")
                        if audio_file_path:
                            try:
                                delete_audio_by_path(audio_file_path)
                                print(f"🗑️ 已刪除舊音檔：{audio_file_path}")
                            except Exception as e:
                                print(f"⚠️ 刪除音檔失敗：{e}")

                            db.tasks.update_one(
                                {"_id": old_task["_id"]},
                                {"$set": {
                                    "result.audio_file": None,
                                    "result.audio_filename": None
                                }}
                            )
                            deleted_count += 1

                    print(f"✅ 自動清理完成，共刪除 {deleted_count} 個舊音檔")

            client.close()
        except Exception as e:
            print(f"⚠️ 清理舊音檔時發生錯誤：{e}")
            import traceback
            traceback.print_exc()

    def _save_audio_file_sync(self, task_id: str, temp_dir: Path, audio_files: list) -> None:
        """同步處理音檔保存（使用 storage_service 統一管理）

        由於在轉錄前已經轉換為 16kHz MP3，這裡只需移動/上傳
        """
        from src.utils.storage_service import save_audio

        print(f"🔧 [_save_audio_file_sync] 開始處理，audio_files 數量: {len(audio_files)}")

        if not audio_files:
            print(f"⚠️ [_save_audio_file_sync] 沒有找到音檔文件")
            return

        try:
            # 找到 MP3 檔案（應該已經是 16kHz MP3）
            mp3_file = None
            for f in audio_files:
                if f.suffix.lower() == '.mp3':
                    mp3_file = f
                    break

            if not mp3_file:
                print(f"⚠️ [_save_audio_file_sync] 未找到 MP3 檔案")
                return

            print(f"🔧 [_save_audio_file_sync] 找到 MP3: {mp3_file}")
            print(f"🔧 [_save_audio_file_sync] 音檔是否存在: {mp3_file.exists()}")

            # 從 task 取得用戶 tier
            task = self._get_task_sync(task_id)
            user_tier = task.get("user", {}).get("tier", "free") if task else "free"

            # 使用 storage_service 儲存（local: 移動到 uploads/，aws: 上傳到 uploads/{tier}/）
            stored_path = save_audio(task_id, mp3_file, tier=user_tier)
            print(f"💾 已儲存音檔: {stored_path}")

            # 使用同步方法更新任務的 audio_file 路徑
            # 保存原始檔名（但副檔名改為 .mp3）
            original_filename = Path(audio_files[0].name).stem + ".mp3"
            self._update_task_sync(task_id, {
                "result.audio_file": stored_path,
                "result.audio_filename": original_filename
            })
            print(f"✅ [_save_audio_file_sync] 已更新資料庫")
        except Exception as e:
            print(f"❌ [_save_audio_file_sync] 保存音檔時發生錯誤: {e}")
            import traceback
            traceback.print_exc()

    def _cleanup_temp_files(self, task_id: str, mp3_path: Optional[Path], save_audio: bool = True) -> None:
        """清理臨時檔案

        ⚠️ 重要邏輯說明（請勿修改）：
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        1. 【只有成功的轉錄會保存音檔】
           - save_audio=True：保存音檔（任務成功完成）
           - save_audio=False：不保存音檔（任務失敗或取消）

        2. 【keep_audio 的作用】
           - False（默認）：標記為可刪除（供未來 S3 Lifecycle 使用）
           - True（用戶勾選）：標記為保留（供未來 S3 標籤使用）

        3. 【自動清理機制】（已停用 2026-01-16）
           - 不再自動刪除音檔
           - 未來由 AWS S3 Lifecycle Policy 管理
           - keep_audio 標記將用於 S3 物件標籤
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        Args:
            task_id: 任務 ID
            mp3_path: MP3 檔案路徑（可選，如果已移動則為 None）
            save_audio: 是否保存音檔（True=成功完成，False=失敗/取消）
        """
        # 注意：如果 save_audio=True，MP3 已被移動到 uploads/，這裡不需要刪除
        # 只有在失敗/取消時才需要清理 MP3
        if not save_audio and mp3_path and mp3_path.exists():
            try:
                mp3_path.unlink()
                print(f"🗑️ 已清理臨時 MP3 檔案：{mp3_path.name}")
            except Exception as e:
                print(f"⚠️ 清理 MP3 檔案失敗：{e}")

        temp_dir = self.task_service.get_temp_dir(task_id)
        if temp_dir and temp_dir.exists():
            print(f"📁 臨時目錄: {temp_dir}")
            # 搜尋 input.* (單檔模式) 或 merged*.mp3 (合併模式)
            audio_files = list(temp_dir.glob("input.*")) + list(temp_dir.glob("merged*.mp3"))
            print(f"🎵 找到的音檔: {[f.name for f in audio_files]}")

            # 只有在任務成功完成時才保存音檔
            if save_audio:
                # 檢查是否需要保留音檔（使用同步方法）
                task = self._get_task_sync(task_id)
                keep_audio = task.get("keep_audio", False) if task else False

                print(f"🔍 任務 {task_id} 的 keep_audio 設定: {keep_audio}")

                try:
                    # 使用同步方法處理音檔保存（避免 event loop 衝突）
                    self._save_audio_file_sync(task_id, temp_dir, audio_files)

                    # 清理臨時目錄（不包含已移動的音檔）
                    shutil.rmtree(temp_dir)

                    if keep_audio:
                        print(f"🗑️ 已清理臨時目錄，音檔已保存並標記為受保護")
                    else:
                        print(f"🗑️ 已清理臨時目錄，音檔已保存（可被自動清理）")
                except Exception as e:
                    print(f"⚠️ 保存音檔失敗：{e}")
                    # 如果保存失敗，還是清理臨時目錄
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass
            else:
                # 任務失敗或取消，直接刪除臨時目錄和音檔
                print(f"⚠️ 任務未成功完成，不保存音檔")
                try:
                    shutil.rmtree(temp_dir)
                    print(f"🗑️ 已清理臨時目錄和音檔（任務失敗/取消）")
                except Exception as e:
                    print(f"⚠️ 清理臨時目錄失敗：{e}")

    def _run_transcription(
        self,
        task_id: str,
        mp3_path: Path,
        language: Optional[str],
        use_chunking: bool
    ) -> tuple:
        """執行 Whisper 轉錄（使用 MP3 格式，可並行執行）

        Args:
            task_id: 任務 ID
            mp3_path: MP3 檔案路徑（16kHz）
            language: 語言代碼
            use_chunking: 是否使用分段模式

        Returns:
            (full_text, segments, detected_language)
        """
        if use_chunking:
            self._update_progress(task_id, "正在並行分段轉錄音檔（多進程）...")
            full_text, segments, detected_language = self.whisper.transcribe_in_chunks_parallel(
                mp3_path,
                language=language,
                max_workers=3,
                progress_callback=lambda completed, total, processing=0: self._update_chunk_progress(
                    task_id, completed, total, processing
                ),
                cancel_check=lambda: self._is_cancelled(task_id)
            )
        else:
            self._update_progress(task_id, "正在轉錄音檔...")
            full_text, segments, detected_language = self.whisper.transcribe(
                mp3_path,
                language=language
            )
        return full_text, segments, detected_language

    def _run_diarization(
        self,
        task_id: str,
        mp3_path: Path,
        max_speakers: Optional[int]
    ) -> Optional[list]:
        """執行說話者辨識（使用 MP3 格式，可並行執行）

        Args:
            task_id: 任務 ID
            mp3_path: MP3 檔案路徑（16kHz）
            max_speakers: 最大講者人數

        Returns:
            diarization_segments 或 None（失敗時）
        """
        try:
            self._update_progress(task_id, "正在進行說話者辨識...", {
                "diarization_started": True
            })
            print(f"🔊 [並行] 開始說話者辨識")
            print(f"🔊 [並行] max_speakers 參數: {max_speakers}")

            diarization_segments = self.diarization.perform_diarization(
                mp3_path,
                max_speakers=max_speakers
            )

            return diarization_segments

        except Exception as diarize_error:
            print(f"⚠️ [並行] 說話者辨識失敗：{diarize_error}")
            self._update_progress(task_id, f"語者辨識失敗（{str(diarize_error)[:100]}）", {
                "diarization_failed": True,
                "diarization_error": str(diarize_error)[:200]
            })
            return None
