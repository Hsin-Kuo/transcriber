"""SpeakerNamesUpdate schema 測試（XSS audit TODO-5）。

PUT /transcriptions/{task_id}/speaker-names 的 body 原本是裸 dict，長度/數量/
型別完全不限。這裡只驗證長度/數量/型別邊界——不做 HTML sanitize，講者名稱
允許合法含 `<` `>` 等字元（逃逸是輸出端責任）。
"""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.models.transcription import SpeakerNamesUpdate  # noqa: E402


class TestValidPayloads:
    def test_typical_mapping(self):
        model = SpeakerNamesUpdate.model_validate({"SPEAKER_00": "張三", "SPEAKER_01": "李四"})
        assert model.root == {"SPEAKER_00": "張三", "SPEAKER_01": "李四"}

    def test_empty_mapping_allowed(self):
        model = SpeakerNamesUpdate.model_validate({})
        assert model.root == {}

    def test_name_may_contain_angle_brackets(self):
        # 逃逸是輸出端責任，這裡不做 sanitize/strip
        model = SpeakerNamesUpdate.model_validate({"SPEAKER_00": "王<小>明"})
        assert model.root["SPEAKER_00"] == "王<小>明"

    def test_boundary_lengths_pass(self):
        model = SpeakerNamesUpdate.model_validate({"K" * 50: "N" * 100})
        assert len(next(iter(model.root))) == 50

    def test_exactly_50_speakers_allowed(self):
        payload = {f"SPEAKER_{i:02d}": "name" for i in range(50)}
        model = SpeakerNamesUpdate.model_validate(payload)
        assert len(model.root) == 50


class TestInvalidPayloads:
    def test_too_many_speakers_rejected(self):
        payload = {f"SPEAKER_{i:03d}": "name" for i in range(51)}
        with pytest.raises(ValidationError, match="Too many speakers"):
            SpeakerNamesUpdate.model_validate(payload)

    def test_key_too_long_rejected(self):
        with pytest.raises(ValidationError, match="Speaker key too long"):
            SpeakerNamesUpdate.model_validate({"K" * 51: "name"})

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError, match="Speaker name too long"):
            SpeakerNamesUpdate.model_validate({"SPEAKER_00": "N" * 500})

    def test_non_string_value_rejected(self):
        with pytest.raises(ValidationError):
            SpeakerNamesUpdate.model_validate({"SPEAKER_00": 12345})

    def test_non_dict_body_rejected(self):
        with pytest.raises(ValidationError):
            SpeakerNamesUpdate.model_validate(["SPEAKER_00", "張三"])
