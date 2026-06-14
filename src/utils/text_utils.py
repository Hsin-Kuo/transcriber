"""
文本工具函數
職責：提供文本處理相關的工具函數
"""

import unicodedata
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


def align_segments_to_punctuated_text(segments: List[Dict], punctuated_text: str) -> List[Dict]:
    """標點處理後，將 punctuated_text 的內容對齊回各 segment。

    策略：用 Unicode category 定義「內容字符」（字母、數字、CJK；非標點非空白），
    在 punctuated_text 與原始 segments 之間做 1:1 字符對齊，
    再按 segment 邊界切出含尾隨標點的 span。

    若對齊失敗（字符數量或內容不符，表示 LLM 修改了文字），fallback 回原始 segments。
    """
    if not segments or not punctuated_text:
        return segments

    def is_content(ch: str) -> bool:
        return unicodedata.category(ch)[0] in ('L', 'N', 'M')

    # 從 punctuated_text 提取內容字符及其位置
    punct_content = [(i, ch) for i, ch in enumerate(punctuated_text) if is_content(ch)]

    # 從各 segment 依序提取內容字符（帶 segment index）
    seg_content = []
    for seg_idx, seg in enumerate(segments):
        for ch in seg.get("text", ""):
            if is_content(ch):
                seg_content.append((seg_idx, ch))

    # 數量或字符不符 → fallback
    if len(punct_content) != len(seg_content):
        return segments
    for (_, ch_p), (_, ch_s) in zip(punct_content, seg_content, strict=True):
        if ch_p != ch_s:
            return segments

    if not punct_content:
        return segments

    # 記錄每個 segment 在 punctuated_text 中第一個與最後一個內容字符的位置
    seg_first: Dict[int, int] = {}
    seg_last: Dict[int, int] = {}
    for (pos, _), (seg_idx, _) in zip(punct_content, seg_content, strict=True):
        if seg_idx not in seg_first:
            seg_first[seg_idx] = pos
        seg_last[seg_idx] = pos

    # 切出每個 segment 的 span（含尾隨標點，不含下一個 segment 的內容）
    result = []
    for seg_idx, seg in enumerate(segments):
        if seg_idx not in seg_first:
            result.append({**seg, "text": ""})
            continue

        start = seg_first[seg_idx]
        if seg_idx + 1 in seg_first:
            end = seg_first[seg_idx + 1]
            text = punctuated_text[start:end].rstrip()
        else:
            text = punctuated_text[start:].strip()

        result.append({**seg, "text": text})

    return result


# 句末標點（半形與全形都列，因可能在 convert 全形之前執行）
_SENTENCE_END_PUNCT = "。！？!?…"


def split_segments_at_sentence_punctuation(segments: List[Dict]) -> List[Dict]:
    """在 Gemini 標點之後，把每個 segment 依句末標點切成「句子級」子 segment。

    中文 whisper 不吐標點 → 早期(word-timestamp)切只能依停頓/長度、會切在句中。
    句子邊界只有 Gemini 加完標點才有，故在 align 之後做這步。

    計時：在原 segment 的 [start, end] 內，依各句字數比例線性分配（段已不長 →
    比例插值夠用；不需把 word timestamps 穿過整條 pipeline）。speaker 等欄位沿用母段。
    無句末標點（標點失敗 / use_punctuation=False）→ 該段原樣保留。
    """
    if not segments:
        return segments

    out: List[Dict] = []
    for seg in segments:
        text = seg.get("text") or ""
        # 依句末標點切，標點留在句尾
        sentences, cur = [], ""
        for ch in text:
            cur += ch
            if ch in _SENTENCE_END_PUNCT:
                sentences.append(cur)
                cur = ""
        if cur:
            sentences.append(cur)

        # 0 或 1 句（無句末標點）→ 不動
        if len([s for s in sentences if s.strip()]) <= 1:
            out.append(seg)
            continue

        start = seg.get("start", 0.0)
        end = seg.get("end", start)
        dur = max(0.0, end - start)
        total = sum(len(s) for s in sentences) or 1
        cum = 0
        for s in sentences:
            seg_chars = len(s)
            if not s.strip():
                cum += seg_chars
                continue
            sub_start = start + dur * (cum / total)
            cum += seg_chars
            sub_end = start + dur * (cum / total)
            out.append({
                **seg,
                "start": round(sub_start, 3),
                "end": round(sub_end, 3),
                "text": s.strip(),
            })

    return out


def convert_segments_punctuation(segments: List[Dict]) -> List[Dict]:
    """將 segments 中的半形標點符號轉換為全形

    Args:
        segments: Sound Lite 輸出的 segments 列表

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
