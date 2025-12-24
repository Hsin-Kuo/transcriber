"""
AudioService - 音檔處理服務
職責：
- 音檔格式轉換
- 音檔裁切和合併
- 音檔清理
- 音檔元資料處理
"""

from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import subprocess
import json
from pydub import AudioSegment
from datetime import datetime, timedelta
import uuid
from threading import Lock
import pytz


TZ_UTC8 = pytz.timezone('Asia/Taipei')


class AudioService:
    """音檔處理服務

    提供音檔相關的業務邏輯
    """

    def __init__(self, output_dir: Optional[Path] = None, clips_dir: Optional[Path] = None):
        """初始化 AudioService

        Args:
            output_dir: 輸出目錄（可選）
            clips_dir: 片段儲存目錄（可選）
        """
        self.output_dir = output_dir or Path("output")
        self.output_dir.mkdir(exist_ok=True)

        # 片段管理
        self.clips_dir = clips_dir or (self.output_dir / "audio_clips")
        self.clips_dir.mkdir(exist_ok=True)

        self.audio_clips: Dict[str, Dict[str, Any]] = {}
        self.clips_lock = Lock()

    def convert_to_wav(
        self,
        audio_path: Path,
        sample_rate: int = 16000,
        channels: int = 1
    ) -> Path:
        """轉換音檔為 WAV 格式

        Args:
            audio_path: 原始音檔路徑
            sample_rate: 採樣率（默認 16kHz，Whisper 推薦）
            channels: 聲道數（默認單聲道）

        Returns:
            WAV 檔案路徑
        """
        # 如果已經是 WAV，檢查是否需要重新編碼
        if audio_path.suffix.lower() == '.wav':
            # 檢查採樣率和聲道
            if self._check_audio_format(audio_path, sample_rate, channels):
                return audio_path

        # 使用 ffmpeg 轉換
        wav_path = audio_path.with_suffix('.wav')

        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', str(audio_path),
                '-acodec', 'pcm_s16le',  # WAV 格式
                '-ar', str(sample_rate),  # 採樣率
                '-ac', str(channels),  # 聲道數
                str(wav_path)
            ], check=True, capture_output=True, timeout=300)

            return wav_path

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"音檔轉換失敗：{e.stderr.decode()}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("音檔轉換超時")

    def trim_audio(
        self,
        audio_path: Path,
        start_ms: int,
        end_ms: int,
        output_path: Optional[Path] = None
    ) -> Path:
        """裁切音檔

        Args:
            audio_path: 原始音檔路徑
            start_ms: 開始時間（毫秒）
            end_ms: 結束時間（毫秒）
            output_path: 輸出路徑（可選）

        Returns:
            裁切後的音檔路徑
        """
        if output_path is None:
            output_path = self.output_dir / f"trimmed_{audio_path.name}"

        # 使用 ffmpeg 裁切
        start_seconds = start_ms / 1000.0
        duration_seconds = (end_ms - start_ms) / 1000.0

        try:
            subprocess.run([
                'ffmpeg', '-y', '-i', str(audio_path),
                '-ss', str(start_seconds),
                '-t', str(duration_seconds),
                '-acodec', 'copy',  # 複製編碼（不重新編碼）
                str(output_path)
            ], check=True, capture_output=True, timeout=60)

            return output_path

        except subprocess.CalledProcessError as e:
            # 如果 copy 失敗，嘗試重新編碼
            try:
                subprocess.run([
                    'ffmpeg', '-y', '-i', str(audio_path),
                    '-ss', str(start_seconds),
                    '-t', str(duration_seconds),
                    str(output_path)
                ], check=True, capture_output=True, timeout=60)

                return output_path

            except subprocess.CalledProcessError:
                raise RuntimeError(f"音檔裁切失敗：{e.stderr.decode()}")

    def merge_audio_files(
        self,
        audio_paths: list[Path],
        output_path: Optional[Path] = None
    ) -> Path:
        """合併多個音檔

        Args:
            audio_paths: 音檔路徑列表
            output_path: 輸出路徑（可選）

        Returns:
            合併後的音檔路徑
        """
        if not audio_paths:
            raise ValueError("音檔列表不能為空")

        if len(audio_paths) == 1:
            return audio_paths[0]

        if output_path is None:
            output_path = self.output_dir / "merged_audio.wav"

        # 使用 pydub 合併
        try:
            combined = AudioSegment.empty()
            for audio_path in audio_paths:
                audio = AudioSegment.from_file(audio_path)
                combined += audio
                del audio  # 釋放記憶體

            combined.export(output_path, format="wav")
            del combined

            return output_path

        except Exception as e:
            raise RuntimeError(f"音檔合併失敗：{str(e)}")

    def get_audio_duration(self, audio_path: Path) -> int:
        """獲取音檔時長（毫秒）

        Args:
            audio_path: 音檔路徑

        Returns:
            音檔時長（毫秒）
        """
        # 優先使用 ffprobe（快速，不載入記憶體）
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', str(audio_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                probe_data = json.loads(result.stdout)
                duration_seconds = float(probe_data['format']['duration'])
                return int(duration_seconds * 1000)

        except Exception:
            pass

        # 回退到 pydub
        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)
        del audio
        return duration_ms

    def get_audio_info(self, audio_path: Path) -> dict:
        """獲取音檔詳細資訊

        Args:
            audio_path: 音檔路徑

        Returns:
            音檔資訊字典
        """
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', str(audio_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                probe_data = json.loads(result.stdout)
                format_info = probe_data.get('format', {})
                streams = probe_data.get('streams', [])

                # 找到音訊流
                audio_stream = next(
                    (s for s in streams if s.get('codec_type') == 'audio'),
                    {}
                )

                duration_seconds = float(format_info.get('duration', 0))

                return {
                    "filename": audio_path.name,
                    "format": format_info.get('format_name'),
                    "duration_seconds": duration_seconds,
                    "duration_ms": int(duration_seconds * 1000),
                    "size_bytes": int(format_info.get('size', 0)),
                    "size_mb": round(int(format_info.get('size', 0)) / 1024 / 1024, 2),
                    "bitrate": int(format_info.get('bit_rate', 0)),
                    "codec": audio_stream.get('codec_name'),
                    "sample_rate": int(audio_stream.get('sample_rate', 0)),
                    "channels": int(audio_stream.get('channels', 0)),
                }

        except Exception as e:
            # 回退到基本資訊
            return {
                "filename": audio_path.name,
                "size_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
                "size_mb": round(audio_path.stat().st_size / 1024 / 1024, 2) if audio_path.exists() else 0,
                "error": str(e)
            }

    def cleanup_audio_file(self, audio_path: Path) -> bool:
        """清理（刪除）音檔

        Args:
            audio_path: 音檔路徑

        Returns:
            是否刪除成功
        """
        try:
            if audio_path.exists():
                audio_path.unlink()
                print(f"🗑️ 已刪除音檔：{audio_path.name}")
                return True
            return False
        except Exception as e:
            print(f"⚠️ 刪除音檔失敗：{e}")
            return False

    def detect_silence(
        self,
        audio_path: Path,
        min_silence_len: int = 1000,
        silence_thresh: int = -40
    ) -> list[Tuple[int, int]]:
        """檢測音檔中的靜音片段

        Args:
            audio_path: 音檔路徑
            min_silence_len: 最小靜音長度（毫秒）
            silence_thresh: 靜音閾值（dB）

        Returns:
            靜音片段列表 [(start_ms, end_ms), ...]
        """
        from pydub.silence import detect_nonsilent

        audio = AudioSegment.from_file(audio_path)

        # 檢測非靜音片段
        nonsilent_ranges = detect_nonsilent(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh
        )

        # 轉換為靜音片段
        silence_ranges = []
        prev_end = 0

        for start, end in nonsilent_ranges:
            if start > prev_end:
                silence_ranges.append((prev_end, start))
            prev_end = end

        # 最後一段
        if prev_end < len(audio):
            silence_ranges.append((prev_end, len(audio)))

        del audio
        return silence_ranges

    # ========== 私有輔助方法 ==========

    def _check_audio_format(
        self,
        audio_path: Path,
        expected_sample_rate: int,
        expected_channels: int
    ) -> bool:
        """檢查音檔格式是否符合預期

        Args:
            audio_path: 音檔路徑
            expected_sample_rate: 預期採樣率
            expected_channels: 預期聲道數

        Returns:
            是否符合預期
        """
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', str(audio_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                probe_data = json.loads(result.stdout)
                streams = probe_data.get('streams', [])

                audio_stream = next(
                    (s for s in streams if s.get('codec_type') == 'audio'),
                    None
                )

                if audio_stream:
                    sample_rate = int(audio_stream.get('sample_rate', 0))
                    channels = int(audio_stream.get('channels', 0))

                    return (
                        sample_rate == expected_sample_rate and
                        channels == expected_channels
                    )

        except Exception:
            pass

        return False

    # ========== 片段管理方法 ==========

    def clip_audio_regions(
        self,
        audio_path: Path,
        regions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """剪輯音檔中的多個區段

        Args:
            audio_path: 原始音檔路徑
            regions: 區段列表 [{"start": 10.5, "end": 25.3, "id": "xxx"}, ...]

        Returns:
            剪輯結果列表 [{"clip_id": "...", "filename": "...", "duration": 14.8}, ...]
        """
        # 載入音檔
        audio = AudioSegment.from_file(str(audio_path))

        clips = []
        for region in regions:
            start = region.get("start", 0)
            end = region.get("end", len(audio) / 1000.0)
            region_id = region.get("id", "")

            # 轉換為毫秒
            start_ms = int(start * 1000)
            end_ms = int(end * 1000)

            # 剪輯片段
            clip_segment = audio[start_ms:end_ms]

            # 生成唯一 ID
            clip_id = str(uuid.uuid4())
            timestamp = datetime.now(TZ_UTC8).strftime("%Y%m%d_%H%M%S")

            # 儲存為 MP3
            filename = f"clip_{timestamp}_{clip_id[:8]}.mp3"
            filepath = self.clips_dir / filename

            clip_segment.export(
                str(filepath),
                format="mp3",
                bitrate="192k"
            )

            # 計算實際時長
            duration = len(clip_segment) / 1000.0

            # 建立片段元數據
            clip_data = {
                "clip_id": clip_id,
                "filename": filename,
                "path": str(filepath),
                "duration": duration,
                "start": start,
                "end": end,
                "region_id": region_id,
                "created_at": datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")
            }

            # 儲存到記憶體
            with self.clips_lock:
                self.audio_clips[clip_id] = clip_data

            clips.append({
                "clip_id": clip_id,
                "filename": filename,
                "duration": duration
            })

            del clip_segment

        del audio
        return clips

    def merge_clips(
        self,
        clip_ids: List[str],
        mode: str = "different-files"
    ) -> Dict[str, Any]:
        """合併多個音檔片段

        Args:
            clip_ids: 片段 ID 列表
            mode: 合併模式
                - "different-files": 合併不同音檔（中間無間隔）
                - "same-file-clips": 合併同一音檔的片段（保持原始時間順序）

        Returns:
            合併結果 {"merged_id": "...", "filename": "...", "duration": 120.5}
        """
        # 取得所有片段
        with self.clips_lock:
            clips_to_merge = []
            for clip_id in clip_ids:
                if clip_id not in self.audio_clips:
                    raise ValueError(f"片段 {clip_id} 不存在")
                clips_to_merge.append(self.audio_clips[clip_id])

        # 如果是同一音檔的片段，按原始時間排序
        if mode == "same-file-clips":
            clips_to_merge.sort(key=lambda x: x.get("start", 0))

        # 合併音檔
        combined = AudioSegment.empty()

        for clip_data in clips_to_merge:
            filepath = Path(clip_data["path"])
            if not filepath.exists():
                raise FileNotFoundError(f"片段檔案不存在：{filepath}")

            clip_audio = AudioSegment.from_file(str(filepath))
            combined += clip_audio
            del clip_audio

        # 儲存合併結果
        merged_id = str(uuid.uuid4())
        timestamp = datetime.now(TZ_UTC8).strftime("%Y%m%d_%H%M%S")
        filename = f"merged_{timestamp}_{merged_id[:8]}.mp3"
        filepath = self.clips_dir / filename

        combined.export(
            str(filepath),
            format="mp3",
            bitrate="192k"
        )

        duration = len(combined) / 1000.0
        del combined

        # 儲存元數據
        merged_data = {
            "clip_id": merged_id,
            "filename": filename,
            "path": str(filepath),
            "duration": duration,
            "is_merged": True,
            "source_clips": clip_ids,
            "created_at": datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")
        }

        with self.clips_lock:
            self.audio_clips[merged_id] = merged_data

        return {
            "merged_id": merged_id,
            "filename": filename,
            "duration": duration
        }

    def get_clip(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """獲取片段資訊

        Args:
            clip_id: 片段 ID

        Returns:
            片段資訊或 None
        """
        with self.clips_lock:
            return self.audio_clips.get(clip_id)

    def cleanup_old_clips(self, max_age_hours: int = 24) -> int:
        """清理超過指定時間的音訊片段

        Args:
            max_age_hours: 最大保留時間（小時），預設 24 小時

        Returns:
            刪除的片段數量
        """
        cutoff_time = datetime.now(TZ_UTC8) - timedelta(hours=max_age_hours)

        deleted_count = 0
        with self.clips_lock:
            clips_to_delete = []

            for clip_id, clip_data in self.audio_clips.items():
                # 解析創建時間
                created_str = clip_data.get("created_at", "")
                try:
                    created_time = datetime.strptime(created_str, "%Y-%m-%d %H:%M:%S")
                    created_time = created_time.replace(tzinfo=TZ_UTC8)

                    if created_time < cutoff_time:
                        clips_to_delete.append(clip_id)
                except Exception:
                    continue

            # 刪除過期片段
            for clip_id in clips_to_delete:
                clip_data = self.audio_clips[clip_id]
                filepath = Path(clip_data["path"])

                if filepath.exists():
                    filepath.unlink()
                    print(f"🗑️ 已刪除過期片段：{filepath.name}")

                del self.audio_clips[clip_id]
                deleted_count += 1

        return deleted_count

    def convert_to_web_format(
        self,
        audio_path: Path,
        bitrate: str = "192k"
    ) -> Dict[str, Any]:
        """轉換音檔為瀏覽器相容的格式（MP3）

        Args:
            audio_path: 原始音檔路徑
            bitrate: 位元率（默認 192k）

        Returns:
            轉換結果 {"clip_id": "...", "filename": "...", "size_mb": 2.5}
        """
        # 載入音檔
        audio = AudioSegment.from_file(str(audio_path))

        # 生成輸出檔名
        clip_id = str(uuid.uuid4())
        output_filename = f"converted_{Path(audio_path).stem}.mp3"
        output_path = self.clips_dir / output_filename

        # 轉換為 MP3
        audio.export(
            str(output_path),
            format="mp3",
            bitrate=bitrate,
            parameters=["-q:a", "2"]  # 高品質
        )

        del audio

        # 取得檔案大小
        size_bytes = output_path.stat().st_size
        size_mb = round(size_bytes / 1024 / 1024, 2)

        # 儲存元數據
        clip_data = {
            "clip_id": clip_id,
            "filename": output_filename,
            "path": str(output_path),
            "original_filename": audio_path.name,
            "size_bytes": size_bytes,
            "size_mb": size_mb,
            "created_at": datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S")
        }

        with self.clips_lock:
            self.audio_clips[clip_id] = clip_data

        return {
            "clip_id": clip_id,
            "filename": output_filename,
            "size_mb": size_mb
        }
