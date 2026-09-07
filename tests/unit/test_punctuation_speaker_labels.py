"""語者標籤保全：標籤絕不進 LLM，由構造保證 labels_out == labels_in。

背景（2026-09 實測，gemini-2.5-flash-lite）：標籤原本隨文字送進 Gemini，靠 prompt
請它保留。實測呈現劑量反應——chunk 內標籤 58~340 個時保留率 100%，只剩 1 個時
兩次試驗都被整批刪光（0%）。長篇獨白正好落在「標籤極少」那端，造成使用者回報的
「前半段沒有語者、後半段才有」。

本測試組驗證結構，不驗證 Gemini 行為：LLM 呼叫一律 mock。
"""
import pytest

from src.services.utils.punctuation_processor import PunctuationProcessor

MODEL = "gemini-2.5-flash-lite"


def _proc():
    return PunctuationProcessor()


def _fake_chunk(transform=None):
    """產生假的 `_punctuate_chunk`，並記錄每次收到的 chunk_text。"""
    seen = []

    def _inner(chunk_text, language, chunk_idx=None, total_chunks=None):
        seen.append(chunk_text)
        out = transform(chunk_text) if transform else chunk_text
        return out, MODEL, {"total": 10, "prompt": 6, "completion": 4}

    _inner.seen = seen
    return _inner


def _add_punctuation(text: str) -> str:
    """模擬 LLM：在每行尾加句號並重新分段（刻意打亂段落結構）。"""
    lines = [ln for ln in text.split("\n\n") if ln.strip()]
    return "\n\n".join(f"{ln}。" for ln in lines)


# ── 核心保證：標籤不進 LLM、且不可能遺失 ────────────────────────────────

def test_labels_are_never_sent_to_the_llm(monkeypatch):
    proc = _proc()
    fake = _fake_chunk(_add_punctuation)
    monkeypatch.setattr(proc, "_punctuate_chunk", fake)

    text = "[SPEAKER_00] 今天我們來討論規劃\n\n[SPEAKER_01] 好我先講第一點"
    proc.process(text, provider="gemini", language="zh")

    assert fake.seen, "應該至少呼叫一次 LLM"
    for chunk in fake.seen:
        assert "[SPEAKER" not in chunk.upper()


def test_round_trip_preserves_every_label_and_order(monkeypatch):
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk(_add_punctuation))

    text = (
        "[SPEAKER_00] 今天我們來討論規劃\n\n"
        "[SPEAKER_01] 好我先講第一點\n\n"
        "[SPEAKER_00] 我補充一下"
    )
    out, model, usage = proc.process(text, provider="gemini", language="zh")

    lines = out.split("\n\n")
    assert len(lines) == 3
    assert lines[0].startswith("[SPEAKER_00] ")
    assert lines[1].startswith("[SPEAKER_01] ")
    assert lines[2].startswith("[SPEAKER_00] ")
    assert out.count("[SPEAKER_00]") == 2
    assert out.count("[SPEAKER_01]") == 1
    assert model == MODEL
    # 標點確實有被套用
    assert "。" in out


def test_llm_deleting_labels_cannot_lose_them(monkeypatch):
    """模擬舊 bug：LLM 把看到的標籤全刪。新路徑下標籤根本沒送出去，故不受影響。"""
    proc = _proc()

    def wipe_labels(chunk_text: str) -> str:
        # 就算模型想刪，chunk 裡也沒有標籤可刪
        return chunk_text.replace("[SPEAKER_00]", "").replace("[SPEAKER_01]", "")

    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk(wipe_labels))

    text = "[SPEAKER_00] 第一段內容\n\n[SPEAKER_01] 第二段內容"
    out, _, _ = proc.process(text, provider="gemini", language="zh")

    assert out.count("[SPEAKER_00]") == 1
    assert out.count("[SPEAKER_01]") == 1


def test_single_label_survives(monkeypatch):
    """prod 失效情境：整個 chunk 只有 1 個標籤（長篇獨白）→ 舊路徑 0% 保留。"""
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk(_add_punctuation))

    text = "[SPEAKER_00] " + "這是一段很長的獨白" * 50
    out, _, _ = proc.process(text, provider="gemini", language="zh")

    assert out.startswith("[SPEAKER_00] ")
    assert out.count("[SPEAKER_00]") == 1


# ── chunk 邊界與超長輪次切片 ────────────────────────────────────────────

def test_turn_never_spans_a_chunk_boundary():
    proc = _proc()
    texts = ["A" * 30, "B" * 30, "C" * 30]

    chunks = proc._group_turns_into_chunks(texts, chunk_size=70)

    # 每個 chunk 內的 piece 都必須是完整輪次（未被切片）
    for chunk in chunks:
        for turn_idx, piece in chunk:
            assert piece == texts[turn_idx]
    # 每個輪次只出現一次
    all_idx = [i for chunk in chunks for i, _ in chunk]
    assert sorted(all_idx) == [0, 1, 2]


def test_oversized_turn_is_split_into_pieces_sharing_one_turn_index():
    proc = _proc()
    texts = ["X" * 250]

    chunks = proc._group_turns_into_chunks(texts, chunk_size=100)

    assert len(chunks) > 1, "超長輪次應被切成多個 chunk"
    assert all(len(chunk) == 1 for chunk in chunks)
    assert all(chunk[0][0] == 0 for chunk in chunks), "所有切片共用同一 turn_idx"
    assert "".join(chunk[0][1] for chunk in chunks) == texts[0]


def test_oversized_turn_rejoins_into_one_labelled_line(monkeypatch):
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk())

    body = "長篇獨白內容" * 60
    text = f"[SPEAKER_00] {body}\n\n[SPEAKER_01] 短回應"
    out, _, _ = proc.process(text, provider="gemini", language="zh", chunk_size=100)

    lines = out.split("\n\n")
    assert len(lines) == 2, f"超長輪次必須 rejoin 成一行，實際 {len(lines)} 行"
    assert out.count("[SPEAKER_00]") == 1
    assert out.count("[SPEAKER_01]") == 1
    assert lines[0].replace("[SPEAKER_00] ", "") == body


# ── 回歸底線：無標籤輸入行為完全不變 ────────────────────────────────────

def test_unlabelled_input_takes_original_path(monkeypatch):
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk(_add_punctuation))

    text = "這是一段沒有語者標籤的文字"
    out, model, _ = proc.process(text, provider="gemini", language="zh")

    # 原路徑：輸出即 LLM 結果，未經任何標籤處理
    assert out == _add_punctuation(text)
    assert model == MODEL


def test_parse_speaker_turns_returns_none_without_labels():
    proc = _proc()
    assert proc._parse_speaker_turns("純文字\n\n沒有標籤") is None
    assert proc._parse_speaker_turns("") is None


def test_parse_speaker_turns_extracts_label_and_body():
    proc = _proc()
    turns = proc._parse_speaker_turns("[SPEAKER_00] 甲說的話\n\n[SPEAKER_01] 乙說的話")
    assert turns == [("[SPEAKER_00]", "甲說的話"), ("[SPEAKER_01]", "乙說的話")]


def test_mixed_labelled_and_unlabelled_turns(monkeypatch):
    """部分行沒有標籤（防禦性情境）→ 有標籤的照貼，無標籤的不硬加。"""
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk())

    text = "[SPEAKER_00] 有標籤\n\n沒有標籤的一行\n\n[SPEAKER_02] 又有標籤"
    out, _, _ = proc.process(text, provider="gemini", language="zh")

    lines = out.split("\n\n")
    assert len(lines) == 3
    assert lines[0].startswith("[SPEAKER_00]")
    assert not lines[1].startswith("[")
    assert lines[2].startswith("[SPEAKER_02]")


def test_many_speakers_all_preserved(monkeypatch):
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk(_add_punctuation))

    turns = [f"[SPEAKER_{i:02d}] 第{i}位講者的內容" for i in range(8)]
    out, _, _ = proc.process("\n\n".join(turns), provider="gemini", language="zh")

    for i in range(8):
        assert out.count(f"[SPEAKER_{i:02d}]") == 1
    assert len(out.split("\n\n")) == 8


# ── 對齊（_align_output_to_pieces）────────────────────────────────────────

def test_align_splits_output_back_to_pieces():
    proc = _proc()
    pieces = ["甲說的話", "乙說的話"]
    output = "甲說的話。乙說的話。"

    aligned = proc._align_output_to_pieces(output, pieces)

    assert aligned == ["甲說的話。", "乙說的話。"]


def test_align_returns_none_on_truncated_output():
    proc = _proc()
    pieces = ["內容" * 50, "內容" * 50]
    output = "內容"  # 嚴重截斷

    assert proc._align_output_to_pieces(output, pieces) is None


def test_truncated_chunk_falls_back_to_original_text(monkeypatch):
    """對齊失敗 → 整批回退原文：內容不遺失，標籤照樣完整。"""
    proc = _proc()
    monkeypatch.setattr(proc, "_punctuate_chunk", _fake_chunk(lambda t: "崩塌"))

    text = "[SPEAKER_00] " + "甲的內容" * 30 + "\n\n[SPEAKER_01] " + "乙的內容" * 30
    out, _, _ = proc.process(text, provider="gemini", language="zh")

    assert out.count("[SPEAKER_00]") == 1
    assert out.count("[SPEAKER_01]") == 1
    assert "甲的內容" * 30 in out
    assert "乙的內容" * 30 in out


def test_single_piece_chunk_returns_output_as_is():
    proc = _proc()
    assert proc._align_output_to_pieces("  加了標點。 ", ["加了標點"]) == ["加了標點。"]
