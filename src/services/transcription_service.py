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
from .progress_store import ProgressStore
from .transcription_orchestrator import TranscriptionOrchestrator
from .utils.whisper_processor import WhisperProcessor
from .utils.punctuation_processor import PunctuationProcessor
from .utils.diarization_processor import DiarizationProcessor
from src.database.sync_client import get_sync_db
from src.utils.time_utils import get_utc_timestamp


class TranscriptionService:
    """轉錄協調服務

    協調 Whisper 轉錄、標點處理、說話者辨識等功能
    """

    def __init__(
        self,
        task_service: TaskService,
        whisper_processor: WhisperProcessor,
        punctuation_processor: PunctuationProcessor,
        progress_store: ProgressStore,
        diarization_processor: Optional[DiarizationProcessor] = None,
        executor: Optional[ThreadPoolExecutor] = None,
    ):
        """初始化 TranscriptionService

        Args:
            task_service: TaskService 實例
            whisper_processor: WhisperProcessor 實例
            punctuation_processor: PunctuationProcessor 實例
            progress_store: ProgressStore，所有進度寫入經由此介面
            diarization_processor: DiarizationProcessor 實例（可選）
            executor: 線程池執行器（可選）
        """
        self.task_service = task_service
        self.whisper = whisper_processor
        self.punctuation = punctuation_processor
        self.diarization = diarization_processor
        self.executor = executor or ThreadPoolExecutor(max_workers=3)
        self.progress_store = progress_store

        # 建立 Orchestrator（持有 Service 的 audio I/O + DB write callbacks）
        # 避免循環依賴：注入 bound methods 而非 self
        self.orchestrator = TranscriptionOrchestrator(
            whisper=self.whisper,
            punctuation=self.punctuation,
            diarization=self.diarization,
            progress_store=self.progress_store,
            task_service=self.task_service,
            convert_audio_to_mp3=self._convert_audio_to_mp3,
            save_audio_file_sync=self._save_audio_file_sync,
            save_transcription_results=self._save_transcription_results,
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
        """啟動轉錄任務（非阻擋）。submit orchestrator.run 進 executor，立即返回。"""
        # 如果 max_speakers 為 1，視為不需要辨識（只有一個講者無需辨識）
        if max_speakers == 1:
            use_diarization = False
            print("ℹ️  [start_transcription] max_speakers=1，停用說話者辨識")

        print(f"🚀 [start_transcription] 準備提交任務 {task_id} 到線程池")
        try:
            future = self.executor.submit(
                self.orchestrator.run,
                task_id,
                audio_file_path,
                language,
                use_chunking,
                use_punctuation,
                punctuation_provider,
                use_diarization,
                max_speakers,
                ui_language,
            )
            print(f"✅ [start_transcription] 任務 {task_id} 已成功提交到線程池")
            print(f"🔧 [start_transcription] Future 狀態: {future}")
        except Exception as e:
            print(f"❌ [start_transcription] 提交任務到線程池失敗：{e}")
            import traceback
            traceback.print_exc()


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


    def _get_task_sync(self, task_id: str) -> Optional[dict]:
        """同步獲取任務（避免 event loop 衝突）"""
        try:
            return get_sync_db().tasks.find_one({"_id": task_id})
        except Exception as e:
            print(f"⚠️ 同步獲取任務失敗：{e}")
            return None

    def _update_task_sync(self, task_id: str, updates: dict) -> bool:
        """同步更新任務（避免 event loop 衝突）

        Returns:
            bool: 是否更新成功
        """
        try:
            updates["updated_at"] = get_utc_timestamp()
            result = get_sync_db().tasks.update_one(
                {"_id": task_id},
                {"$set": updates}
            )
            print(f"✅ 同步更新任務 {task_id}，修改了 {result.modified_count} 條記錄")
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
            db = get_sync_db()

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

        except Exception as e:
            print(f"⚠️ 保存轉錄結果到 MongoDB 失敗：{e}")
            import traceback
            traceback.print_exc()

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
        - 所有音檔都會被保存（見 transcription_orchestrator._cleanup_temp_files）
        - keep_audio 只影響是否可以被自動刪除
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        Args:
            task_id: 當前任務 ID
        """
        try:
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

            db = get_sync_db()

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
            print("⚠️ [_save_audio_file_sync] 沒有找到音檔文件")
            return

        try:
            # 找到 MP3 檔案（應該已經是 16kHz MP3）
            mp3_file = None
            for f in audio_files:
                if f.suffix.lower() == '.mp3':
                    mp3_file = f
                    break

            if not mp3_file:
                print("⚠️ [_save_audio_file_sync] 未找到 MP3 檔案")
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
            print("✅ [_save_audio_file_sync] 已更新資料庫")
        except Exception as e:
            print(f"❌ [_save_audio_file_sync] 保存音檔時發生錯誤: {e}")
            import traceback
            traceback.print_exc()

