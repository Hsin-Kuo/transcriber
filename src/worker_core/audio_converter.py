"""
音檔格式轉換工具

Worker 收到的音檔可能是任意格式（ALAC、AAC、WAV、FLAC 等），
統一轉為 MP3（128kbps, mono）以確保瀏覽器可播放並節省儲存空間。
pyannote 說話者辨識需要 WAV 格式，因此另提供 WAV 轉換。
"""

import json
import subprocess
from pathlib import Path


def convert_to_mp3(audio_path: Path) -> tuple[Path, bool]:
    """將音檔轉為 MP3（128kbps, mono）。

    Returns:
        (mp3_path, transcoded)
        transcoded=False：已是 MP3，僅重新命名
        transcoded=True：實際重新編碼，S3 需要更新
    """
    mp3_path = audio_path.with_suffix(".mp3")

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        probe = json.loads(result.stdout)
        codec = probe.get("streams", [{}])[0].get("codec_name", "")
    except Exception:
        codec = ""

    # 已是 MP3 codec，只需重新命名（若副檔名不同）
    if codec == "mp3":
        if audio_path != mp3_path:
            audio_path.rename(mp3_path)
        print("✅ 音檔已是 MP3 格式，無需轉碼")
        return mp3_path, False

    print(f"🔄 音檔格式 {codec or '未知'}，轉碼為 MP3 128kbps...")
    original_size = audio_path.stat().st_size / 1024 / 1024
    tmp_path = mp3_path.with_name(f"_tmp_{mp3_path.name}")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path),
             "-vn", "-acodec", "libmp3lame", "-b:a", "128k", "-ac", "1",
             "-f", "mp3", str(tmp_path)],
            check=True, capture_output=True, timeout=600,
        )
        if audio_path != mp3_path:
            audio_path.unlink()
        tmp_path.rename(mp3_path)
        new_size = mp3_path.stat().st_size / 1024 / 1024
        print(f"✅ MP3 轉碼完成: {original_size:.1f} MB → {new_size:.1f} MB")
        return mp3_path, True
    except Exception as e:
        print(f"⚠️ MP3 轉碼失敗: {e}，以原始格式繼續")
        if tmp_path.exists():
            tmp_path.unlink()
        # 重新命名讓後續流程統一拿到 .mp3 路徑
        if audio_path != mp3_path:
            audio_path.rename(mp3_path)
        return mp3_path, False


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
