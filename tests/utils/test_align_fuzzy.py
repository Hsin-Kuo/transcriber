"""align_segments_to_punctuated_text 模糊對齊測試。

舊版嚴格 1:1，Gemini 改字或 diarization 的 [SPEAKER_XX] 就整個 fallback（segments 無標點）。
新版用 difflib 模糊對齊 + 剝 speaker 標籤，容忍增刪改。
"""
from src.utils.text_utils import align_segments_to_punctuated_text


def _segs(*texts):
    out, t = [], 0.0
    for x in texts:
        out.append({"start": t, "end": t + 1, "text": x, "speaker": "A"})
        t += 1
    return out


def test_exact_match_distributes_punctuation():
    segs = _segs("今天天氣", "很好嗎")
    out = align_segments_to_punctuated_text(segs, "今天天氣，很好嗎？")
    assert out[0]["text"] == "今天天氣，"
    assert out[1]["text"] == "很好嗎？"
    assert all(s["speaker"] == "A" for s in out)  # 其他欄位保留


def test_speaker_labels_stripped():
    segs = _segs("今天天氣", "很好嗎")
    out = align_segments_to_punctuated_text(segs, "[SPEAKER_00] 今天天氣，很好嗎？")
    # 剝掉 [SPEAKER_00] 後應正常對齊（segments 拿到標點）
    assert "，" in out[0]["text"] and "今天天氣" in out[0]["text"]
    assert "？" in out[1]["text"]
    assert "SPEAKER" not in out[0]["text"]


def test_gemini_substitution_still_aligns():
    # Gemini 把「嗎」改成「喔」→ 內容字不完全相同，舊版會 fallback；新版仍切兩段且有標點
    segs = _segs("今天天氣", "很好嗎")
    out = align_segments_to_punctuated_text(segs, "今天天氣，很好喔？")
    assert len(out) == 2
    assert "，" in out[0]["text"]
    assert out[1]["text"].endswith("？")


def test_gemini_insertion_still_aligns():
    # Gemini 插入「的」
    segs = _segs("今天天氣真好", "我們出門")
    out = align_segments_to_punctuated_text(segs, "今天的天氣真好，我們出門。")
    assert len(out) == 2
    assert out[0]["text"].endswith("，")
    assert out[1]["text"].endswith("。")
    # 兩段合起來涵蓋全文（不漏字）
    assert "我們出門" in out[1]["text"]


def test_empty_inputs_fallback():
    segs = _segs("abc")
    assert align_segments_to_punctuated_text(segs, "") == segs
    assert align_segments_to_punctuated_text([], "abc。") == []


def test_segments_get_punctuation_not_raw():
    # 回歸防線：對齊後 segments 應含標點（不是原始無標點文字）
    segs = _segs("我來介紹一下", "這個產品")
    out = align_segments_to_punctuated_text(segs, "我來介紹一下，這個產品。")
    joined = "".join(s["text"] for s in out)
    assert "，" in joined and "。" in joined
