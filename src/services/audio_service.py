"""
AudioService - 音檔處理服務
職責：
- 音檔合併
- 音檔元資料處理
"""

from pathlib import Path
from typing import List, Optional
import subprocess
from datetime import datetime
import pytz
import json
import uuid


TZ_UTC8 = pytz.timezone('Asia/Taipei')


class AudioService:
    """音檔處理服務

    提供音檔合併相關的業務邏輯
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """初始化 AudioService

        Args:
            output_dir: 輸出目錄（可選）
        """
        self.output_dir = output_dir or Path("output")
        self.output_dir.mkdir(exist_ok=True, parents=True)

    def merge_audio_files(
        self,
        audio_paths: List[Path],
        output_path: Optional[Path] = None
    ) -> Path:
        """合併多個音檔

        使用 ffmpeg concat filter 進行高效合併
        固定輸出格式：MP3 (16kHz, mono, 192kbps)

        Args:
            audio_paths: 音檔路徑列表（按順序）
            output_path: 輸出路徑（可選）

        Returns:
            合併後的音檔路徑
        """
        if not audio_paths:
            raise ValueError("音檔列表不能為空或為 None")

        if len(audio_paths) == 1:
            return audio_paths[0]

        # 生成輸出檔名（固定MP3格式）
        # 使用 UUID 確保多用戶並發時不會衝突
        if output_path is None:
            unique_id = str(uuid.uuid4())[:12]  # 使用 12 位 UUID
            timestamp = datetime.now(TZ_UTC8).strftime("%Y%m%d_%H%M%S")
            output_path = self.output_dir / f"merged_{timestamp}_{unique_id}.mp3"

        # 使用 ffmpeg concat filter（支援不同格式）
        try:
            # 構建 filter_complex 參數
            inputs = []
            filter_parts = []

            for idx, path in enumerate(audio_paths):
                inputs.extend(['-i', str(path)])
                filter_parts.append(f'[{idx}:a]')

            # 合併所有音軌
            filter_complex = f"{''.join(filter_parts)}concat=n={len(audio_paths)}:v=0:a=1[outa]"

            # 執行 ffmpeg（固定MP3參數）
            cmd = [
                'ffmpeg', '-y',
                *inputs,
                '-filter_complex', filter_complex,
                '-map', '[outa]',
                '-acodec', 'libmp3lame',
                '-b:a', '192k',
                '-ar', '16000',  # 16kHz（Whisper 推薦）
                '-ac', '1',      # 單聲道
                str(output_path)
            ]

            print(f"🔧 執行 ffmpeg 合併：{len(audio_paths)} 個檔案")

            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=600  # 10分鐘超時
            )

            print(f"✅ 合併成功：{output_path}")
            return output_path

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise RuntimeError(f"音檔合併失敗：{error_msg}")

        except subprocess.TimeoutExpired:
            raise RuntimeError("音檔合併超時（超過10分鐘）")

    def get_audio_duration(self, audio_path: Path) -> int:
        """獲取音檔時長（毫秒）

        使用 ffprobe（快速，不載入記憶體）

        Args:
            audio_path: 音檔路徑

        Returns:
            音檔時長（毫秒）
        """
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', str(audio_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                probe_data = json.loads(result.stdout)
                duration_seconds = float(probe_data['format']['duration'])
                return int(duration_seconds * 1000)
            else:
                return 0

        except Exception as e:
            print(f"⚠️ 獲取音檔時長失敗：{e}")
            return 0
