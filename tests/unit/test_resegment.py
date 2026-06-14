"""_resegment_by_words：依字間停頓 / 長度把長 segment 切成碎片的測試。

batched(turbo)的 segment 以 VAD 語音塊為界會變超長，這個函式在 whisper 輸出當下
用 word timestamps 重切。用假 Word（只需 start/end/word）測，不依賴模型。
"""
from collections import namedtuple

from src.services.utils.whisper_processor import (
    _resegment_by_words,
    RESEG_MAX_SEGMENT_SEC,
    RESEG_GAP_THRESHOLD_SEC,
    RESEG_MIN_SEGMENT_SEC,
)

W = namedtuple("W", "start end word")


def _evenly_spoken(n, start=0.0, dur=0.4, gap=0.0, char="字"):
    """連續 n 個字，每字 dur 秒、字間 gap 秒（gap=0 表無停頓）。"""
    words, t = [], start
    for _ in range(n):
        words.append(W(round(t, 3), round(t + dur, 3), char))
        t += dur + gap
    return words


def test_words_none_keeps_segment_unchanged():
    segs = [{"start": 1.0, "end": 5.0, "text": "原樣", "words": None}]
    assert _resegment_by_words(segs) == [{"start": 1.0, "end": 5.0, "text": "原樣"}]


def test_long_continuous_run_split_by_max_length():
    # 25 秒連續無停頓 → 應被 max(10s) 切成多段，每段不超過上限
    words = _evenly_spoken(50, dur=0.5, gap=0.0)  # 50 字 ×0.5s = 25s
    out = _resegment_by_words([{"start": 0, "end": 25, "text": "x", "words": words}])
    assert len(out) >= 3
    for s in out:
        assert s["end"] - s["start"] <= RESEG_MAX_SEGMENT_SEC + 0.5  # 容一字誤差


def test_split_at_pause():
    # 兩段各 ~2 秒，中間 1 秒停頓（> gap 門檻，且兩側都 ≥ min）→ 切成 2 段
    left = _evenly_spoken(5, start=0.0, dur=0.4, gap=0.0)        # 0.0–2.0
    right = _evenly_spoken(5, start=3.0, dur=0.4, gap=0.0)       # 3.0–5.0（停頓 1.0s）
    out = _resegment_by_words([{"start": 0, "end": 5, "text": "x", "words": left + right}])
    assert len(out) == 2
    assert out[0]["end"] <= 2.01 and out[1]["start"] >= 2.99


def test_small_gap_below_min_not_split():
    # 第 2 字後有停頓，但累積還沒到 min(1.5s) → 不切（避免碎段）
    words = [
        W(0.0, 0.4, "甲"),
        W(0.4, 0.8, "乙"),          # 累積 0.8s < 1.5
        W(1.6, 2.0, "丙"),          # 與前字停頓 0.8s > gap，但前面累積未達 min
        W(2.0, 2.4, "丁"),
    ]
    out = _resegment_by_words([{"start": 0, "end": 2.4, "text": "x", "words": words}])
    assert len(out) == 1
    assert out[0]["text"] == "甲乙丙丁"


def test_empty_text_words_skipped():
    words = [W(0.0, 0.4, "  "), W(0.4, 0.8, "")]  # 全空白/空 → flush 後 text 空 → 跳過
    out = _resegment_by_words([{"start": 0, "end": 0.8, "text": "x", "words": words}])
    assert out == []


def test_constants_are_sane():
    assert 0 < RESEG_GAP_THRESHOLD_SEC < RESEG_MIN_SEGMENT_SEC < RESEG_MAX_SEGMENT_SEC
