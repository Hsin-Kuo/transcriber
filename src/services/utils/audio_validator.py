"""上傳音檔驗證：副檔名白名單 + magic bytes 檢查。

防禦目標：
1. 拒絕非音檔副檔名（.exe / .sh / .html 等）
2. 拒絕假冒副檔名（.mp3 但內容是 PE / shell script）

ffmpeg 後續仍會驗證實際格式，這層是早期防線。
"""
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

# 允許的副檔名（小寫，含點）
ALLOWED_EXTENSIONS = frozenset({
    ".mp3", ".m4a", ".wav", ".ogg", ".oga", ".flac",
    ".aac", ".webm", ".mp4", ".opus", ".wma",
})

# Magic bytes 對應的音/視訊容器（offset, signature）
# 參考 https://www.garykessler.net/library/file_sigs.html
_MAGIC_SIGNATURES = (
    # ID3v2 標頭（常見於 mp3）
    (0, b"ID3"),
    # MP3 frame sync (MPEG1/2 Layer III) — 各種 bitrate / sampling rate
    (0, b"\xff\xfb"), (0, b"\xff\xf3"), (0, b"\xff\xf2"),
    (0, b"\xff\xfa"), (0, b"\xff\xe3"),
    # AAC ADTS
    (0, b"\xff\xf1"), (0, b"\xff\xf9"),
    # WAV (RIFF ... WAVE)
    (0, b"RIFF"),
    # OGG / Opus
    (0, b"OggS"),
    # FLAC
    (0, b"fLaC"),
    # MP4 / M4A — "ftyp" 在 offset 4
    (4, b"ftyp"),
    # WebM / Matroska EBML
    (0, b"\x1a\x45\xdf\xa3"),
    # AIFF
    (0, b"FORM"),
)


def validate_filename_extension(filename: Optional[str]) -> str:
    """驗證副檔名屬於白名單，回傳小寫安全副檔名（含點）。

    Raises HTTPException 400 if invalid.
    """
    if not filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "缺少檔名，無法驗證類型",
        )
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"不支援的檔案類型 '{suffix or '無副檔名'}'，僅接受：{allowed}",
        )
    return suffix


def validate_magic_bytes(file_path: Path) -> None:
    """讀取檔頭驗證 magic bytes 對應已知音/視訊格式。

    Raises HTTPException 400 if signature doesn't match any known audio format.
    """
    try:
        with file_path.open("rb") as f:
            header = f.read(16)
    except OSError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"無法讀取上傳檔案：{e}",
        )

    for offset, sig in _MAGIC_SIGNATURES:
        if header[offset:offset + len(sig)] == sig:
            return

    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "檔案內容與音檔格式不符（magic bytes 不匹配），疑似偽造副檔名",
    )
