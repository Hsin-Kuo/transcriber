"""storage.handoff 單元測試（Handoff audio；local-mode 行為，boto3-free）。"""
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

from src.utils.storage import handoff  # noqa: E402

VALID_ID = "12345678-1234-1234-1234-123456789abc"


class TestExtAndKey:
    def test_key_for_valid_ext(self):
        assert handoff._handoff_s3_key(VALID_ID, "wav") == f"handoff/{VALID_ID}.wav"

    @pytest.mark.parametrize("bad", ["exe", "../x", "mp3.exe", ""])
    def test_invalid_ext_rejected(self, bad):
        # 防路徑注入：副檔名白名單
        with pytest.raises(ValueError):
            handoff._handoff_s3_key(VALID_ID, bad)


class TestLocalMode:
    """is_aws() 預設 False → handoff 多為 noop。"""

    def test_upload_is_noop_returns_local_path(self, tmp_path):
        src = tmp_path / "input.wav"
        src.write_bytes(b"RIFF....WAVE")
        assert handoff.upload_to_handoff(VALID_ID, src, "wav") == str(src)
        assert src.exists()  # local 模式不搬動

    def test_download_raises_in_local(self, tmp_path):
        with pytest.raises(RuntimeError):
            handoff.download_from_handoff(VALID_ID, "wav", tmp_path / "out.wav")

    def test_delete_is_noop(self):
        handoff.delete_handoff(VALID_ID, "wav")  # 不報錯

    def test_sweep_returns_zero(self):
        assert handoff.sweep_handoff_orphans() == 0
