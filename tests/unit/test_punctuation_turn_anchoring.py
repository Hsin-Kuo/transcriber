"""輪次邊界對齊：body 換行正規化（P1）+ 切點錨點吸附（P2）。

使用者回報症狀（staging 0ad21a82）：
    [SPEAKER_01] 們現在在網頁還是泡很多地方一直給別人
    看？有
    [SPEAKER_00] 人來申請的話，…

兩個成因：
- 切點越過 LLM 自己給的空行邊界，把下一輪開頭幾個字帶進前一輪（→ 開頭缺字）
- 輪次 body 內殘留 `\\n\\n`，與輪次分隔符撞號（→ 無標籤漂浮段落）

實測基線：漂浮段落 187/427（43.8%）；漂浮段落 82.8% 結束在句子中間，
有標籤輪次只有 4.9%；越界量中位數 11 字。
LLM 呼叫一律 mock，本檔測結構不測 Gemini。
"""
import re

from src.services.utils.punctuation_processor import PunctuationProcessor

MODEL = "gemini-2.5-flash-lite"
LABEL_RE = re.compile(r"\[SPEAKER_\d+\]")


def _proc():
    return PunctuationProcessor()


def _fake(transform):
    def _inner(chunk_text, language, chunk_idx=None, total_chunks=None):
        return transform(chunk_text), MODEL, None
    return _inner


# ── P1：body 換行正規化 ─────────────────────────────────────────────────

def test_cjk_body_newlines_are_joined_without_space(monkeypatch):
    proc = _proc()
    # 模擬 LLM 在單一輪次內自行分段
    monkeypatch.setattr(
        proc, "_punctuate_chunk",
        _fake(lambda t: t.replace("給別人看", "給別人看？\n\n")),
    )

    out, _, _ = proc.process(
        "[SPEAKER_00] 我們現在在網頁貼很多地方給別人看", provider="gemini", language="zh"
    )

    assert "\n\n" not in out.replace("\n\n[SPEAKER", "\x00")  # 只剩輪次分隔
    body = LABEL_RE.sub("", out).strip()
    assert "\n" not in body
    assert "給別人看" in body


def test_latin_body_newlines_become_single_space(monkeypatch):
    proc = _proc()
    monkeypatch.setattr(
        proc, "_punctuate_chunk",
        _fake(lambda t: t.replace("lazy dog", "lazy\n\ndog")),
    )

    out, _, _ = proc.process(
        "[SPEAKER_00] The quick brown fox jumps over the lazy dog",
        provider="gemini", language="en",
    )

    body = LABEL_RE.sub("", out).strip()
    assert "\n" not in body
    assert "lazy dog" in body, "拉丁語系換行必須換成單一空格，不能黏成 lazydog"
    assert "lazydog" not in body
    assert "  " not in body


def test_upstream_newlines_in_turn_text_are_also_normalized(monkeypatch):
    """上游 segments 自帶的換行（實測 237/2443 段）也要收掉。"""
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake(lambda t: t))

    # identity LLM：換行完全來自輸入本身
    out, _, _ = proc.process(
        "[SPEAKER_00] 得非常\n \n 好。然後就走出臺大醫院",
        provider="gemini", language="zh",
    )

    body = LABEL_RE.sub("", out).strip()
    assert "\n" not in body
    assert "得非常好。" in body


def test_output_shape_is_one_paragraph_per_turn(monkeypatch):
    """段落數必須等於輪次數——沒有漂浮段落。"""
    proc = _proc()
    monkeypatch.setattr(
        proc, "_punctuate_chunk",
        _fake(lambda t: t.replace("。", "。\n\n")),  # LLM 到處插空行
    )

    turns = [f"[SPEAKER_{i%2:02d}] 第{i}位講者說了一些話。還有第二句話。" for i in range(6)]
    out, _, _ = proc.process("\n\n".join(turns), provider="gemini", language="zh")

    paras = [p for p in out.split("\n\n") if p.strip()]
    assert len(paras) == 6, f"應為 6 段（每輪一段），實際 {len(paras)}"
    assert all(LABEL_RE.match(p) for p in paras), "不得有無標籤的漂浮段落"


# ── P2：切點錨點吸附 ────────────────────────────────────────────────────

def test_snap_prefers_blank_line_only_on_ties():
    """距離優先、空行只用來打平手。

    嚴格「空行永遠贏」會挑到輪次內部的分段空行、放掉正落在估計點上的句末標點；
    e2e 重播實測那樣會讓輪次結尾落在句中的比率從 9.8% 惡化到 15.9%。
    """
    proc = _proc()
    # 空行 44（距 6）vs 句末 48（距 2）→ 取較近的句末
    assert proc._snap_to_anchor(50, 12, [44], [48], lower=0, upper=100) == 48
    # 同距離 → 空行優先
    assert proc._snap_to_anchor(50, 12, [48], [52], lower=0, upper=100) == 48


def test_snap_picks_nearest_anchor_not_the_first():
    """LLM 給的空行數是輪次數的 1.78 倍，貪心取第一個會系統性選錯。"""
    proc = _proc()
    assert proc._snap_to_anchor(50, 20, [35, 48, 60], [], lower=0, upper=100) == 48


def test_snap_falls_back_to_estimate_when_no_anchor_in_window():
    proc = _proc()
    assert proc._snap_to_anchor(50, 5, [10, 90], [12], lower=0, upper=100) == 50


def test_snap_respects_lower_bound_for_monotonicity():
    proc = _proc()
    # 錨點 30 在窗口內但低於 lower → 不得回退
    got = proc._snap_to_anchor(40, 20, [30], [], lower=36, upper=100)
    assert got >= 36


def test_snap_clamps_to_upper_bound():
    proc = _proc()
    assert proc._snap_to_anchor(120, 20, [], [], lower=0, upper=100) == 100


def test_local_deletion_no_longer_steals_next_turn_opening():
    """核心失效型態：LLM 局部刪贅字 → 舊碼切點越界偷走下一輪開頭。"""
    proc = _proc()
    pieces = [
        "我們現在在網頁還是貼很多地方一直給別人看",
        "有人來申請的話我們就會看",
    ]
    # LLM 刪掉「還是」「一直」(4 個內容字)，並在真正的輪次邊界給了空行
    output = "我們現在在網頁貼很多地方給別人看？\n\n有人來申請的話，我們就會看。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned is not None
    assert aligned[1].startswith("有人來申請"), (
        f"下一輪開頭不得缺字，實際 {aligned[1][:12]!r}"
    )
    assert "\n" not in aligned[0], "空行應歸前一片段並被 strip 掉"
    assert aligned[0].endswith("？")


def test_blank_lines_more_than_turns_still_finds_turn_boundary():
    """輪次內也有空行（實測 1.78 倍場景）→ 要選最接近估計位置的那個。"""
    proc = _proc()
    pieces = ["甲甲甲甲甲甲甲甲甲甲", "乙乙乙乙乙乙乙乙乙乙"]
    # 輪次邊界的空行在中間，另外在兩輪內部各插一個空行
    output = "甲甲甲。\n\n甲甲甲甲甲甲甲。\n\n乙乙乙乙乙。\n\n乙乙乙乙乙。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned is not None
    assert "乙" not in aligned[0], "不得把下一語者的字併進上一段"
    assert aligned[1].count("乙") == 10


def test_sentence_end_used_when_no_blank_line():
    proc = _proc()
    pieces = ["甲甲甲甲甲甲甲甲甲甲", "乙乙乙乙乙乙乙乙乙乙"]
    output = "甲甲甲甲甲甲甲甲甲甲。乙乙乙乙乙乙乙乙乙乙。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned == ["甲甲甲甲甲甲甲甲甲甲。", "乙乙乙乙乙乙乙乙乙乙。"]


def test_cut_points_are_strictly_monotonic_with_dense_anchors():
    """密集錨點下切點不可回退、不可產生空片段。"""
    proc = _proc()
    pieces = ["甲" * 6, "乙" * 6, "丙" * 6, "丁" * 6]
    # 每個字後面都有空行 → 錨點極密，最容易誘發回退
    output = "\n\n".join(list("甲甲甲甲甲甲乙乙乙乙乙乙丙丙丙丙丙丙丁丁丁丁丁丁"))

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned is not None
    assert len(aligned) == 4
    assert all(p for p in aligned), f"不得有空片段: {aligned}"
    # 重組後內容字元不遺失
    joined = "".join(aligned)
    for ch in "甲乙丙丁":
        assert joined.count(ch) == 6


def test_median_overshoot_scenario_is_corrected():
    """實測越界中位數 11 字級的場景：修正後開頭歸位。"""
    proc = _proc()
    turn1 = "這是第一位講者講的一段話總共有好幾十個字這樣才夠長"
    turn2 = "這是第二位講者接著講的內容也要夠長才測得出來"
    pieces = [turn1, turn2]
    # LLM 刪掉 turn1 中 11 個內容字元，邊界給空行
    shortened = turn1.replace("總共有好幾十個字這樣", "")
    output = f"{shortened}。\n\n{turn2}。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned is not None
    assert aligned[1].startswith("這是第二位講者"), (
        f"開頭缺字未修正: {aligned[1][:14]!r}"
    )
    assert "\n" not in aligned[0]


# ── code review 回歸測試 ─────────────────────────────────────────────────

def test_non_final_cut_never_lands_at_end_of_output():
    """review #1：吸附把切點放到 len(output) → 末片段空字串 → 呼叫端回填原文
    → 同一段文字出現兩次。非末段切點必須為後續片段各留至少一個字元。
    """
    proc = _proc()
    # 短的末輪次被 LLM 併進前一句，句末錨點正好在字串結尾且落在窗口內
    pieces = ["這是第一位講者講的一段話內容", "好"]
    output = "這是第一位講者講的一段話內容，好。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned is not None
    assert all(p for p in aligned), f"不得有空片段: {aligned}"
    # 內容不得重複出現
    assert aligned[0].count("這是第一位講者") == 1
    assert "這是第一位講者" not in aligned[1]


def test_no_content_duplication_end_to_end(monkeypatch):
    """review #1 端到端：確認輸出裡沒有同一段文字出現兩次。"""
    proc = _proc()
    monkeypatch.setattr(
        proc, "_punctuate_chunk",
        _fake(lambda t: t.replace("\n\n", "，") + "。"),  # LLM 把短末輪次併進前句
    )

    out, _, _ = proc.process(
        "[SPEAKER_00] 這是第一位講者講的一段話內容\n\n[SPEAKER_01] 好",
        provider="gemini", language="zh",
    )

    assert out.count("這是第一位講者講的一段話內容") == 1, f"內容重複: {out!r}"
    assert out.count("[SPEAKER_00]") == 1
    assert out.count("[SPEAKER_01]") == 1


def test_multi_piece_cuts_reserve_room_for_every_piece():
    """review #1 級聯情境：多輪次時後續切點不得全被 clamp 到結尾。"""
    proc = _proc()
    pieces = ["甲" * 12, "乙", "丙", "丁"]
    output = "甲甲甲甲甲甲甲甲甲甲甲甲，乙丙丁。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned is not None
    assert all(p for p in aligned), f"不得有空片段: {aligned}"
    assert len(aligned) == 4


def test_cjk_body_keeps_space_between_embedded_latin_words():
    """review #2：中文逐字稿夾英文術語，換行落在兩個拉丁詞之間不得黏死。"""
    proc = _proc()

    assert proc._normalize_turn_body("我用 machine \n\n learning 模型", "zh") == (
        "我用 machine learning 模型"
    )
    # 純中文仍然直接接續（不多出空格）
    assert proc._normalize_turn_body("我說\n\n他也說", "zh") == "我說他也說"
    # 中文與拉丁交界不補空格（沿用既有 CJK 慣例）
    assert proc._normalize_turn_body("模型\n\nlearning", "zh") == "模型learning"


def test_closing_quote_stays_with_previous_turn():
    """review #3：句末錨點落在 。 與 」 之間 → 收尾引號不得懸掛到下一輪開頭。"""
    proc = _proc()
    pieces = ["甲甲甲甲甲", "乙乙乙乙乙"]
    output = "他說「甲甲甲甲甲。」乙乙乙乙乙。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned[0].endswith("」"), f"收尾引號應跟著前一段: {aligned[0]!r}"
    assert not aligned[1].startswith("」")
    assert aligned[1].startswith("乙")


def test_ambiguous_period_is_not_an_anchor():
    """review #4：小數點/縮寫裡的 `.` 不得當句末錨點。"""
    import src.services.utils.punctuation_processor as pp

    assert pp._is_ambiguous_period("3.5", 1) is True
    assert pp._is_ambiguous_period("e.g", 1) is True
    assert pp._is_ambiguous_period("end. Next", 3) is False

    proc = _proc()
    pieces = ["The rate was 3.5 and we expect more growth", "Yes I agree with that point"]
    output = "The rate was 3.5 and we expect more growth. Yes, I agree with that point."

    aligned = proc._align_output_to_pieces(output, pieces)

    assert "3.5" in aligned[0], f"小數不得被切開: {aligned[0]!r}"
    assert aligned[1].startswith("Yes"), f"下一輪開頭被偷字: {aligned[1]!r}"


def test_cjk_language_tuple_is_shared():
    """review #5：CJK 語言 tuple 收斂成單一常數。"""
    import src.services.utils.punctuation_processor as pp

    src = open(pp.__file__, encoding="utf-8").read()
    assert src.count('("zh", "zh-TW", "zh-CN", "ja", "ko")') == 1, (
        "5 元素 CJK tuple 應只在 _NO_SPACE_LANGUAGES 定義一次"
    )


def test_no_anchor_at_all_still_returns_full_coverage():
    """完全沒有錨點（無標點無空行）→ 回退計數位置，內容不遺失。"""
    proc = _proc()
    pieces = ["甲" * 10, "乙" * 10]
    output = "甲" * 10 + "乙" * 10

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned == ["甲" * 10, "乙" * 10]
