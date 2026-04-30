"""
音檔格式轉換工具

Worker 收到的音檔可能是任意格式（ALAC、AAC、WAV、FLAC 等），
統一轉為 MP3（128kbps, mono）以確保瀏覽器可播放並節省儲存空間。
pyannote 說話者辨識需要 WAV 格式，因此另提供 WAV 轉換。
"""

import json
import subprocess
from pathlib import Path


def convert_to_mp3(audio_path: Path) -> Path:
    """將音檔轉為 MP3（128kbps, mono）。若已是 MP3 則直接回傳。

    轉碼成功後刪除原始檔，並以相同路徑名返回 .mp3 路徑。
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        probe = json.loads(result.stdout)
        codec = probe.get("streams", [{}])[0].get("codec_name", "")

        if codec == "mp3":
            print("✅ 音檔已是 MP3 格式，無需轉碼")
            return audio_path

        print(f"🔄 音檔格式 {codec}，轉碼為 MP3 128kbps...")
        original_size = audio_path.stat().st_size / 1024 / 1024
        mp3_path = audio_path.with_suffix(".mp3.tmp")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-vn", "-acodec", "libmp3lame",
             "-b:a", "128k", "-ac", "1", str(mp3_path)],
            check=True, capture_output=True, timeout=600,
        )
        mp3_path.rename(audio_path)
        new_size = audio_path.stat().st_size / 1024 / 1024
        print(f"✅ MP3 轉碼完成: {original_size:.1f} MB → {new_size:.1f} MB")
        return audio_path
    except Exception as e:
        print(f"⚠️ MP3 轉碼失敗: {e}，使用原始檔案")
        return audio_path


def convert_to_wav(audio_path: Path, wav_path: Path) -> Path:
    """將音檔轉為 16kHz mono WAV（pyannote 說話者辨識需要）。"""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path)],
            check=True, capture_output=True,
        )
        print(f"🔄 已轉換為 WAV: {wav_path}")
        return wav_path
    except Exception as e:
        print(f"⚠️ WAV 轉換失敗: {e}，使用原始音檔")
        return audio_path
