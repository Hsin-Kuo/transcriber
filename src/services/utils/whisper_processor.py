"""
WhisperProcessor - Whisper 轉錄處理器
職責：Whisper 模型的封裝（無狀態工具類）
"""

from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import subprocess
import json
from pydub import AudioSegment
from faster_whisper import WhisperModel


class WhisperProcessor:
    """Whisper 轉錄處理器

    封裝 Whisper 模型的轉錄功能，提供無狀態的轉錄方法
    """

    def __init__(self, model: WhisperModel):
        """初始化 WhisperProcessor

        Args:
            model: Whisper 模型實例
        """
        self.model = model

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None
    ) -> Tuple[str, List[Dict], str]:
        """轉錄音檔（單次轉錄，不分段）

        Args:
            audio_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）

        Returns:
            (完整文字, segments 列表, 偵測到的語言)
        """
        segments_list, detected_language = self._transcribe_with_timestamps(
            audio_path, language
        )

        # 合併所有 segment 的文字
        full_text = " ".join(seg["text"] for seg in segments_list)

        return full_text, segments_list, detected_language

    def transcribe_in_chunks(
        self,
        audio_path: Path,
        chunk_duration_ms: int = 600000,  # 10 分鐘
        language: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> Tuple[str, List[Dict], str]:
        """將音檔分段後轉錄（提高長音檔的準確度）

        Args:
            audio_path: 音檔路徑
            chunk_duration_ms: 每段長度（毫秒）
            language: 語言代碼（None 表示自動偵測）
            progress_callback: 進度回調函數 callback(chunk_idx, total_chunks)

        Returns:
            (完整文字, segments 列表, 偵測到的語言)
        """
        # 獲取音檔總長度
        total_duration_ms = self._get_audio_duration(audio_path)
        total_minutes = total_duration_ms / 1000 / 60
        print(f"📊 音檔總長度：{total_minutes:.1f} 分鐘")

        # 如果音檔不長，直接轉錄
        if total_duration_ms <= chunk_duration_ms:
            print(f"📝 音檔長度在 {chunk_duration_ms/1000/60:.0f} 分鐘內，直接轉錄...")
            return self.transcribe(audio_path, language)

        # 長音檔：分段處理
        num_chunks = (total_duration_ms + chunk_duration_ms - 1) // chunk_duration_ms
        print(f"🔄 音檔較長，將分為 {num_chunks} 段處理（每段約 {chunk_duration_ms/1000/60:.0f} 分鐘）...")

        # 切分音檔
        chunk_files = self._split_audio_into_chunks(
            audio_path, total_duration_ms, chunk_duration_ms
        )

        # 轉錄每個 chunk
        all_text_parts = []
        all_segments = []
        detected_language = None

        for chunk_idx, chunk_path in enumerate(chunk_files, start=1):
            print(f"🎙 轉錄第 {chunk_idx}/{num_chunks} 段...")

            # 進度回調
            if progress_callback:
                progress_callback(chunk_idx, num_chunks)

            # 轉錄這個 chunk
            chunk_text, chunk_segments, chunk_lang = self.transcribe(
                chunk_path, language
            )

            all_text_parts.append(chunk_text)
            all_segments.extend(chunk_segments)

            # 記錄偵測到的語言（使用第一段的結果）
            if detected_language is None:
                detected_language = chunk_lang

            # 清理臨時檔案
            try:
                chunk_path.unlink()
            except Exception as e:
                print(f"⚠️ 清理 chunk 檔案失敗：{e}")

        # 合併所有文字
        full_text = " ".join(all_text_parts)

        return full_text, all_segments, detected_language

    def transcribe_with_diarization(
        self,
        audio_path: Path,
        diarization_segments: List[Dict],
        language: Optional[str] = None
    ) -> Tuple[str, List[Dict], str]:
        """轉錄音檔並合併說話者辨識結果

        Args:
            audio_path: 音檔路徑
            diarization_segments: 說話者辨識結果
            language: 語言代碼

        Returns:
            (帶說話者標記的文字, segments 列表, 偵測到的語言)
        """
        # 先轉錄
        _, segments_list, detected_language = self.transcribe(audio_path, language)

        # 合併 diarization 結果
        merged_text = self._merge_transcription_with_diarization(
            segments_list, diarization_segments
        )

        return merged_text, segments_list, detected_language

    # ========== 私有輔助方法 ==========

    def _transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: Optional[str] = None
    ) -> Tuple[List[Dict], str]:
        """轉錄音檔並返回帶時間戳的 segments

        Args:
            audio_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）

        Returns:
            (segments 列表, 偵測到的語言)
        """
        segments_list = []
        segments, info = self.model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5
        )

        # 獲取 Whisper 偵測到的語言
        detected_language = info.language if hasattr(info, 'language') else None

        for segment in segments:
            segments_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text
            })

        return segments_list, detected_language

    def _get_audio_duration(self, audio_path: Path) -> int:
        """獲取音檔總長度（毫秒）

        優先使用 ffprobe（快速，不載入記憶體），失敗時回退到 pydub

        Args:
            audio_path: 音檔路徑

        Returns:
            音檔長度（毫秒）
        """
        # 使用 ffprobe 獲取音檔資訊，不載入到記憶體
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', str(audio_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                probe_data = json.loads(result.stdout)
                total_duration_seconds = float(probe_data['format']['duration'])
                return int(total_duration_seconds * 1000)

        except Exception as e:
            print(f"⚠️ ffprobe 失敗，回退到 pydub: {e}")

        # 回退到 pydub
        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)
        del audio  # 立即釋放記憶體
        return duration_ms

    def _split_audio_into_chunks(
        self,
        audio_path: Path,
        total_duration_ms: int,
        chunk_duration_ms: int
    ) -> List[Path]:
        """將音檔切分為多個小段

        使用 ffmpeg 流式處理，避免記憶體問題

        Args:
            audio_path: 原始音檔路徑
            total_duration_ms: 音檔總長度（毫秒）
            chunk_duration_ms: 每段長度（毫秒）

        Returns:
            chunk 檔案路徑列表
        """
        chunk_files = []
        start_ms = 0
        chunk_idx = 1

        while start_ms < total_duration_ms:
            end_ms = min(start_ms + chunk_duration_ms, total_duration_ms)

            print(f"   準備第 {chunk_idx} 段 ({start_ms/1000/60:.1f}-{end_ms/1000/60:.1f} 分鐘)...")

            # 使用 ffmpeg 直接切分，不載入到記憶體
            temp_path = audio_path.parent / f"_temp_{audio_path.stem}_chunk_{chunk_idx}.wav"
            start_seconds = start_ms / 1000.0
            duration_seconds = (end_ms - start_ms) / 1000.0

            try:
                # 使用 ffmpeg 切分音檔（流式處理，不佔用記憶體）
                subprocess.run([
                    'ffmpeg', '-y', '-i', str(audio_path),
                    '-ss', str(start_seconds),
                    '-t', str(duration_seconds),
                    '-acodec', 'pcm_s16le',  # WAV 格式
                    '-ar', '16000',  # 16kHz 採樣率（Whisper 推薦）
                    '-ac', '1',  # 單聲道
                    str(temp_path)
                ], check=True, capture_output=True, timeout=60)

            except subprocess.TimeoutExpired:
                print(f"   ⚠️ 切分第 {chunk_idx} 段超時，嘗試使用 pydub")
                # 回退到 pydub（較慢但更穩定）
                audio = AudioSegment.from_file(audio_path)
                chunk_audio = audio[start_ms:end_ms]
                chunk_audio.export(temp_path, format="wav")
                del audio, chunk_audio  # 立即釋放

            except Exception as e:
                print(f"   ⚠️ ffmpeg 切分失敗，回退到 pydub: {e}")
                # 回退到 pydub
                audio = AudioSegment.from_file(audio_path)
                chunk_audio = audio[start_ms:end_ms]
                chunk_audio.export(temp_path, format="wav")
                del audio, chunk_audio  # 立即釋放

            chunk_files.append(temp_path)
            start_ms = end_ms
            chunk_idx += 1

        return chunk_files

    def _merge_transcription_with_diarization(
        self,
        transcription_segments: List[Dict],
        diarization_segments: List[Dict]
    ) -> str:
        """合併轉錄文字和說話者標記

        Args:
            transcription_segments: Whisper 轉錄結果 (帶時間戳)
            diarization_segments: Speaker diarization 結果

        Returns:
            合併後的文字，格式：[Speaker A] 文字內容
        """
        if not diarization_segments:
            # 沒有 diarization 結果，直接返回純文字
            return " ".join(seg.get("text", "") for seg in transcription_segments)

        # 為每個轉錄片段分配說話者
        result_lines = []
        current_speaker = None
        current_text = []

        for trans_seg in transcription_segments:
            trans_start = trans_seg.get("start", 0)
            trans_end = trans_seg.get("end", 0)
            trans_text = trans_seg.get("text", "")

            if not trans_text.strip():
                continue

            # 找到與此轉錄片段重疊最多的說話者
            best_speaker = None
            max_overlap = 0

            for dia_seg in diarization_segments:
                dia_start = dia_seg["start"]
                dia_end = dia_seg["end"]

                # 計算重疊時間
                overlap_start = max(trans_start, dia_start)
                overlap_end = min(trans_end, dia_end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = dia_seg["speaker"]

            # 如果說話者改變，輸出之前的內容
            if best_speaker != current_speaker and current_text:
                speaker_label = f"[{current_speaker}]" if current_speaker else ""
                result_lines.append(f"{speaker_label} {''.join(current_text)}")
                current_text = []

            current_speaker = best_speaker
            current_text.append(trans_text)

        # 輸出最後一段
        if current_text:
            speaker_label = f"[{current_speaker}]" if current_speaker else ""
            result_lines.append(f"{speaker_label} {''.join(current_text)}")

        return "\n\n".join(result_lines)
