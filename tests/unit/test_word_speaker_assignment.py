"""word 級語者對齊核心的測試：_pick_speaker_for_span / Viterbi DP / assign_speakers_word_level。

比照 tests/unit/test_resegment.py 的假資料風格：不依賴模型，words 用 plain dict
（{start, end, word}，即 _resegment_by_words 的輸出格式）。
"""
from src.services.utils.whisper_processor import (
    WhisperProcessor,
    _build_turn_index,
    _build_units,
    _is_latin_glue,
    _pick_speaker_for_span,
    _pick_speaker_indexed,
    _word_speaker_candidates,
    assign_speakers_word_level,
)


def _w(start, end, word):
    return {"start": start, "end": end, "word": word}


def _turn(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


def test_cross_speaker_split_at_word_boundary():
    # 單 segment 4 個字，turns A[0,2]/B[2,4] → 依語者變換點切成兩子段。
    # 注意：token 用 CJK——連續無空格的拉丁 token 在新語意下屬同一英文字
    # （會被 _build_units 黏成一單位共用 speaker），不適合當跨語者切分素材。
    words = [_w(0, 1, "甲"), _w(1, 2, "乙"), _w(2, 3, "丙"), _w(3, 4, "丁")]
    turns = [_turn(0, 2, "SPEAKER_00"), _turn(2, 4, "SPEAKER_01")]
    segs = [{"start": 0, "end": 4, "text": "甲乙丙丁", "words": words}]

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 2
    assert out[0] == {"start": 0, "end": 2, "text": "甲乙", "speaker": "SPEAKER_00"}
    assert out[1] == {"start": 2, "end": 4, "text": "丙丁", "speaker": "SPEAKER_01"}


def test_pick_speaker_no_overlap_falls_back_to_nearest_turn():
    # word 落在兩個 turn 之間的間隙（[1,3]）→ 依中點距最近的 turn 歸屬
    turns = [_turn(0, 1, "A"), _turn(3, 4, "B")]
    # 中點 1.55，距 A 的 end(1) 為 0.55；距 B 的 start(3) 為 1.45 → 歸 A
    assert _pick_speaker_for_span(1.5, 1.6, turns) == "A"
    # 中點 2.6，距 A 為 1.6；距 B 為 0.4 → 歸 B
    assert _pick_speaker_for_span(2.5, 2.7, turns) == "B"


def test_pick_speaker_empty_turns_returns_none():
    assert _pick_speaker_for_span(0, 1, []) is None


# ── 近平手 tie-break（真實 staging 案例：83.8s 附近「我也」誤分）──────────────

def test_near_tie_broken_in_favor_of_freshly_started_turn():
    # 真實案例數字：長 turn A 尾端與剛開口的短 turn B 同時完整罩住 word「我也」，
    # 重疊秒數精確平手（0.480s vs 0.480s）→ 近平手改用 turn-start affinity 決勝：
    # B 的 turn 起點（83.583）緊貼 word 起點（83.800）→ affinity 0.783；
    # A 早在 79.230 就開講 → affinity 0。剛開口的 B 證據較強，勝出。
    turns = [
        _turn(79.230, 84.427, "SPEAKER_00"),  # A：長 turn，word 落在尾端
        _turn(83.583, 84.393, "SPEAKER_02"),  # B：剛開口的插話短 turn
    ]
    assert _pick_speaker_for_span(83.800, 84.280, turns) == "SPEAKER_02"


def test_tiebreak_does_not_flip_clear_overlap_fraction_difference():
    # 重疊比例差距明顯（> NEAR_TIE_EPSILON）→ 不進近平手路徑，tie-break 用 proximity
    # 且權重 0.1 不足以蓋過重疊差——重疊較多的 X 仍須勝出。
    span = (0.0, 1.0)
    turn_x = _turn(0.0, 0.8, "X")   # overlap=0.8 → fraction=0.8；proximity=0.75
    turn_y = _turn(0.25, 0.75, "Y")  # overlap=0.5 → fraction=0.5；proximity=1.0（span 正中心）
    assert _pick_speaker_for_span(*span, [turn_x, turn_y]) == "X"


def test_no_words_long_segment_ignores_proximity_more_overlap_wins():
    # 無 words 的 passthrough 段沒有 reseg 6s 上限，proximity 翻盤窗隨 span 長度放大：
    # 6s span 下 X 重疊 4.0s(fraction 0.667)、Y 重疊 3.6s(0.6) 但貼 span 中心
    # (proximity 1.0)——若套 proximity，Y(0.7) 會贏 X(0.667+~0)。
    # 無 words 路徑只比重疊比例 → 重疊較多的 X 必勝。
    segs = [{"start": 0.0, "end": 6.0, "text": "long passthrough"}]
    turns = [
        _turn(0.0, 4.0, "X"),   # overlap 4.0s；turn 中心 2.0 離 span 中心 3.0 較遠
        _turn(1.2, 4.8, "Y"),   # overlap 3.6s；turn 中心 3.0 = span 中心
    ]

    out = assign_speakers_word_level(segs, turns)

    assert out == [{"start": 0.0, "end": 6.0, "text": "long passthrough", "speaker": "X"}]


# ── Word 尾端錨定（batched pipeline word start 前漂，staging「我也」實測數字）──

def test_word_tail_anchor_recovers_batched_drifted_word():
    # batched pipeline 實測：「我也」起點前漂 0.59s（83.800→83.210）、時長 0.48→1.06s，
    # 膨脹 span 稀釋與插話 turn 的重疊比例（1.0→0.636），近平手變一面倒 → 誤判前語者。
    # 尾端錨定只取 (end-0.6, end) 評分 → 恢復近平手，affinity+DP 判給後語者。
    turns = [
        _turn(79.225, 84.423, "SPEAKER_02"),  # 前語者長 turn
        _turn(83.596, 84.406, "SPEAKER_03"),  # 插話短 turn
        _turn(84.423, 90.278, "SPEAKER_03"),  # 後語者主 turn
    ]
    drifted = _w(83.210, 84.270, "我也")  # 起點前漂的 batched word（1.06s）
    words = [
        _w(82.930, 83.210, "臉"),   # 前文：02 獨占
        drifted,
        _w(84.270, 84.630, "常"),   # 後文起：03 較優
        _w(84.730, 84.850, "會"),   # 後文：03 主 turn 內
    ]
    segs = [{"start": 82.930, "end": 84.850, "text": "臉我也常會", "words": words}]

    # 對照斷言：不套尾端錨定的「原始膨脹 span」候選分數一面倒偏前語者
    # （前導音段稀釋插話 turn 重疊：fraction 1.0 vs ~0.64，差距 > NEAR_TIE_EPSILON
    # → 連近平手路徑都進不去），tie-break/DP 無從翻盤
    sorted_turns, starts, prefix_max_end = _build_turn_index(turns)
    raw = _word_speaker_candidates(
        drifted["start"], drifted["end"], sorted_turns, starts, prefix_max_end,
        anchor_tail=False,
    )
    assert raw["SPEAKER_02"] > raw["SPEAKER_03"] + 0.2

    out = assign_speakers_word_level(segs, turns)

    my_ye = next(s for s in out if "我也" in s["text"])
    assert my_ye["speaker"] == "SPEAKER_03"


def test_word_tail_anchor_leaves_short_words_untouched():
    # 時長 ≤ WORD_TAIL_ANCHOR_SEC 的正常短字：有效 span = 原始 span，行為完全不變
    # ——錨定開關開/關的候選分數表完全相同。
    turns = [
        _turn(79.230, 84.427, "SPEAKER_00"),
        _turn(83.583, 84.393, "SPEAKER_02"),
    ]
    sorted_turns, starts, prefix_max_end = _build_turn_index(turns)

    # 真實案例的非 batched「我也」（0.48s < 0.6s）
    with_anchor = _word_speaker_candidates(
        83.800, 84.280, sorted_turns, starts, prefix_max_end, anchor_tail=True
    )
    without_anchor = _word_speaker_candidates(
        83.800, 84.280, sorted_turns, starts, prefix_max_end, anchor_tail=False
    )
    assert with_anchor == without_anchor


# ── Viterbi DP 行為（取代舊的孤立單字 smoothing）────────────────────────────

def test_viterbi_flips_tie_at_speaker_handover_point():
    # 真實案例數字（staging 音檔 83.8s「我也」）：前文 word 屬 00、
    # 「我也」重疊精確平手但 affinity 偏剛開口的 02、後文 words 屬 02（換手點）。
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
    # 中段搭腔：前後文皆屬 A（長 turn），中間 word 被剛開口的 nested 短 turn B 同時
    # 罩住、重疊平手且 affinity 偏 B——但 B 只是搭腔證據，前後文一致性（兩次換手成本）
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
    # 原 smoothing 功能：A A B A A 型孤立單字雜訊（B 靠近平手 affinity 弱優勢贏
    # per-word，非強證據）→ 兩次換手成本遠大於 emission 差 → DP 全判 A。
    # words 用 0.5s（< WORD_TAIL_ANCHOR_SEC），不受尾端錨定影響。
    turns = [
        _turn(0.0, 10.0, "A"),
        _turn(2.9, 3.6, "B"),   # nested、以 w3 為中心，讓 w3 的 per-word 分數以微小差距偏 B
    ]
    # token 用 CJK——連續拉丁 token 會被 _build_units 黏成一單位，測不到逐字 DP
    words = [
        _w(1.0, 1.5, "一"), _w(2.0, 2.5, "二"), _w(3.0, 3.5, "三"),
        _w(4.0, 4.5, "四"), _w(5.0, 5.5, "五"),
    ]
    segs = [{"start": 1.0, "end": 5.5, "text": "一二三四五", "words": words}]

    # 前置確認：中間 word 單獨判會給 B（弱優勢），DP 才有東西可壓
    assert _pick_speaker_for_span(3.0, 3.5, turns) == "B"

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
    w2 = _w(3.55, 3.85, "w2")  # A/B 皆完整罩住（近平手），affinity 微偏剛開口的 B

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


def test_gap_word_fallback_does_not_drag_weak_real_overlap():
    # 信心度反轉迴歸：間隙字的 nearest fallback（純猜測）分數必須低於鄰接字的微弱
    # 「真實」重疊（fraction ~0.12），否則 DP 會為了保住間隙字的猜測分數，把有真證據
    # 的字一起拖去錯的語者（NEAREST_FALLBACK_SCORE=0.2 時代的實證 bug）。
    turns = [
        _turn(0.0, 8.9, "B"),     # w1 的最近 turn（但零重疊，只是猜測）
        _turn(10.0, 20.0, "A"),   # w2 有真實擦邊重疊
    ]
    words = [
        _w(8.95, 9.10, "w1"),   # 間隙字：零重疊，nearest=B（距 B 尾 0.125 < 距 A 頭 0.975）
        _w(9.12, 10.12, "w2"),  # 擦邊真重疊：與 A 重疊 0.12s / 1.0s = fraction 0.12
    ]
    segs = [{"start": 8.95, "end": 10.12, "text": "w1w2", "words": words}]

    # 前置確認：間隙字單獨判仍歸 B（fallback 語意本身不變）
    assert _pick_speaker_for_span(8.95, 9.10, turns) == "B"

    out = assign_speakers_word_level(segs, turns)

    # w2 的真證據（0.12 > fallback 0.01）勝出；間隙字也被前後文帶去 A（弱猜測被蓋過）
    assert len(out) == 1
    assert out[0]["speaker"] == "A"


def test_viterbi_converges_weak_alternating_pattern():
    # 43f829f 修過的迴歸點：per-word 弱證據交替（A B A B A 型）不得殘留交替雜訊。
    # 用兩個 nested 短 turn 讓 w2/w4 的 per-word 分數以微小差距偏 B → DP 收斂單一語者 A
    # （翻兩字要 4 次換手成本 ≫ emission 差 ~0.07）。
    # words 用 0.5s（< WORD_TAIL_ANCHOR_SEC），不受尾端錨定影響。
    turns = [
        _turn(0.0, 10.0, "A"),
        _turn(1.95, 2.55, "B"),   # 以 w2 為中心的 nested 短 turn
        _turn(3.95, 4.55, "B"),   # 以 w4 為中心的 nested 短 turn
    ]
    # token 用 CJK——連續拉丁 token 會被 _build_units 黏成一單位，測不到逐字 DP
    words = [
        _w(1.0, 1.5, "一"), _w(2.0, 2.5, "二"), _w(3.0, 3.5, "三"),
        _w(4.0, 4.5, "四"), _w(5.0, 5.5, "五"),
    ]
    segs = [{"start": 1.0, "end": 5.5, "text": "一二三四五", "words": words}]

    # 前置確認：per-word 確實是 A B A B A（w2/w4 靠近平手 affinity 弱優勢偏 B）
    assert [_pick_speaker_for_span(w["start"], w["end"], turns) for w in words] == \
        ["A", "B", "A", "B", "A"]

    out = assign_speakers_word_level(segs, turns)

    assert len(out) == 1
    assert out[0]["speaker"] == "A"


# ── 跨段 Viterbi + 拉丁 unit grouping（staging dump 實測數字）──────────────

def test_global_viterbi_flips_segment_final_tie_word_across_boundary():
    # staging 實測數字（dump 70cba0b5「我也」）：「我也」是前段最後一個 word、與前一字
    # 零間隙、重疊精確近平手（affinity 偏剛開口的 03，優勢 ~0.1 < 換手成本 0.3）。
    # per-segment DP 下它是序列末端，換手只虧不賺 → 誤判前語者 02（replay_eval.md
    # 第一輪的 0.2 < 0.3 硬上限）。跨段 DP 讓它不再是末端：後段整串 words 押 03，
    # 換手橫豎要發生、成本兩條路徑抵銷 → 「我也」的 affinity 優勢決勝，翻給 03。
    turns = [
        _turn(79.2253, 84.4060, "SPEAKER_02"),  # 前語者長 turn
        _turn(83.5960, 90.2785, "SPEAKER_03"),  # 後語者主 turn（83.6 剛開口）
        _turn(85.0303, 85.8741, "SPEAKER_02"),  # 後段內的搭腔短 turn
    ]
    seg1_words = [
        _w(82.62, 82.78, "看"), _w(82.78, 82.92, "你的"),
        _w(82.92, 83.22, "臀"), _w(83.22, 84.20, "我也"),  # 段尾近平手字
    ]
    seg2_words = [
        _w(84.20, 84.62, "常"), _w(84.62, 84.72, "常"), _w(84.72, 84.84, "會"),
        _w(84.84, 85.02, "忘"), _w(85.02, 85.24, "記"),
    ]
    segs = [
        {"start": 82.62, "end": 84.20, "text": "看你的臀我也", "words": seg1_words},
        {"start": 84.20, "end": 85.24, "text": "常常會忘記", "words": seg2_words},
    ]

    out = assign_speakers_word_level(segs, turns)

    my_ye = next(s for s in out if "我也" in s["text"])
    assert my_ye["speaker"] == "SPEAKER_03"
    # 前文（看你的臀）仍屬 02——只有交界字被後段證據接走
    assert out[0]["speaker"] == "SPEAKER_02"
    assert "看" in out[0]["text"]


def test_latin_unit_grouping_assigns_whole_word_one_speaker():
    # staging 實測數字（Emily 案）：whisper 把 Emily 切成 'Em'+'ily' 兩個 sub-word
    # token，語者交界恰在中間（02 turn 到 162.031 結束、03 接手）→ 逐字指派會把
    # 一個英文字切給兩個語者。黏成單位後以單位 span [161.75,162.27] 評分
    # （02 重疊 0.281s=54% > 03 0.239s=46%）→ 整字判 02。
    turns = [
        _turn(160.0903, 162.0310, "SPEAKER_02"),
        _turn(162.0310, 162.6553, "SPEAKER_03"),
        _turn(162.9085, 179.1591, "SPEAKER_03"),
    ]
    words = [
        _w(160.81, 161.27, "那就"), _w(161.27, 161.51, "想"), _w(161.51, 161.75, "到"),
        _w(161.75, 162.11, "Em"), _w(162.11, 162.27, "ily"),   # 同一英文字的 sub-word
        _w(162.27, 163.33, "謝謝"),
    ]
    segs = [{"start": 160.81, "end": 163.33, "text": "那就想到Emily謝謝", "words": words}]

    # 單位黏合本身：Em+ily 進同一單位
    stream = [
        {"seg_idx": 0, "word_idx": i, "start": w["start"], "end": w["end"], "word": w["word"]}
        for i, w in enumerate(words)
    ]
    units = _build_units(stream)
    emily_unit = next(u for u in units if u["words"][0]["word"] == "Em")
    assert [e["word"] for e in emily_unit["words"]] == ["Em", "ily"]
    assert (emily_unit["start"], emily_unit["end"]) == (161.75, 162.27)

    out = assign_speakers_word_level(segs, turns)

    emily_seg = next(s for s in out if "Emily" in s["text"])
    assert emily_seg["speaker"] == "SPEAKER_02"   # 整字同一語者，不再 Em|ily 切開


def test_near_tie_requires_two_distinct_speakers():
    # near-tie 判定必須看「不同 speaker」的競爭：A 有兩個重疊 turn（fraction 0.75/0.74，
    # 差 0.01）、競爭者 B 只有 0.68——若拿全體 turn 排序前兩名（0.75 vs 0.74，皆 A）會
    # 誤觸近平手、改用 affinity（B 起點緊貼 word → affinity 0.96 → B 翻盤）。
    # per-speaker 規則下 A(0.75) vs B(0.68) 差 0.07 > ε → 走 proximity，A 勝。
    turns = [
        _turn(9.0, 10.375, "A"),   # A turn 1：overlap 0.375 → fraction 0.75
        _turn(9.0, 10.37, "A"),    # A turn 2：overlap 0.370 → fraction 0.74（同語者，非競爭）
        _turn(9.96, 10.34, "B"),   # B：overlap 0.340 → fraction 0.68，但起點緊貼 word
    ]
    assert _pick_speaker_for_span(10.0, 10.5, turns) == "A"


def test_unit_anchor_budget_scales_with_token_count():
    # 黏合單位的錨定預算 = WORD_TAIL_ANCHOR_SEC × 單位 word 數：3-token 英文字
    # span 0.9s、預算 1.8s → 完整 span 評分（A 重疊 0.55s=61% > B 0.45s=50% → A）。
    # 對照：舊行為固定裁到尾端 0.6s 會把前導 sub-word 'Ha' 的證據裁掉
    # （裁後 A 0.25s/0.6=42% < B 0.45s/0.6=75% → 誤判 B）。
    turns = [
        _turn(8.0, 10.55, "A"),    # 覆蓋單位前 61%
        _turn(10.45, 12.0, "B"),   # 覆蓋單位尾 50%
    ]
    words = [_w(10.0, 10.3, "Ha"), _w(10.3, 10.6, "pp"), _w(10.6, 10.9, "y")]
    segs = [{"start": 10.0, "end": 10.9, "text": "Happy", "words": words}]

    # 前置確認：三個 token 黏成一個 0.9s 單位
    stream = [
        {"seg_idx": 0, "word_idx": i, "start": w["start"], "end": w["end"], "word": w["word"]}
        for i, w in enumerate(words)
    ]
    units = _build_units(stream)
    assert len(units) == 1 and (units[0]["start"], units[0]["end"]) == (10.0, 10.9)

    out = assign_speakers_word_level(segs, turns)

    assert out == [{"start": 10.0, "end": 10.9, "text": "Happy", "speaker": "A"}]


def test_is_latin_glue_rules():
    # 黏：拉丁接拉丁（無前導空格）、數字接在字母後、連字號
    assert _is_latin_glue("Em", "ily") is True
    assert _is_latin_glue("Em", "42") is True
    assert _is_latin_glue("co", "-op") is True
    # 不黏：CJK（不符拉丁 regex / 前一 token 非拉丁字母結尾）
    assert _is_latin_glue("我", "也") is False
    assert _is_latin_glue("我", "ily") is False
    # 不黏：有前導空格（faster-whisper 新英文字的訊號）
    assert _is_latin_glue("Hello", " world") is False
    # 不黏：前一 token 以數字結尾（"A1"+"B2" 不是同一個字的自然切分）
    assert _is_latin_glue("A1", "B2") is False
    # 不黏：前一 token 空字串
    assert _is_latin_glue("", "ily") is False


def test_cross_segment_gap_relief_applies_at_boundary():
    # 跨段 gap 折扣：交界字近平手（affinity 微偏 B 0.085 < 全額換手成本 0.3），
    # 換手橫豎要發生——
    # - 後段延遲 0.35s 開始（≥ SWITCH_GAP_RELIEF_SEC）→ 邊界換手打折(0.09)，
    #   DP 把換手推遲到便宜的邊界 → 交界字留 A
    # - 對照組：後段緊貼（gap 0.1）→ 兩個換手點同價，emission 決定 → 交界字翻 B
    turns = [
        _turn(0.0, 4.0, "A"),
        _turn(3.4, 4.4, "B"),
    ]
    w1 = _w(3.0, 3.3, "w1")    # A 獨占
    w2 = _w(3.55, 3.85, "w2")  # 段尾近平手字（A/B 皆罩住，affinity 微偏剛開口的 B）

    # 跨段 gap 0.35 ≥ 0.3 → 折扣生效，換手發生在段邊界
    out = assign_speakers_word_level([
        {"start": 3.0, "end": 3.85, "text": "w1w2", "words": [w1, w2]},
        {"start": 4.2, "end": 4.5, "text": "w3", "words": [_w(4.2, 4.5, "w3")]},
    ], turns)
    assert [(s["speaker"], s["text"]) for s in out] == [("A", "w1w2"), ("B", "w3")]

    # 對照組：跨段 gap 0.1 → 全額成本，換手提前到 emission 較高的 w2
    out = assign_speakers_word_level([
        {"start": 3.0, "end": 3.85, "text": "w1w2", "words": [w1, w2]},
        {"start": 3.95, "end": 4.25, "text": "w3", "words": [_w(3.95, 4.25, "w3")]},
    ], turns)
    assert [(s["speaker"], s["text"]) for s in out] == [
        ("A", "w1"), ("B", "w2"), ("B", "w3"),
    ]


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
    不 import 生產的常數與函數，避免和被測程式碼共用同一段邏輯）。
    規格與生產 word 路徑一致：尾端錨定 0.6s、近平手（fraction 差 < 0.05）用
    turn-start affinity（scale 1.0）、其餘用 proximity；
    平手語意與生產 `_argmax_speaker` 一致：精確平分時取字典序最小的 speaker。
    """
    if not turns:
        return None

    start = max(start, end - 0.6)  # word 尾端錨定（獨立重寫，同生產規格）
    span_len = max(end - start, 1e-6)

    overlapping = []  # [(turn, overlap_fraction)]
    for turn in turns:
        overlap = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
        if overlap > 0.0:
            overlapping.append((turn, overlap / span_len))

    if not overlapping:
        midpoint = (start + end) / 2.0

        def _distance(turn):
            if midpoint < turn["start"]:
                return turn["start"] - midpoint
            if midpoint > turn["end"]:
                return midpoint - turn["end"]
            return 0.0

        return min(turns, key=_distance)["speaker"]

    fracs = sorted((f for _, f in overlapping), reverse=True)
    near_tie = len(overlapping) >= 2 and (fracs[0] - fracs[1] < 0.05)

    best_speaker = None
    best_score = 0.0
    for turn, fraction in overlapping:
        if near_tie:
            tiebreak = max(0.0, 1 - abs(start - turn["start"]) / 1.0)
        else:
            turn_len = turn["end"] - turn["start"]
            if turn_len <= 0:
                tiebreak = 0.0
            else:
                span_mid = (start + end) / 2.0
                turn_mid = (turn["start"] + turn["end"]) / 2.0
                tiebreak = max(0.0, 1 - abs(span_mid - turn_mid) / (turn_len / 2.0))
        score = fraction + 0.1 * tiebreak
        if score > best_score or (
            score == best_score and best_speaker is not None and turn["speaker"] < best_speaker
        ):
            best_score = score
            best_speaker = turn["speaker"]

    return best_speaker


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


def test_indexed_and_brute_force_agree_on_symmetric_tie_regardless_of_turn_order():
    # 對稱平手：兩 turn 區間完全相同、turns 順序與字典序倒置（Z 在前）
    # → 分數精確相等，兩實作都必須決定性地取字典序最小的 "A"（不依賴迭代/掃描順序）
    turns = [_turn(0, 2, "Z"), _turn(0, 2, "A")]
    sorted_turns, starts, prefix_max_end = _build_turn_index(turns)
    span = (0.5, 1.5)

    indexed = _pick_speaker_indexed(*span, sorted_turns, starts, prefix_max_end)
    brute = _brute_force_pick_speaker(*span, turns)

    assert indexed == brute == "A"
