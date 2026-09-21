"""TimestampRefiner 純邏輯（交界窗構造 + 保守寫回）——不碰模型/CUDA/uroman。

背景見 forced_alignment.py 檔頭：whisper word start 前漂 → 交界字黏錯邊，
POC 實證 MMS_FA 對齊可修（「会」76.21→76.75、「因为」84.89→85.69）。
"""
from src.services.utils.forced_alignment import (
    apply_refined_times,
    speaker_change_windows,
)


def _turn(s, e, spk):
    return {"start": s, "end": e, "speaker": spk}


def test_windows_at_speaker_changes_only():
    turns = [_turn(0, 10, "A"), _turn(10, 20, "A"), _turn(20, 30, "B")]
    # A→A 交接不算變換；A→B 在 20s → 窗 [18, 22]
    assert speaker_change_windows(turns) == [(18.0, 22.0)]


def test_nested_interjection_creates_merged_window():
    # B 疊在 A 內（8–9.4s）：start 與 end 都是變換點，且相近 → 合併成一個窗
    turns = [_turn(0, 20, "A"), _turn(8.0, 9.4, "B")]
    wins = speaker_change_windows(turns)
    assert len(wins) == 1
    a, b = wins[0]
    assert a <= 6.0 + 0.01 and b >= 11.4 - 0.01


def test_windows_clamped_at_zero_and_merged():
    turns = [_turn(0, 1, "A"), _turn(1, 2, "B"), _turn(2, 3, "A")]
    wins = speaker_change_windows(turns)
    assert wins[0][0] == 0.0            # 不出現負時間
    assert len(wins) == 1               # 相鄰變換點合併


def test_no_change_no_windows():
    assert speaker_change_windows([_turn(0, 5, "A")]) == []
    assert speaker_change_windows([_turn(0, 5, "A"), _turn(5, 9, "A")]) == []


def test_apply_refined_respects_max_shift():
    words = [{"start": 76.21, "end": 76.75, "word": "会"}]
    # 位移 0.54s（<1.0）→ 採用
    n = apply_refined_times(words, [(76.75, 76.91)])
    assert n == 1 and words[0]["start"] == 76.75
    # 位移 >1.0s → 拒絕
    words2 = [{"start": 10.0, "end": 10.5, "word": "字"}]
    n2 = apply_refined_times(words2, [(12.0, 12.3)])
    assert n2 == 0 and words2[0]["start"] == 10.0


def test_apply_refined_keeps_monotonic_order():
    words = [
        {"start": 5.0, "end": 5.5, "word": "一"},
        {"start": 5.5, "end": 6.0, "word": "二"},
    ]
    # 第二個字的修正值早於第一個字 → 被鉗到不早於前字 start
    n = apply_refined_times(words, [(5.2, 5.6), (4.9, 5.4)])
    assert n == 2
    assert words[1]["start"] >= words[0]["start"]
    assert words[1]["end"] > words[1]["start"]


def test_none_entries_leave_words_untouched():
    words = [{"start": 1.0, "end": 1.5, "word": "嗯"}]
    assert apply_refined_times(words, [None]) == 0
    assert words[0]["start"] == 1.0
