"""
文本工具函數
職責：提供文本處理相關的工具函數
"""

from typing import List, Dict

# 半形轉全形標點符號對照表
HALFWIDTH_TO_FULLWIDTH_PUNCTUATION = {
    ",": "，",
    ".": "。",
    "?": "？",
    "!": "！",
    ":": "：",
    ";": "；",
    "(": "（",
    ")": "）",
    "[": "【",
    "]": "】",
    '"': "「",
    "'": "'",
}


def convert_punctuation_to_fullwidth(text: str) -> str:
    """將文本中的半形標點符號轉換為全形

    Args:
        text: 要轉換的文本

    Returns:
        轉換後的文本
    """
    if not text:
        return text

    result = text
    for half, full in HALFWIDTH_TO_FULLWIDTH_PUNCTUATION.items():
        result = result.replace(half, full)

    return result


def convert_segments_punctuation(segments: List[Dict]) -> List[Dict]:
    """將 segments 中的半形標點符號轉換為全形

    Args:
        segments: Whisper 輸出的 segments 列表

    Returns:
        轉換後的 segments 列表
    """
    if not segments:
        return segments

    converted = []
    for segment in segments:
        new_segment = segment.copy()
        if "text" in new_segment and new_segment["text"]:
            new_segment["text"] = convert_punctuation_to_fullwidth(new_segment["text"])
        converted.append(new_segment)

    return converted
