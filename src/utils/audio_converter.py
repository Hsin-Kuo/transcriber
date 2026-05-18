"""音檔格式轉換 — Compact audio 契約的唯一實作。

對應 CONTEXT.md「Compact audio」。Web Server 跟 Worker 共用同一份。

實作策略：precise skip + 自適應 re-encode。ffprobe 抓 5 個屬性，全 match
才 skip ffmpeg；任一不 match 就 re-encode，target 依輸入自適應（不 upsample、
不 grow）。歷史上踩過兩次半成品 skip（只看 suffix / 只看 codec）導致永久檔
違反契約——詳見 CONTEXT.md callout。
"""
import json
import subprocess
from pathlib import Path
from typing import Optional


# 標準 MP3 支援的 sample rate（MPEG-1/2/2.5 全部合法值）
VALID_MP3_SAMPLE_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)

# Compact audio 契約上限
SAMPLE_RATE_CAP = 16000
BITRATE_CAP = 128_000
# VBR 平均 bitrate 跟 nominal 設定有誤差；給 ~2% slack 避免邊緣 case 被反覆 re-encode
BITRATE_VBR_SLACK = 130_000


def convert_to_mp3(audio_path: Path) -> tuple[Path, bool]:
    """把音檔轉成 Compact audio MP3，回傳 (mp3_path, transcoded)。

    transcoded=False：輸入已滿足契約，僅必要時改副檔名
    transcoded=True ：實際 re-encode 過

    Raises:
        RuntimeError(error_code="INVALID_AUDIO")：ffmpeg 轉換失敗
    """
    mp3_path = audio_path.with_suffix(".mp3")
    probe = _probe(audio_path)

    if _is_compact(probe):
        if audio_path != mp3_path:
            audio_path.rename(mp3_path)
        print("✅ 音檔已符合 Compact audio 契約，無需重編")
        return mp3_path, False

    sample_rate, bit_rate = _adaptive_target(probe)
    print(
        f"🔄 音檔不符契約，re-encode 到 mono {sample_rate}Hz {bit_rate // 1000}kbps MP3"
    )

    tmp_path = mp3_path.with_name(f"_tmp_{mp3_path.name}")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(audio_path),
                "-vn",
                "-acodec", "libmp3lame",
                "-b:a", str(bit_rate),
                "-ar", str(sample_rate),
                "-ac", "1",
                "-f", "mp3",
                str(tmp_path),
            ],
            check=True, capture_output=True, timeout=600,
        )
        if audio_path != mp3_path and audio_path.exists():
            audio_path.unlink()
        tmp_path.rename(mp3_path)
        return mp3_path, True
    except subprocess.CalledProcessError as e:
        if tmp_path.exists():
            tmp_path.unlink()
        stderr_tail = (
            e.stderr.decode(errors="replace")[-300:]
            if isinstance(e.stderr, (bytes, bytearray))
            else ""
        )
        err = RuntimeError(
            f"音檔格式轉換失敗，檔案可能損壞或受 DRM 保護。ffmpeg: {stderr_tail}"
        )
        err.error_code = "INVALID_AUDIO"
        raise err from e
    except subprocess.TimeoutExpired as e:
        if tmp_path.exists():
            tmp_path.unlink()
        err = RuntimeError("音檔格式轉換超時（> 600s）")
        err.error_code = "INVALID_AUDIO"
        raise err from e


def convert_to_wav(audio_path: Path, wav_path: Path) -> Path:
    """把音檔轉成 16kHz mono WAV（pyannote 說話者辨識的 canonical 輸入）。

    失敗時印警告並 fallback 回傳原 audio_path（讓上游決定如何處理）。
    """
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path)],
            check=True, capture_output=True,
        )
        print(f"🔄 已轉換為 WAV: {wav_path}")
        return wav_path
    except subprocess.CalledProcessError as e:
        stderr_tail = (
            e.stderr.decode(errors="replace")[-300:]
            if isinstance(e.stderr, (bytes, bytearray))
            else ""
        )
        print(f"⚠️ WAV 轉換失敗，回退使用原始音檔。ffmpeg: {stderr_tail}")
        return audio_path


# ── 內部 helpers ───────────────────────────────────────────────


def _probe(audio_path: Path) -> Optional[dict]:
    """ffprobe → JSON dict；任何失敗回 None（caller 視為「不符契約」）。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-show_format",
                str(audio_path),
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return json.loads(result.stdout) if result.stdout else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def _is_compact(probe: Optional[dict]) -> bool:
    """檢查輸入是否已滿足 Compact audio 契約全部 5 屬性。

    任一不符立即回 False——必須 5 個全過才能 skip ffmpeg。
    """
    if not probe:
        return False

    # 1. container = mp3
    # ffprobe 對 mp3 container 回 "mp3"；曖昧容器（mp4/m4a 等）會回逗號分隔
    format_name = (probe.get("format") or {}).get("format_name", "")
    if "mp3" not in format_name.split(","):
        return False

    # 2. 必須有「恰好一條」audio stream（多 stream / 含 video 都拒）
    audio_streams = [
        s for s in probe.get("streams", [])
        if s.get("codec_type") == "audio"
    ]
    if len(audio_streams) != 1:
        return False
    if len(probe.get("streams", [])) != 1:
        # 有 audio 但同時有其他（video / data / 附圖）→ re-encode 把雜訊洗掉
        return False
    s = audio_streams[0]

    # 3. codec = mp3
    if s.get("codec_name") != "mp3":
        return False

    # 4. channels = 1
    if s.get("channels") != 1:
        return False

    # 5. sample_rate ∈ 合法 MP3 sample rate 集合（注意 ffprobe 回 string）
    try:
        sample_rate = int(s.get("sample_rate", 0))
    except (TypeError, ValueError):
        return False
    if sample_rate not in VALID_MP3_SAMPLE_RATES:
        return False

    # 6. bit_rate ≤ cap（含 VBR slack）；ffprobe 回 string
    try:
        bit_rate = int(s.get("bit_rate", 0))
    except (TypeError, ValueError):
        return False
    if bit_rate <= 0 or bit_rate > BITRATE_VBR_SLACK:
        return False

    return True


def _adaptive_target(probe: Optional[dict]) -> tuple[int, int]:
    """根據輸入挑 re-encode target，保證不 upsample、不 grow。

    Returns:
        (sample_rate, bit_rate)
    """
    if not probe:
        return SAMPLE_RATE_CAP, BITRATE_CAP

    audio_streams = [
        s for s in probe.get("streams", [])
        if s.get("codec_type") == "audio"
    ]
    if not audio_streams:
        return SAMPLE_RATE_CAP, BITRATE_CAP
    s = audio_streams[0]

    # sample_rate：取 min(input, cap)，再 snap 到 ≤ 該值的最大合法 MP3 rate
    try:
        input_sr = int(s.get("sample_rate", 0))
    except (TypeError, ValueError):
        input_sr = 0
    if input_sr <= 0:
        target_sr = SAMPLE_RATE_CAP
    else:
        cap = min(input_sr, SAMPLE_RATE_CAP)
        valid = [r for r in VALID_MP3_SAMPLE_RATES if r <= cap]
        target_sr = max(valid) if valid else VALID_MP3_SAMPLE_RATES[0]

    # bit_rate：取 min(input, cap)；輸入無 bit_rate 資訊（PCM/WAV 等）就用 cap
    try:
        input_br = int(s.get("bit_rate", 0))
    except (TypeError, ValueError):
        input_br = 0
    target_br = min(input_br, BITRATE_CAP) if input_br > 0 else BITRATE_CAP

    return target_sr, target_br
