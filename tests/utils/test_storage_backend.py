"""storage.backend 單元測試（local / S3 切換核心；boto3-free）。"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.storage import backend  # noqa: E402

VALID_ID = "12345678-1234-1234-1234-123456789abc"


class TestValidateTaskId:
    def test_valid_uuid_passes(self):
        backend.validate_task_id(VALID_ID)  # no raise

    @pytest.mark.parametrize("bad", ["", "../etc/passwd", "not-a-uuid", "12345678-1234-1234-1234-12345678"])
    def test_invalid_rejected(self, bad):
        with pytest.raises(ValueError):
            backend.validate_task_id(bad)


class TestParseS3Key:
    def test_extracts_key(self):
        assert backend.parse_s3_key(f"s3://my-bucket/uploads/free/{VALID_ID}.mp3") == f"uploads/free/{VALID_ID}.mp3"

    @pytest.mark.parametrize("uri", ["", None, "/local/path.mp3", "s3://only-bucket"])
    def test_non_s3_or_keyless_returns_none(self, uri):
        assert backend.parse_s3_key(uri) is None


class TestDetectContentType:
    def _write(self, tmp_path, name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return p

    def test_id3_mp3(self, tmp_path):
        assert backend.detect_content_type(self._write(tmp_path, "a.bin", b"ID3" + b"\x00" * 9)) == "audio/mpeg"

    def test_riff_wave(self, tmp_path):
        assert backend.detect_content_type(self._write(tmp_path, "a.bin", b"RIFF" + b"\x00" * 4 + b"WAVE")) == "audio/wav"

    def test_ftyp_mp4(self, tmp_path):
        assert backend.detect_content_type(self._write(tmp_path, "a.bin", b"\x00\x00\x00\x18ftypM4A ")) == "audio/mp4"

    def test_unknown_falls_back_to_suffix(self, tmp_path):
        assert backend.detect_content_type(self._write(tmp_path, "a.flac", b"xxxxxxxxxxxx")) == "audio/flac"


class TestValidateAwsConfig:
    def test_local_mode_is_noop(self, monkeypatch):
        monkeypatch.setattr(backend, "DEPLOY_ENV", "local")
        backend.validate_aws_config()  # no raise

    def test_aws_mode_missing_vars_raises(self, monkeypatch):
        monkeypatch.setattr(backend, "DEPLOY_ENV", "aws")
        monkeypatch.setattr(backend, "S3_BUCKET", "")
        monkeypatch.delenv("SQS_QUEUE_URL", raising=False)
        with pytest.raises(RuntimeError) as ei:
            backend.validate_aws_config()
        assert "S3_BUCKET" in str(ei.value) and "SQS_QUEUE_URL" in str(ei.value)
