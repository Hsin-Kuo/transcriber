"""_resegment_by_words：依字間停頓 / 長度把長 segment 切成碎片的測試。

batched(turbo)的 segment 以 VAD 語音塊為界會變超長，這個函式在 whisper 輸出當下
用 word timestamps 重切。用假 Word（只需 start/end/word）測，不依賴模型。
"""
from collections import namedtuple

from src.services.utils.whisper_processor import (
    _resegment_by_words,
    _apply_time_offset,
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
    # 切分輸出帶 words，且與輸入的 word 逐一對得上（供下游 word 級語者對齊使用）
    assert out[0]["words"] == [
        {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word} for w in left
    ]
    assert out[1]["words"] == [
        {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word} for w in right
    ]


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


def test_degenerate_words_fallback_to_segment_timing():
    # faster-whisper batched 長檔偶發：word 起點對、但 duration 塌縮（整段字擠在數毫秒內）。
    # 此時 word 範圍(0.003s) << segment 範圍(6.4s) → 應回退用 segment 級 [start,end]，
    # 不被壞 word 拖成數毫秒（否則下游句子切分會把整段話塞進極短時間）。
    degenerate = [W(433.618, 433.618, "字") for _ in range(40)]  # 40 字全擠在同一點
    segs = [{"start": 433.6, "end": 440.0, "text": "一整段正常長度的話", "words": degenerate}]
    out = _resegment_by_words(segs)
    assert len(out) == 1
    assert out[0]["start"] == 433.6 and out[0]["end"] == 440.0  # 用 segment 真實時間
    assert out[0]["text"] == "一整段正常長度的話"
    assert "words" not in out[0]  # degenerate fallback：下游以缺 words 為訊號


def test_normal_words_not_treated_as_degenerate():
    # 正常情況：word 涵蓋幾乎整個 segment → 不該誤判為退化、照常依停頓/長度切
    words = _evenly_spoken(10, start=0.0, dur=0.5, gap=0.0)  # 0.0–5.0
    segs = [{"start": 0.0, "end": 5.0, "text": "x", "words": words}]
    out = _resegment_by_words(segs)
    # word_span(5.0) 不 < seg_span(5.0)*0.5 → 不回退；結果非單一段原樣（有被正常處理）
    assert out and out[0]["start"] == 0.0


def test_constants_are_sane():
    assert 0 < RESEG_GAP_THRESHOLD_SEC < RESEG_MIN_SEGMENT_SEC < RESEG_MAX_SEGMENT_SEC


# ── _apply_time_offset（chunk offset 校正，供 word 時間戳同步平移）────────────

def test_apply_time_offset_without_words():
    seg = {"start": 1.0, "end": 2.0, "text": "x"}
    out = _apply_time_offset(seg, 10.0)
    assert out == {"start": 11.0, "end": 12.0, "text": "x"}


def test_apply_time_offset_shifts_words_too():
    seg = {
        "start": 1.0, "end": 2.0, "text": "ab",
        "words": [{"start": 1.0, "end": 1.5, "word": "a"}, {"start": 1.5, "end": 2.0, "word": "b"}],
    }
    out = _apply_time_offset(seg, 10.0)
    assert out["start"] == 11.0 and out["end"] == 12.0
    assert out["words"] == [
        {"start": 11.0, "end": 11.5, "word": "a"},
        {"start": 11.5, "end": 12.0, "word": "b"},
    ]
