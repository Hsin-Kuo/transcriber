"""split_segments_at_sentence_punctuation：align 後依句末標點切句子級段。"""
from src.utils.text_utils import split_segments_at_sentence_punctuation


def test_split_multi_sentence_with_proportional_time():
    segs = [{"start": 0.0, "end": 10.0, "speaker": "A",
             "text": "今天天氣很好。我們出去走走吧！"}]
    out = split_segments_at_sentence_punctuation(segs)
    assert [s["text"] for s in out] == ["今天天氣很好。", "我們出去走走吧！"]
    # 時間在 [0,10] 內、連續、依字數比例
    assert out[0]["start"] == 0.0
    assert out[-1]["end"] == 10.0
    assert out[0]["end"] == out[1]["start"]
    assert all(s["speaker"] == "A" for s in out)  # speaker 沿用母段


def test_no_sentence_punct_unchanged():
    segs = [{"start": 0.0, "end": 5.0, "text": "今天天氣很好我們出去走走吧"}]  # 無句末標點
    assert split_segments_at_sentence_punctuation(segs) == segs


def test_single_sentence_unchanged():
    segs = [{"start": 1.0, "end": 4.0, "text": "只有一句話。"}]
    out = split_segments_at_sentence_punctuation(segs)
    assert len(out) == 1 and out[0]["text"] == "只有一句話。"


def test_comma_does_not_split():
    # 逗號不是句末標點，不切
    segs = [{"start": 0.0, "end": 6.0, "text": "今天天氣很好，我們出去走走"}]
    out = split_segments_at_sentence_punctuation(segs)
    assert len(out) == 1


def test_multiple_segments_and_question_mark():
    segs = [
        {"start": 0.0, "end": 4.0, "text": "你好嗎？我很好。"},
        {"start": 4.0, "end": 6.0, "text": "沒有標點的段"},
    ]
    out = split_segments_at_sentence_punctuation(segs)
    assert [s["text"] for s in out] == ["你好嗎？", "我很好。", "沒有標點的段"]
    # 第一段切兩句、時間都在 [0,4]
    assert out[0]["start"] == 0.0 and out[1]["end"] == 4.0


def test_empty_segments():
    assert split_segments_at_sentence_punctuation([]) == []
