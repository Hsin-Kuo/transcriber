"""_filter_hallucination_segments：丟棄 Whisper 字幕/頻道 boilerplate 幻覺。

移除 zh initial_prompt 後，靜音/雜訊段偶發的字幕 credit 幻覺（如「字幕由 Amara.org
社群提供」）由這層 deny_list 後處理擋掉。重點同時驗「該丟的丟」與「正常句不誤刪」。
"""
from src.services.utils.whisper_processor import _filter_hallucination_segments


def _seg(text, start=0.0, end=1.0):
    return {"start": start, "end": end, "text": text}


def _texts(segments):
    return [s["text"] for s in segments]


# ── 該丟：字幕/頻道 boilerplate 幻覺 ──────────────────────────────
def test_drops_amara_credit():
    segs = [_seg("中文字幕由Amara.org社群提供。")]
    assert _filter_hallucination_segments(segs) == []


def test_drops_amara_with_inserted_spaces():
    # Whisper 偶爾在 CJK 間插空格 → 正規化後仍須命中
    segs = [_seg("字幕由 Amara.org 社区提供")]
    assert _filter_hallucination_segments(segs) == []


def test_drops_subtitle_volunteer_credit():
    segs = [_seg("字幕由志願者提供")]
    assert _filter_hallucination_segments(segs) == []


def test_drops_chinese_subtitle_volunteer():
    segs = [_seg("中文字幕志願者")]
    assert _filter_hallucination_segments(segs) == []


def test_drops_song_credit():
    segs = [_seg("詞曲 李宗盛")]
    assert _filter_hallucination_segments(segs) == []


def test_keeps_song_credit_word_mid_sentence():
    # 「詞曲」未在段首 → 不誤刪真實討論
    segs = [_seg("這首歌的詞曲都是李宗盛寫的")]
    assert _filter_hallucination_segments(segs) == segs


def test_drops_channel_promo():
    segs = [_seg("請不吝點贊、訂閱、轉發、打賞")]
    assert _filter_hallucination_segments(segs) == []


def test_drops_mingjing_promo():
    segs = [_seg("明鏡需要您的支持")]
    assert _filter_hallucination_segments(segs) == []


# ── 不可誤刪：含相近字詞的正常語句 ───────────────────────────────
def test_keeps_real_sentence_with_overlapping_words():
    segs = [
        _seg("我們今天要討論社群提供的回饋意見"),
        _seg("這個字幕做得很好"),
        _seg("謝謝大家今天的參與"),
        _seg("請大家多多支持我們的活動"),
    ]
    assert _filter_hallucination_segments(segs) == segs


# ── 混合：只丟幻覺、保留真實段、順序不變 ─────────────────────────
def test_mixed_drops_only_hallucination_preserves_order():
    segs = [
        _seg("今天天氣很好", 0, 1),
        _seg("中文字幕由Amara.org社群提供。", 1, 2),
        _seg("我們開始吧", 2, 3),
    ]
    out = _filter_hallucination_segments(segs)
    assert _texts(out) == ["今天天氣很好", "我們開始吧"]


def test_empty_input():
    assert _filter_hallucination_segments([]) == []
