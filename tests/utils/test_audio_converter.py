"""Compact audio 契約 + precise skip 測試。

對應 src/utils/audio_converter.py。每個測試生成一個 ffmpeg fixture 音檔，
然後驗證 skip predicate 是否如預期、re-encode 是否產出符合契約的輸出。

需要本機有 ffmpeg / ffprobe。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 讓 import src.* 鏈不炸（一致於 tests/utils/test_logger.py）
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.utils.audio_converter import (  # noqa: E402
    BITRATE_CAP,
    BITRATE_VBR_SLACK,
    SAMPLE_RATE_CAP,
    VALID_MP3_SAMPLE_RATES,
    _adaptive_target,
    _is_compact,
    _probe,
    convert_to_mp3,
    convert_to_wav,
)


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg / ffprobe 未安裝",
)


@pytest.fixture
def make_audio(tmp_path):
    """產生 ffmpeg 測試音檔 fixture。"""

    def _make(
        filename,
        *,
        codec="mp3",
        sample_rate=16000,
        channels=1,
        bit_rate=128_000,
        duration=1.0,
    ):
        out = tmp_path / filename
        if codec == "mp3":
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"sine=frequency=440:duration={duration}",
                "-acodec", "libmp3lame",
                "-b:a", str(bit_rate),
                "-ar", str(sample_rate),
                "-ac", str(channels),
                "-f", "mp3",
                str(out),
            ]
        elif codec == "wav":
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"sine=frequency=440:duration={duration}",
                "-ar", str(sample_rate),
                "-ac", str(channels),
                str(out),
            ]
        else:
            raise ValueError(f"unsupported codec: {codec}")
        subprocess.run(cmd, check=True, capture_output=True)
        return out

    return _make


# ── Skip predicate：5 個屬性的正/反測 ──────────────────────────


def test_skip_when_matches_contract(make_audio):
    """16kHz mono 128kbps MP3 是契約 sweet spot——必須 skip。"""
    path = make_audio("input.mp3")
    out, transcoded = convert_to_mp3(path)
    assert out == path
    assert transcoded is False


def test_skip_when_low_quality_already(make_audio):
    """8kHz mono 32kbps MP3 已經更小——絕對不可以 upsample 變大。"""
    path = make_audio("input.mp3", sample_rate=8000, bit_rate=32_000)
    out, transcoded = convert_to_mp3(path)
    assert transcoded is False, "低品質檔案被誤 re-encode（會讓檔案變大）"


def test_reencode_when_stereo(make_audio):
    """channels=2 必須 re-encode 成 mono。"""
    path = make_audio("input.mp3", channels=2)
    out, transcoded = convert_to_mp3(path)
    assert transcoded is True
    probe = _probe(out)
    assert probe["streams"][0]["channels"] == 1


def test_reencode_when_high_bitrate(make_audio):
    """bit_rate > 130k（cap + VBR slack）必須 re-encode 壓回 cap。"""
    path = make_audio("input.mp3", bit_rate=192_000)
    out, transcoded = convert_to_mp3(path)
    assert transcoded is True
    probe = _probe(out)
    assert int(probe["streams"][0]["bit_rate"]) <= BITRATE_VBR_SLACK


def test_skip_when_44k_mono_compact(make_audio):
    """44.1kHz mono 128kbps MP3 屬於合法 sample_rate 集合 → 必須 skip（枚舉寬鬆）。

    這是「Compact audio 不叫 Normalized」的核心 case：高 sample_rate 但其他屬性
    都符合，照樣 skip，永久檔保留原 sample_rate。
    """
    path = make_audio("input.mp3", sample_rate=44100)
    out, transcoded = convert_to_mp3(path)
    assert transcoded is False, "44.1kHz mono 128kbps MP3 被誤 re-encode（枚舉寬鬆破功）"


def test_reencode_when_wrong_container(make_audio):
    """WAV container（即使是 mono 16kHz）一定不過 predicate。"""
    path = make_audio("input.wav", codec="wav")
    out, transcoded = convert_to_mp3(path)
    assert transcoded is True
    assert out.suffix == ".mp3"
    probe = _probe(out)
    assert "mp3" in probe["format"]["format_name"].split(",")


def test_reencode_when_wav_disguised_as_mp3(make_audio, tmp_path):
    """歷史 bug：suffix=.mp3 但內容是 wav。Predicate 必須靠 ffprobe 不是副檔名。"""
    wav = make_audio("disguised.wav", codec="wav")
    fake_mp3 = tmp_path / "disguised.mp3"
    wav.rename(fake_mp3)

    out, transcoded = convert_to_mp3(fake_mp3)
    assert transcoded is True, "Predicate 被副檔名騙了（歷史 bug 回歸）"
    probe = _probe(out)
    assert probe["streams"][0]["codec_name"] == "mp3"


# ── 自適應 re-encode target ────────────────────────────────────


def test_adaptive_caps_sample_rate_down(make_audio):
    """22kHz stereo 64kbps → target sample_rate cap 到 16kHz、bit_rate 保留 64k。"""
    path = make_audio("input.mp3", sample_rate=22050, channels=2, bit_rate=64_000)
    out, transcoded = convert_to_mp3(path)
    assert transcoded is True
    probe = _probe(out)
    sr = int(probe["streams"][0]["sample_rate"])
    br = int(probe["streams"][0]["bit_rate"])
    assert sr == SAMPLE_RATE_CAP, "sample_rate 沒 cap 到 16kHz"
    # libmp3lame 對指定 bitrate 通常很準；給 10% slack
    assert br <= 72_000, f"bit_rate 被誤升 ({br})"


def test_adaptive_no_upsample_no_grow(make_audio):
    """8kHz stereo 32kbps → predicate fail (stereo)；target 不能 upsample / grow。

    這是 user 最痛的 case：低品質但 stereo 的小檔，如果用固定 16k 128k target
    re-encode 會變 4 倍大。自適應 target 必須保留 8kHz + 32kbps。
    """
    path = make_audio("input.mp3", sample_rate=8000, channels=2, bit_rate=32_000)
    out, transcoded = convert_to_mp3(path)
    assert transcoded is True
    probe = _probe(out)
    sr = int(probe["streams"][0]["sample_rate"])
    br = int(probe["streams"][0]["bit_rate"])
    assert sr == 8000, "sample_rate 被誤 upsample（變大檔案）"
    assert br <= 36_000, f"bit_rate 被誤升 ({br})（變大檔案）"


def test_adaptive_target_unit():
    """純單元測 _adaptive_target，不跑 ffmpeg。"""
    # 高 sample_rate → cap
    sr, br = _adaptive_target({"streams": [{"codec_type": "audio", "sample_rate": "44100", "bit_rate": "192000"}]})
    assert sr == SAMPLE_RATE_CAP
    assert br == BITRATE_CAP
    # 低 sample_rate → 保留
    sr, br = _adaptive_target({"streams": [{"codec_type": "audio", "sample_rate": "8000", "bit_rate": "32000"}]})
    assert sr == 8000
    assert br == 32_000
    # 邊緣 sample_rate (11025) → snap 到最大合法 ≤ cap 的 rate
    sr, _ = _adaptive_target({"streams": [{"codec_type": "audio", "sample_rate": "11025", "bit_rate": "64000"}]})
    assert sr == 11025
    # 缺失 probe → fallback cap
    assert _adaptive_target(None) == (SAMPLE_RATE_CAP, BITRATE_CAP)
    # 怪 rate (7891) → snap 到 ≤7891 沒有合法 rate → 取最低 8000
    sr, _ = _adaptive_target({"streams": [{"codec_type": "audio", "sample_rate": "7891", "bit_rate": "64000"}]})
    assert sr == VALID_MP3_SAMPLE_RATES[0]


# ── _is_compact 純單元測 ──────────────────────────────────────


def test_is_compact_rejects_none():
    assert _is_compact(None) is False


def test_is_compact_rejects_missing_audio_stream():
    assert _is_compact({"format": {"format_name": "mp3"}, "streams": []}) is False


def test_is_compact_rejects_extra_stream():
    """mp3 帶附圖（PNG video stream）→ re-encode 洗掉附圖。"""
    probe = {
        "format": {"format_name": "mp3"},
        "streams": [
            {"codec_type": "audio", "codec_name": "mp3", "sample_rate": "16000",
             "channels": 1, "bit_rate": "128000"},
            {"codec_type": "video", "codec_name": "png"},  # cover art
        ],
    }
    assert _is_compact(probe) is False


def test_is_compact_accepts_canonical():
    probe = {
        "format": {"format_name": "mp3"},
        "streams": [{
            "codec_type": "audio", "codec_name": "mp3",
            "sample_rate": "16000", "channels": 1, "bit_rate": "128000",
        }],
    }
    assert _is_compact(probe) is True


# ── convert_to_wav ────────────────────────────────────────────


def test_convert_to_wav_basic(make_audio, tmp_path):
    mp3 = make_audio("input.mp3")
    wav = tmp_path / "out.wav"
    out = convert_to_wav(mp3, wav)
    assert out == wav
    probe = _probe(wav)
    assert int(probe["streams"][0]["sample_rate"]) == 16000
    assert probe["streams"][0]["channels"] == 1


def test_convert_to_wav_fallback_on_failure(tmp_path):
    """壞掉的 input → 印警告、回 audio_path（讓上游決定）。"""
    bogus = tmp_path / "not_audio.mp3"
    bogus.write_bytes(b"this is not audio data")
    wav = tmp_path / "out.wav"
    out = convert_to_wav(bogus, wav)
    assert out == bogus  # fallback


# ── 錯誤路徑 ──────────────────────────────────────────────────


def test_convert_to_mp3_raises_on_garbage(tmp_path):
    """完全不是音檔 → predicate fail → ffmpeg 也失敗 → RuntimeError。"""
    bogus = tmp_path / "garbage.mp3"
    bogus.write_bytes(b"definitely not audio")
    with pytest.raises(RuntimeError) as exc_info:
        convert_to_mp3(bogus)
    assert getattr(exc_info.value, "error_code", None) == "INVALID_AUDIO"
