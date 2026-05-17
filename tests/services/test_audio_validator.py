"""上傳音檔白名單 + magic bytes 測試（B8）。"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.utils.audio_validator import (  # noqa: E402
    ALLOWED_EXTENSIONS,
    validate_filename_extension,
    validate_magic_bytes,
)


class TestValidateExtension:
    @pytest.mark.parametrize("filename,expected_ext", [
        ("song.mp3", ".mp3"),
        ("Recording.M4A", ".m4a"),       # 大小寫
        ("a.b.c.flac", ".flac"),         # 多點檔名
        ("空白名.wav", ".wav"),           # unicode 檔名
    ])
    def test_valid_passes(self, filename, expected_ext):
        assert validate_filename_extension(filename) == expected_ext

    @pytest.mark.parametrize("filename", [
        "evil.exe",
        "shell.sh",
        "page.html",
        "noext",
        "",
        None,
        "../../etc/passwd",      # path traversal
        "a.mp3.exe",             # 雙副檔名
        ".bashrc",
    ])
    def test_invalid_rejected(self, filename):
        with pytest.raises(HTTPException) as exc:
            validate_filename_extension(filename)
        assert exc.value.status_code == 400

    def test_allowed_set_covers_common_audio(self):
        # 確保關鍵副檔名都在白名單，避免被誤刪
        for must_have in (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".webm"):
            assert must_have in ALLOWED_EXTENSIONS


class TestValidateMagicBytes:
    @pytest.mark.parametrize("header_bytes,label", [
        (b"ID3\x04\x00\x00\x00\x00" + b"\x00" * 50, "ID3v2 (mp3)"),
        (b"\xff\xfb" + b"\x00" * 50, "MPEG frame sync (mp3)"),
        (b"RIFF\x00\x00\x00\x00WAVE", "WAV"),
        (b"OggS\x00\x02" + b"\x00" * 20, "OGG"),
        (b"fLaC" + b"\x00" * 20, "FLAC"),
        (b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 20, "MP4/M4A"),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * 20, "WebM"),
    ])
    def test_real_audio_headers_pass(self, header_bytes, label, tmp_path):
        f = tmp_path / "audio.bin"
        f.write_bytes(header_bytes)
        validate_magic_bytes(f)  # 不應 raise

    @pytest.mark.parametrize("payload,label", [
        (b"#!/bin/bash\necho pwned", "shell script"),
        (b"<html><script>alert(1)</script></html>", "html"),
        (b"MZ\x90\x00" + b"\x00" * 50, "PE/Windows executable"),
        (b"\x7fELF" + b"\x00" * 50, "ELF binary"),
        (b"random text with no audio header", "plain text"),
    ])
    def test_fake_audio_rejected(self, payload, label, tmp_path):
        f = tmp_path / "fake.mp3"
        f.write_bytes(payload)
        with pytest.raises(HTTPException) as exc:
            validate_magic_bytes(f)
        assert exc.value.status_code == 400

    def test_unreadable_file_raises_400(self, tmp_path):
        nonexistent = tmp_path / "does_not_exist.mp3"
        with pytest.raises(HTTPException) as exc:
            validate_magic_bytes(nonexistent)
        assert exc.value.status_code == 400
