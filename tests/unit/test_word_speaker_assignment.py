"""word 級語者對齊核心的測試：_pick_speaker_for_span / _smooth_isolated_word_speakers /
assign_speakers_word_level。

比照 tests/unit/test_resegment.py 的假資料風格：不依賴模型，words 用 plain dict
（{start, end, word}，即 _resegment_by_words 的輸出格式）。
"""
from src.services.utils.whisper_processor import (
    WhisperProcessor,
    _pick_speaker_for_span,
    _smooth_isolated_word_speakers,
    assign_speakers_word_level,
)


def _w(start, end, word):
    return {"start": start, "end": end, "word": word}


def _turn(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


def test_cross_speaker_split_at_word_boundary():
    # 單 segment 4 個字，turns A[0,2]/B[2,4] → 依語者變換點切成兩子段
    words = [_w(0, 1, "A"), _w(1, 2, "B"), _w(2, 3, "C"), _w(3, 4, "D")]
    turns = [_turn(0, 2, "SPEAKER_00"), _turn(2, 4, "SPEAKER_01")]
    segs = [{"start": 0, "end": 4, "text": "ABCD", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 2
    assert out[0] == {"start": 0, "end": 2, "text": "AB", "speaker": "SPEAKER_00"}
    assert out[1] == {"start": 2, "end": 4, "text": "CD", "speaker": "SPEAKER_01"}


def test_pick_speaker_no_overlap_falls_back_to_nearest_turn():
    # word 落在兩個 turn 之間的間隙（[1,3]）→ 依中點距最近的 turn 歸屬
    turns = [_turn(0, 1, "A"), _turn(3, 4, "B")]
    # 中點 1.55，距 A 的 end(1) 為 0.55；距 B 的 start(3) 為 1.45 → 歸 A
    assert _pick_speaker_for_span(1.5, 1.6, turns) == "A"
    # 中點 2.6，距 A 為 1.6；距 B 為 0.4 → 歸 B
    assert _pick_speaker_for_span(2.5, 2.7, turns) == "B"


def test_pick_speaker_empty_turns_returns_none():
    assert _pick_speaker_for_span(0, 1, []) is None


def test_smoothing_merges_isolated_single_word_run():
    # A A B A A → 孤立單字 B 前後皆為 A → 歸併成 A
    assert _smooth_isolated_word_speakers(["A", "A", "B", "A", "A"]) == ["A", "A", "A", "A", "A"]


def test_smoothing_leaves_run_of_two_untouched():
    # A B B A → B 的 run 長度為 2，不是孤立單字 → 不動
    assert _smooth_isolated_word_speakers(["A", "B", "B", "A"]) == ["A", "B", "B", "A"]


def test_smoothing_alternating_pattern_converges():
    # A B A B A → 孤立 run 逐一併入鄰居後收斂為單一語者，
    # 不得出現「正確的字被改錯、孤立 run 仍殘留」的中間態（如 A A B A A）
    assert _smooth_isolated_word_speakers(["A", "B", "A", "B", "A"]) == ["A"] * 5


def test_smoothing_leaves_boundary_runs_untouched():
    # 首尾孤立 run 沒有雙側鄰居 → 不動
    assert _smooth_isolated_word_speakers(["B", "A", "A", "B"]) == ["B", "A", "A", "B"]


def test_chinese_words_join_without_space():
    words = [_w(0, 1, "你"), _w(1, 2, "好")]
    turns = [_turn(0, 2, "SPEAKER_00")]
    segs = [{"start": 0, "end": 2, "text": "你好", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 1
    assert out[0]["text"] == "你好"


def test_english_words_join_with_leading_space_stripped():
    # faster-whisper 英文 word 自帶前導空格；"".join(...).strip() 即正確拼接
    words = [_w(0, 1, " Hello"), _w(1, 2, " world")]
    turns = [_turn(0, 2, "SPEAKER_00")]
    segs = [{"start": 0, "end": 2, "text": "Hello world", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 1
    assert out[0]["text"] == "Hello world"


def test_segment_without_words_falls_back_to_segment_level_overlap():
    # passthrough/degenerate 段（無 words）→ 整段 _pick_speaker_for_span(seg.start, seg.end)
    segs = [{"start": 0, "end": 2, "text": "hi"}]
    turns = [_turn(0, 0.5, "A"), _turn(0.5, 2, "B")]  # B 與整段重疊較多(1.5s > 0.5s)

    out = assign_speakers_word_level(segs, turns)

    assert out == [{"start": 0, "end": 2, "text": "hi", "speaker": "B"}]


def test_empty_diar_turns_returns_segments_as_is():
    # 空 diar → 原樣回傳（不加 speaker）；words 的剝除由 orchestrator 出口單點處理
    words = [_w(0, 1, "hi")]
    segs = [{"start": 0, "end": 1, "text": "hi", "words": words}]

    out = assign_speakers_word_level(segs, [])

    assert out == segs
    assert "speaker" not in out[0]


# ── 段落模式 merge（_merge_transcription_with_diarization）─────────────────
# model=None：這兩個方法不碰 self.model，無需真的載入 Whisper。

def test_paragraph_mode_empty_diar_returns_plain_text():
    processor = WhisperProcessor(None)
    segments = [{"start": 0, "end": 1, "text": "hello"}, {"start": 1, "end": 2, "text": "world"}]

    result = processor._merge_transcription_with_diarization(segments, [])

    assert result == "hello world"


def test_paragraph_mode_output_format_matches_existing_convention():
    # [SPEAKER_XX] 前綴 + \n\n 分行、同語者連續合併——格式與改動前完全一致
    processor = WhisperProcessor(None)
    words = [_w(0, 1, "Hi"), _w(1, 2, " there"), _w(2, 3, " bye"), _w(3, 4, " now")]
    turns = [_turn(0, 2, "SPEAKER_00"), _turn(2, 4, "SPEAKER_01")]
    segments = [{"start": 0, "end": 4, "text": "Hi there bye now", "words": words}]

    result = processor._merge_transcription_with_diarization(segments, turns)

    assert result == "[SPEAKER_00] Hi there\n\n[SPEAKER_01] bye now"
