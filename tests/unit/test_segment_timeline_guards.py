"""segments 時間軸塌陷防護（2026-09 staging 事故回歸測試）。

事故機制（diar debug dump + opus 診斷實證）：
1. 餵食者：LLM 局部吞內容 → difflib 對齊打平 → align 舊碼把「全文剩餘」塞進
   一小段時窗（text_utils align 的 fallback 分支）
2. 產生器：split 依字數比例在母段時窗內插值 → 巨量文字 × 毫秒時窗 = 數十段
   同 start / 零長度「句子」
3. 惡化器：#407 全形轉換讓句末切點暴增（半形 '.' 原本不在切句集合）

修法：align 打平區給空字串不吞尾、split 加密度守門、'.' 帶歧義判斷入切句集、
落 DB 前哨兵指標。本檔鎖死修法行為。
"""
from collections import Counter

from src.utils.text_utils import (
    align_segments_to_punctuated_text,
    is_ambiguous_period,
    segments_timeline_quality,
    split_segments_at_sentence_punctuation,
)


def _mk(n, chars=8, dur=1.5, short_idx=None, short_dur=0.05):
    segs, t = [], 0.0
    for i in range(n):
        d = short_dur if i == short_idx else dur
        body = chr(0x4E00 + i) * chars  # 每段不同字，避免 difflib 誤配
        segs.append({"start": round(t, 3), "end": round(t + d, 3),
                     "text": body, "speaker": "SPEAKER_00"})
        t += d
    return segs


def _punctuated(segs, drop=(), mark="。"):
    """模擬 LLM 輸出：逐段加句末標點；drop = LLM 吃掉的段落 index。"""
    return "".join(s["text"] + mark for i, s in enumerate(segs) if i not in drop)


def _stats(out):
    c = Counter(round(s["start"], 3) for s in out)
    return {
        "n": len(out),
        "max_same_start": max(c.values()),
        "zero_len": sum(1 for s in out if round(s["end"] - s["start"], 3) <= 0),
    }


# ── Fix 1：align 打平區不准吞掉全文剩餘 ────────────────────────────────────

def test_align_tied_positions_do_not_swallow_remainder():
    """LLM 吞掉第 10 段 → 打平區非末段給空字串，內容歸打平區最後一段（有界）。"""
    segs = _mk(200, short_idx=10)
    aligned = align_segments_to_punctuated_text(segs, _punctuated(segs, drop={10}))

    # 舊行為：aligned[10] 拿到 >1000 字的全文剩餘。新行為：有界。
    assert len(aligned[10]["text"]) < 30, f"打平區文字必須有界: {len(aligned[10]['text'])}字"
    assert len(aligned[11]["text"]) == 9  # 後續正常段不受影響（8字+句號）
    # 內容不遺失：所有段文字串起來 == 全文
    assert sum(len(s["text"]) for s in aligned) >= 199 * 9


def test_align_last_segment_still_takes_true_remainder():
    """真·最後一段拿剩餘文字的既有行為不變。"""
    segs = _mk(5)
    aligned = align_segments_to_punctuated_text(segs, _punctuated(segs))
    assert aligned[-1]["text"].endswith("。")
    assert all(s["text"] for s in aligned)


# ── Fix 2：split 密度守門 ─────────────────────────────────────────────────

def test_split_refuses_text_time_mismatch():
    """巨量文字 × 毫秒時窗 → 不切、保留母段（舊行為：切成 60 段毫秒句）。"""
    seg = {"start": 1623.0, "end": 1623.6, "speaker": "SPEAKER_01",
           "text": "".join(chr(0x4E00 + i) * 12 + "。" for i in range(60))}
    out = split_segments_at_sentence_punctuation([seg])
    assert len(out) == 1 and out[0] == seg


def test_split_normal_segment_still_splits():
    """正常密度（~7 字/秒）的多句段照常切分。"""
    seg = {"start": 10.0, "end": 16.0, "speaker": "A",
           "text": "今天天氣很好。我們出去走走。回來再吃飯。"}
    out = split_segments_at_sentence_punctuation([seg])
    assert len(out) == 3
    assert out[0]["start"] == 10.0 and out[-1]["end"] == 16.0
    assert all(round(s["end"] - s["start"], 3) > 0 for s in out)


# ── Fix 1+2 端到端：事故情境不再塌陷 ─────────────────────────────────────

def test_llm_content_drop_no_longer_collapses_pipeline():
    segs = _mk(200, short_idx=10)
    out = split_segments_at_sentence_punctuation(
        align_segments_to_punctuated_text(segs, _punctuated(segs, drop={10}))
    )
    st = _stats(out)
    assert st["zero_len"] == 0, f"不得有零長度段: {st}"
    assert st["max_same_start"] <= 2, f"不得同瞬間堆疊: {st}"


# ── Fix 3：半形 '.' 入切句集（帶歧義判斷） ────────────────────────────────

def test_halfwidth_period_splits_english_sentences():
    seg = {"start": 0.0, "end": 8.0, "speaker": "A",
           "text": "Hello world. How are you. Fine thanks."}
    out = split_segments_at_sentence_punctuation([seg])
    assert len(out) == 3


def test_decimal_and_abbreviation_do_not_split():
    assert is_ambiguous_period("rate is 3.5 ok", 9) is True
    assert is_ambiguous_period("see e.g. this", 5) is True
    seg = {"start": 0.0, "end": 5.0, "speaker": "A", "text": "比率是 3.5 跟 2.7 左右"}
    out = split_segments_at_sentence_punctuation([seg])
    assert len(out) == 1, "小數點不得被當句末切開"


# ── Fix 4：哨兵指標 ───────────────────────────────────────────────────────

def test_timeline_quality_metrics():
    healthy = [{"start": float(i), "end": i + 1.0} for i in range(10)]
    q = segments_timeline_quality(healthy)
    assert q == {"total": 10, "max_same_start": 1, "zero_length": 0}

    collapsed = [{"start": 100.0, "end": 100.0} for _ in range(15)]
    q2 = segments_timeline_quality(collapsed)
    assert q2["max_same_start"] == 15 and q2["zero_length"] == 15

    assert segments_timeline_quality([]) == {
        "total": 0, "max_same_start": 0, "zero_length": 0
    }
