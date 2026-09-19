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
