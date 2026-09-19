"""CJK-aware 半形→全形句讀轉換。

背景（staging 2026-09-19）：全形一直只靠 LLM 輸出習慣在撐——prompt 原本沒要求、
全文也從未過轉換，模型偶爾輸出半形就露餡。轉換改為程式碼保證，規則是
「鄰字有 CJK 才轉」：錯轉會毀損內容（3.5→3。5），漏轉只是樣式不一致。
"""
from src.utils.text_utils import (
    convert_cjk_punctuation_to_fullwidth,
    convert_segments_punctuation,
)


def test_chinese_context_converts():
    assert convert_cjk_punctuation_to_fullwidth("你好,世界.") == "你好，世界。"
    assert convert_cjk_punctuation_to_fullwidth("是嗎?對!好:嗯;") == "是嗎？對！好：嗯；"


def test_numbers_are_protected():
    assert convert_cjk_punctuation_to_fullwidth("比率是 3.5 跟 1,000") == "比率是 3.5 跟 1,000"
    assert convert_cjk_punctuation_to_fullwidth("時間 12:30 開始") == "時間 12:30 開始"


def test_pure_english_is_untouched():
    text = "Hello, world. How are you? e.g. this: fine; ok!"
    assert convert_cjk_punctuation_to_fullwidth(text) == text


def test_mixed_text_converts_only_cjk_adjacent():
    # 句讀緊貼中文 → 轉；英文句內 → 不轉
    assert (
        convert_cjk_punctuation_to_fullwidth("他說,machine learning很重要.")
        == "他說，machine learning很重要。"
    )
    # 兩個英文詞之間的半形逗號：寧可漏轉不可錯轉
    assert (
        convert_cjk_punctuation_to_fullwidth("用 numpy, pandas 做分析")
        == "用 numpy, pandas 做分析"
    )


def test_japanese_kana_counts_as_cjk():
    assert convert_cjk_punctuation_to_fullwidth("そうですか?") == "そうですか？"


def test_brackets_and_quotes_are_not_converted():
    # 括號/引號有開閉配對問題，刻意不碰
    text = '他說"好"(大概)'
    assert convert_cjk_punctuation_to_fullwidth(text) == text


def test_empty_and_none_safe():
    assert convert_cjk_punctuation_to_fullwidth("") == ""


def test_segments_conversion_is_cjk_aware():
    segments = [
        {"text": "你好,世界.", "start": 0.0, "end": 1.0},
        {"text": "rate is 3.5, ok?", "start": 1.0, "end": 2.0},
        {"text": ""},
        {"start": 2.0},
    ]
    out = convert_segments_punctuation(segments)
    assert out[0]["text"] == "你好，世界。"
    assert out[1]["text"] == "rate is 3.5, ok?", "英文 segment 不得被毀損"
    assert out[2]["text"] == ""
    assert "text" not in out[3]
    # 不改動原 list
    assert segments[0]["text"] == "你好,世界."
