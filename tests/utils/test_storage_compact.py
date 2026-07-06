"""storage.compact 單元測試（Compact audio；local-mode 走真檔案系統，boto3-free）。"""
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

from src.utils.storage import compact  # noqa: E402

VALID_ID = "12345678-1234-1234-1234-123456789abc"


class TestKeyAndTier:
    def test_audio_key_for_valid_tier(self):
        assert compact._audio_s3_key(VALID_ID, "pro") == f"uploads/pro/{VALID_ID}.mp3"

    def test_invalid_tier_rejected(self):
        # 防路徑注入：tier 白名單
        with pytest.raises(ValueError):
            compact._audio_s3_key(VALID_ID, "../secret")

    @pytest.mark.parametrize("path,expected", [
        (f"s3://b/uploads/free/{VALID_ID}.mp3", "free"),
        (f"s3://b/uploads/kept/{VALID_ID}.mp3", "kept"),
        (f"s3://b/uploads/bogus/{VALID_ID}.mp3", None),  # tier 不在白名單
        (f"/local/uploads/{VALID_ID}.mp3", None),         # 非 s3
        ("", None),
    ])
    def test_extract_tier_from_path(self, path, expected):
        assert compact.extract_tier_from_path(path) == expected


class TestPresignedUrlResponseHeaders:
    """AWS 模式下 presigned URL 必須覆寫 Response* 讓瀏覽器把回應當音檔處理，
    不能讓未來混入 bucket 的非 audio content-type 被當 HTML inline 解析。"""

    class _FakeS3:
        def __init__(self):
            self.last_params = None

        def generate_presigned_url(self, operation, Params, ExpiresIn):
            self.last_params = Params
            return "https://bucket.s3.amazonaws.com/fake?signed=1"

    def test_get_audio_presigned_url_overrides_response_headers(self, monkeypatch):
        monkeypatch.setattr(compact, "is_aws", lambda: True)
        fake_s3 = self._FakeS3()
        monkeypatch.setattr(compact, "get_s3", lambda: fake_s3)

        url = compact.get_audio_presigned_url(VALID_ID, tier="pro")

        assert url == "https://bucket.s3.amazonaws.com/fake?signed=1"
        assert fake_s3.last_params["ResponseContentType"] == "audio/mpeg"
        assert fake_s3.last_params["ResponseContentDisposition"] == "inline; filename=audio.mp3"

    def test_get_presigned_url_by_path_overrides_response_headers(self, monkeypatch):
        monkeypatch.setattr(compact, "is_aws", lambda: True)
        fake_s3 = self._FakeS3()
        monkeypatch.setattr(compact, "get_s3", lambda: fake_s3)

        url = compact.get_presigned_url_by_path(f"s3://bucket/uploads/free/{VALID_ID}.mp3")

        assert url is not None
        assert fake_s3.last_params["ResponseContentType"] == "audio/mpeg"
        assert fake_s3.last_params["ResponseContentDisposition"] == "inline; filename=audio.mp3"


class TestLocalModeRoundTrip:
    """is_aws() 預設 False（DEPLOY_ENV=local）→ 走真檔案系統。"""

    def test_save_then_exists_then_delete(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # uploads/ 建在 tmp，不污染 repo
        src = tmp_path / "input.mp3"
        src.write_bytes(b"ID3 audio")

        stored = compact.save_audio(VALID_ID, src, tier="free")
        assert stored == str(Path("uploads") / f"{VALID_ID}.mp3")
        assert not src.exists()                          # 已被 move
        assert compact.audio_exists(VALID_ID) is True
        assert compact.get_audio_local_path(VALID_ID) == Path("uploads") / f"{VALID_ID}.mp3"
        assert compact.get_audio_presigned_url(VALID_ID) is None  # local 無 presigned

        compact.delete_audio_by_path(stored)
        assert compact.audio_exists(VALID_ID) is False

    def test_delete_missing_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        compact.delete_audio(VALID_ID)                   # 不存在也不報錯
        compact.delete_audio_by_path("")                 # 空路徑直接 return
