"""hybrid 覆蓋補轉的純函式測試:_find_uncovered_gaps / _merge_segments_by_start。

batched 是單溫度無 fallback，困難音段會整段掉；hybrid 對「未覆蓋的空洞」用 sequential
補轉。這兩個純函式負責「找空洞」與「依時序合併補轉段」，是補轉正確性的地基。
"""
from src.services.utils.whisper_processor import (
    _find_uncovered_gaps,
    _merge_segments_by_start,
)


def _seg(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


# ── _find_uncovered_gaps ─────────────────────────────────────────

def test_gap_between_segments():
    segs = [_seg(0, 10), _seg(12, 20)]
    # 10–12 的 2s 空洞 + 20–25 的尾端 5s 空洞
    assert _find_uncovered_gaps(segs, 25.0, min_gap=1.0) == [(10.0, 12.0), (20.0, 25.0)]


def test_min_gap_filters_small_holes():
    segs = [_seg(0, 10), _seg(12, 20)]
    # min_gap=3 → 2s 的洞被濾掉，只留尾端 5s
    assert _find_uncovered_gaps(segs, 25.0, min_gap=3.0) == [(20.0, 25.0)]


def test_leading_gap_detected():
    segs = [_seg(8.9, 20)]
    # 開頭 0–8.9 也是空洞（你的 1017 檔開頭就掉了 8.9s）
    gaps = _find_uncovered_gaps(segs, 30.0, min_gap=2.0)
    assert (0.0, 8.9) in gaps


def test_overlapping_segments_absorbed():
    # 重疊段不應產生假空洞
    segs = [_seg(0, 10), _seg(5, 15)]
    assert _find_uncovered_gaps(segs, 15.0, min_gap=1.0) == []


def test_full_coverage_no_gaps():
    segs = [_seg(0, 30)]
    assert _find_uncovered_gaps(segs, 30.0, min_gap=1.0) == []


def test_empty_or_zero_duration():
    assert _find_uncovered_gaps([], 30.0, min_gap=1.0) == [(0.0, 30.0)]
    assert _find_uncovered_gaps([_seg(0, 10)], 0.0, min_gap=1.0) == []


def test_zero_length_segments_ignored():
    # start==end 的退化段不算覆蓋
    segs = [_seg(5, 5), _seg(10, 20)]
    gaps = _find_uncovered_gaps(segs, 20.0, min_gap=2.0)
    assert (0.0, 10.0) in gaps


def test_real_1017_gap_at_speaker_transition():
    # 模擬實測:298.7 前有段、312.5 後有段,中間 12.4s 換講者掉段
    segs = [_seg(280, 298.7), _seg(312.5, 340)]
    gaps = _find_uncovered_gaps(segs, 340.0, min_gap=2.0)
    assert (298.7, 312.5) in gaps


# ── _merge_segments_by_start ─────────────────────────────────────

def test_merge_orders_by_start():
    base = [_seg(0, 10, "a"), _seg(12, 20, "c")]
    extra = [_seg(10, 12, "b")]
    merged = _merge_segments_by_start(base, extra)
    assert [s["text"] for s in merged] == ["a", "b", "c"]


def test_merge_preserves_all_fields():
    base = [{"start": 0, "end": 1, "text": "a", "words": ["w"]}]
    extra = [{"start": 2, "end": 3, "text": "b", "words": None}]
    merged = _merge_segments_by_start(base, extra)
    assert merged[0]["words"] == ["w"] and "words" in merged[1]


def test_merge_empty_extra_is_noop():
    base = [_seg(0, 10, "a")]
    assert _merge_segments_by_start(base, []) == base


def test_merge_full_text_join_in_time_order():
    # 合併後依序串接 → full_text 應為時序正確的句子(下游送 Gemini 的就是這個)
    base = [_seg(0, 5, "第一句"), _seg(10, 15, "第三句")]
    extra = [_seg(5, 10, "第二句")]
    merged = _merge_segments_by_start(base, extra)
    assert "".join(s["text"] for s in merged) == "第一句第二句第三句"
