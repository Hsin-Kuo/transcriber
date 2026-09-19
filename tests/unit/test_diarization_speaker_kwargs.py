"""講者人數 → pyannote pipeline kwargs 的轉換（單一來源 _build_speaker_kwargs）。

語意變更（2026-09-19 使用者回報 2 女 1 男被辨識成 2 人）：人數 = 確切人數
（num_speakers=N 強制簇數），不再是上限（min=1, max=N）。max 只是上限時
pipeline 可自行輸出更少人，同性別相近聲音常被聚成一簇。
"""
from src.services.utils.diarization_processor import DiarizationProcessor

build = DiarizationProcessor._build_speaker_kwargs


def test_count_forces_exact_cluster_count():
    assert build(3) == {"num_speakers": 3}


def test_empty_means_auto_detect():
    assert build(None) == {}


def test_out_of_range_falls_back_to_auto():
    # 與 HTTP 層白名單一致（2-10）；越界一律回自動偵測
    assert build(1) == {}
    assert build(11) == {}


def test_boundary_counts_accepted():
    assert build(2) == {"num_speakers": 2}
    assert build(10) == {"num_speakers": 10}


# ── pyannote 4.x 對接（waveform 餵入 + 新輸出 API）────────────────────────────

class _FakeTurn:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _FakeOutput:
    """模擬 4.x 的輸出物件：speaker_diarization 迭代出 (turn, speaker) 二元組。"""
    def __init__(self, pairs):
        self.speaker_diarization = pairs


def test_collect_segments_from_4x_output():
    out = _FakeOutput([
        (_FakeTurn(0.0, 5.2), "SPEAKER_00"),
        (_FakeTurn(5.2, 9.0), "SPEAKER_01"),
    ])
    segs = DiarizationProcessor._collect_segments(out)
    assert segs == [
        {"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"},
        {"start": 5.2, "end": 9.0, "speaker": "SPEAKER_01"},
    ]


def test_load_waveform_shape_and_rate(tmp_path):
    """waveform dict 是繞過 torchcodec 的關鍵——驗證形狀 (channel, time) 與取樣率。"""
    import numpy as np
    import soundfile as sf

    wav = tmp_path / "t.wav"
    sf.write(wav, np.zeros(16000, dtype="float32"), 16000)

    audio = DiarizationProcessor._load_waveform(wav)
    assert audio["sample_rate"] == 16000
    assert tuple(audio["waveform"].shape) == (1, 16000)
    assert str(audio["waveform"].dtype) == "torch.float32"
