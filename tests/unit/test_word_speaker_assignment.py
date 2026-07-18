"""word 級語者對齊核心的測試：_pick_speaker_for_span / Viterbi DP / assign_speakers_word_level。

比照 tests/unit/test_resegment.py 的假資料風格：不依賴模型，words 用 plain dict
（{start, end, word}，即 _resegment_by_words 的輸出格式）。
"""
from src.services.utils.whisper_processor import (
    WhisperProcessor,
    _pick_speaker_for_span,
    _pick_speaker_indexed,
    _build_turn_index,
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


# ── proximity tiebreak（真實 staging 案例：83.8s 附近「我也」誤分）───────────

def test_proximity_breaks_exact_overlap_tie_in_favor_of_short_centered_turn():
    # 真實案例數字：長 turn A 尾端與短 turn B（幾乎以 word 為中心）同時完整罩住
    # word「我也」，重疊秒數精確平手（0.480s vs 0.480s）。
    # 嚴格 `>` 比較下先迭代的 A 會贏 → 誤分；proximity 應該讓證據更強的 B 勝出。
    turns = [
        _turn(79.230, 84.427, "SPEAKER_00"),  # A：長 turn，word 落在尾端
        _turn(83.583, 84.393, "SPEAKER_02"),  # B：短 turn，幾乎以 word 為中心
    ]
    assert _pick_speaker_for_span(83.800, 84.280, turns) == "SPEAKER_02"


def test_proximity_does_not_flip_clear_overlap_fraction_difference():
    # X 重疊比例 0.8、Y 重疊比例 0.5（差 0.3 > 0.2）；Y 雖然以 span 為正中心
    # （proximity=1.0，優於 X 的 0.75），但 PROXIMITY_WEIGHT=0.1 不足以蓋過
    # 0.3 的重疊比例差距——X 仍須勝出，否則 proximity 會蓋過真正的重疊證據。
    span = (0.0, 1.0)
    turn_x = _turn(0.0, 0.8, "X")   # overlap=0.8 → fraction=0.8；proximity=0.75
    turn_y = _turn(0.25, 0.75, "Y")  # overlap=0.5 → fraction=0.5；proximity=1.0（span 正中心）
    assert _pick_speaker_for_span(*span, [turn_x, turn_y]) == "X"


# ── Viterbi DP 行為（取代舊的孤立單字 smoothing）────────────────────────────

def test_viterbi_flips_tie_at_speaker_handover_point():
    # 真實案例數字（staging 音檔 83.8s「我也」）：前文 word 屬 00、
    # 「我也」重疊精確平手但 proximity 偏 02、後文 words 屬 02（換手點）。
    # DP 只需一次換手（且發生在 0.56s 停頓處、成本打折）→ 我也判給 02。
    turns = [
        _turn(79.230, 84.427, "SPEAKER_00"),  # 前語者長 turn
        _turn(83.583, 84.393, "SPEAKER_02"),  # 插話短 turn（以「我也」為中心）
        _turn(84.427, 90.266, "SPEAKER_02"),  # 後語者主 turn
    ]
    words = [
        _w(82.960, 83.240, "臉"),    # 00 獨占
        _w(83.800, 84.280, "我也"),  # 平手（0.480 vs 0.480），proximity 偏 02
        _w(84.280, 84.580, "常"),
        _w(84.580, 84.780, "會"),    # 02 主 turn 內
    ]
    segs = [{"start": 82.960, "end": 84.780, "text": "臉我也常會", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert [(s["speaker"], s["text"]) for s in out] == [
        ("SPEAKER_00", "臉"),
        ("SPEAKER_02", "我也常會"),
    ]


def test_viterbi_keeps_context_speaker_for_mid_run_backchannel_tie():
    # 中段搭腔：前後文皆屬 A（長 turn），中間 word 被 nested 短 turn B 同時罩住、
    # 重疊平手且 proximity 偏 B——但 B 只是搭腔證據，前後文一致性（兩次換手成本）
    # 應讓該字留給 A，不得翻盤。
    turns = [
        _turn(0.0, 10.0, "A"),   # 主 turn
        _turn(4.0, 5.0, "B"),    # nested 搭腔短 turn
    ]
    words = [
        _w(1.0, 1.4, "w1"),   # A 獨占
        _w(4.2, 4.8, "w2"),   # A/B 皆完整罩住（平手），proximity 偏 B（B 中心 4.5 = word 中心）
        _w(6.0, 6.5, "w3"),   # A 獨占
    ]
    segs = [{"start": 1.0, "end": 6.5, "text": "w1w2w3", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 1
    assert out[0]["speaker"] == "A"


def test_viterbi_suppresses_isolated_weak_flip():
    # 原 smoothing 功能：A A B A A 型孤立單字雜訊（B 靠弱優勢贏 per-word，非強證據）
    # → 兩次換手成本 0.6 遠大於 emission 差 → DP 全判 A。
    turns = [
        _turn(0.0, 10.0, "A"),
        _turn(2.9, 4.1, "B"),   # nested，讓中間 word 的 per-word 分數以微小差距偏 B
    ]
    words = [_w(1, 2, "u"), _w(2, 3, "v"), _w(3, 4, "x"), _w(4, 5, "y"), _w(5, 6, "z")]
    segs = [{"start": 1, "end": 6, "text": "uvxyz", "words": words}]

    # 前置確認：中間 word 單獨判會給 B（弱優勢），DP 才有東西可壓
    assert _pick_speaker_for_span(3, 4, turns) == "B"

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 1
    assert out[0]["speaker"] == "A"


def test_viterbi_preserves_strong_evidence_interjection():
    # 強證據插話：中間 word 完全落在 B turn 內、A 零重疊（emission 差 ≈1.1 > 2×SWITCH_PENALTY）
    # → 即使 words 幾乎連續（無停頓折扣），DP 仍保留 A→B→A 換手。
    turns = [
        _turn(0.0, 3.0, "A"),
        _turn(3.0, 4.0, "B"),
        _turn(4.0, 7.0, "A"),
    ]
    words = [
        _w(2.5, 3.0, "w1"),   # A 獨占
        _w(3.1, 3.9, "w2"),   # B 獨占（A 兩個 turn 皆零重疊）
        _w(4.0, 4.5, "w3"),   # A 獨占
    ]
    segs = [{"start": 2.5, "end": 4.5, "text": "w1w2w3", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert [(s["speaker"], s["text"]) for s in out] == [
        ("A", "w1"), ("B", "w2"), ("A", "w3"),
    ]


def test_viterbi_prefers_switching_at_pause():
    # 邊界近平手（w2 被 A/B 皆罩住、emission 微偏 B）：
    # - w2→w3 有 ≥0.3s 停頓 → 換手成本打折，DP 把換手推遲到停頓處（w2 留給 A）
    # - 對照組：w3 貼緊 w2（無停頓）→ 兩個換手點成本相同，emission 決定，換手提前到 w2
    turns = [
        _turn(0.0, 4.0, "A"),
        _turn(3.4, 4.4, "B"),
    ]
    w1 = _w(3.0, 3.3, "w1")    # A 獨占
    w2 = _w(3.55, 3.85, "w2")  # A/B 皆完整罩住，emission 微偏 B（B 中心 3.9 較近）

    # 有停頓：w2→w3 gap 0.35 ≥ SWITCH_GAP_RELIEF_SEC → 換手發生在 gap 處
    w3_gapped = _w(4.2, 4.5, "w3")
    out = assign_speakers_word_level(
        [{"start": 3.0, "end": 4.5, "text": "w1w2w3", "words": [w1, w2, w3_gapped]}], turns
    )
    assert [(s["speaker"], s["text"]) for s in out] == [("A", "w1w2"), ("B", "w3")]

    # 無停頓（對照組）：w2→w3 gap 0.1 → 全額成本，換手提前到 emission 較高的 w2
    w3_contig = _w(3.95, 4.25, "w3")
    out = assign_speakers_word_level(
        [{"start": 3.0, "end": 4.25, "text": "w1w2w3", "words": [w1, w2, w3_contig]}], turns
    )
    assert [(s["speaker"], s["text"]) for s in out] == [("A", "w1"), ("B", "w2w3")]


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


# ── 索引窗口正確性：bisect 索引版 vs 暴力全掃版 ─────────────────────────
# _pick_speaker_indexed 只掃 bisect 找到的窗口內 turns；用一個獨立實作的暴力版
# （對全部 turns 評分，不做任何窗口裁剪）逐 span 比對，證明窗口裁剪沒有漏算。

def _brute_force_pick_speaker(start, end, turns):
    """暴力對照版：對「全部」turns 評分，不做 bisect 窗口裁剪（獨立重寫評分公式，
    不 import 生產的 PROXIMITY_WEIGHT / _turn_score，避免和被測程式碼共用同一段邏輯）。
    """
    if not turns:
        return None

    best_speaker = None
    best_score = 0.0
    for turn in turns:
        overlap = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
        if overlap <= 0.0:
            continue
        span_len = max(end - start, 1e-6)
        overlap_fraction = overlap / span_len
        turn_len = turn["end"] - turn["start"]
        if turn_len <= 0:
            proximity = 0.0
        else:
            span_mid = (start + end) / 2.0
            turn_mid = (turn["start"] + turn["end"]) / 2.0
            proximity = max(0.0, 1 - abs(span_mid - turn_mid) / (turn_len / 2.0))
        score = overlap_fraction + 0.1 * proximity
        if score > best_score:
            best_score = score
            best_speaker = turn["speaker"]

    if best_speaker is not None:
        return best_speaker

    midpoint = (start + end) / 2.0

    def _distance(turn):
        if midpoint < turn["start"]:
            return turn["start"] - midpoint
        if midpoint > turn["end"]:
            return midpoint - turn["end"]
        return 0.0

    return min(turns, key=_distance)["speaker"]


def test_indexed_window_matches_brute_force_across_overlapping_and_nested_turns():
    # 6 個 turns：含互相重疊（S0/S1、S2/S4）、含長 turn 完整罩住短 turn 的 nested case（S2 罩住 S3）
    turns = [
        _turn(0, 5, "S0"),
        _turn(4, 9.5, "S1"),    # 與 S0 重疊 [4,5]
        _turn(8, 20, "S2"),     # 長 turn，與 S1 重疊 [8,9.5]
        _turn(12, 13, "S3"),    # 被 S2 完整罩住的短 turn（nested）
        _turn(18, 25, "S4"),    # 與 S2 重疊 [18,20]
        _turn(24, 30, "S5"),    # 與 S4 重疊 [24,25]
    ]
    sorted_turns, starts, prefix_max_end = _build_turn_index(turns)

    spans = [
        (0.0, 1.0),      # 只在 S0 內
        (4.0, 5.0),      # S0/S1 重疊區
        (4.5, 5.5),      # S0/S1 重疊區，偏移
        (8.0, 9.0),      # S1/S2 重疊區（S1 尾端 vs S2 開頭）
        (8.5, 9.2),      # 同上，偏移
        (12.0, 13.0),    # 恰為 nested 短 turn S3 本身
        (12.2, 12.8),    # 被 S2 與 S3 同時罩住
        (11.9, 13.1),    # 跨出 S3 邊界，仍被 S2 罩住
        (18.0, 20.0),    # S2/S4 重疊區全段
        (19.0, 19.5),    # S2/S4 重疊區，偏移
        (23.0, 24.5),    # 跨 S4 尾端與 S5 開頭前
        (24.0, 25.0),    # S4/S5 重疊區
        (26.0, 27.0),    # 只在 S5 內
        (30.5, 31.0),    # 零重疊 fallback（在所有 turns 之後）
    ]

    for start, end in spans:
        indexed = _pick_speaker_indexed(start, end, sorted_turns, starts, prefix_max_end)
        brute = _brute_force_pick_speaker(start, end, turns)
        assert indexed == brute, f"span=({start},{end}) indexed={indexed} brute={brute}"
