"""
文本工具函數
職責：提供文本處理相關的工具函數
"""

import difflib
import re
import unicodedata
from typing import List, Dict

# diarization 開啟時 full_text 內嵌的說話者標籤；對齊前需剝除（segments 文字裡沒有）
_SPEAKER_LABEL_RE = re.compile(r'\[SPEAKER_\d+\]')

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


def strip_subtitle_punctuation(text: str) -> str:
    """移除字幕用文字的句讀標點，但保留數字/英文中有語意的符號。

    用 Unicode 標點類別（P*）判斷整體移除，僅對歧義的 ASCII 字元 `. , : ' -`
    以前後字元 lookaround 保護，避免破壞：
    - 小數點 / 千分位：3.14、1,000
    - 時間冒號：12:30
    - 英文縮寫：U.S.、e.g
    - 字內單引號：don't、John's
    - 連字號：well-known、2-3

    全形句讀（，。！？、；：「」…—等）一律移除。
    """
    if not text:
        return text

    chars = list(text)
    n = len(chars)
    out = []

    for i, ch in enumerate(chars):
        if not unicodedata.category(ch).startswith("P"):
            out.append(ch)
            continue

        prev_ch = chars[i - 1] if i > 0 else ""
        next_ch = chars[i + 1] if i + 1 < n else ""

        # 受保護的字內 ASCII 標點：前後皆為對應類別時保留
        if ch == "." and ((prev_ch.isdigit() and next_ch.isdigit())
                          or (prev_ch.isalpha() and next_ch.isalpha())):
            out.append(ch)            # 3.14 / U.S
            continue
        if ch == "," and prev_ch.isdigit() and next_ch.isdigit():
            out.append(ch)            # 1,000
            continue
        if ch == ":" and prev_ch.isdigit() and next_ch.isdigit():
            out.append(ch)            # 12:30
            continue
        if ch in ("'", "’") and prev_ch.isalnum() and next_ch.isalnum():
            out.append(ch)            # don't / John's
            continue
        if ch == "-" and prev_ch.isalnum() and next_ch.isalnum():
            out.append(ch)            # well-known / 2-3
            continue

        # 其餘標點：移除（不補字）

    result = "".join(out)
    # 收斂移除後可能產生的多餘空白
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip()


def align_segments_to_punctuated_text(segments: List[Dict], punctuated_text: str) -> List[Dict]:
    """標點處理後，將 punctuated_text 的內容對齊回各 segment（把標點/句子分回各段）。

    用「內容字符」（字母、數字、CJK；非標點非空白）做對齊，**模糊比對**（difflib）
    以容忍 Gemini 的增/刪/改字——舊版要求嚴格 1:1，Gemini 只要動一個字就整個 fallback，
    diarization 的 `[SPEAKER_XX]` 標籤更是必然破壞 1:1 → segments 永遠拿不到標點。

    步驟：① 剝掉 full_text 的 `[SPEAKER_XX]` 標籤 ② difflib 對齊 segment↔punct 內容字符，
    為每段找出在(剝標籤後)文字中的起點 ③ 按相鄰段起點切出含尾隨標點的 span。
    任何異常或無內容字 → fallback 回原始 segments（不打斷轉錄）。
    """
    if not segments or not punctuated_text:
        return segments

    try:
        def is_content(ch: str) -> bool:
            return unicodedata.category(ch)[0] in ('L', 'N', 'M')

        clean = _SPEAKER_LABEL_RE.sub("", punctuated_text)

        punct_content = [(i, ch) for i, ch in enumerate(clean) if is_content(ch)]
        seg_content = []  # (seg_idx, char)
        for seg_idx, seg in enumerate(segments):
            for ch in seg.get("text", ""):
                if is_content(ch):
                    seg_content.append((seg_idx, ch))

        if not punct_content or not seg_content:
            return segments

        # difflib 對齊：seg 內容字 index → punct 內容字 index（容忍增刪改）
        sm = difflib.SequenceMatcher(
            a=[c for _, c in seg_content], b=[c for _, c in punct_content], autojunk=False
        )
        map_arr: List = [None] * len(seg_content)
        for tag, i1, i2, j1, _j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    map_arr[i1 + k] = j1 + k
            elif tag in ("replace", "delete"):
                # seg 這段字對到 punct 區塊起點（clamp）；'insert' 的 punct 多字由 slice 自然涵蓋
                jj = min(j1, len(punct_content) - 1)
                for k in range(i1, i2):
                    map_arr[k] = jj
        # 補未對到的（保險）：用其後第一個有效對應
        nxt = len(punct_content) - 1
        for k in range(len(map_arr) - 1, -1, -1):
            if map_arr[k] is None:
                map_arr[k] = nxt
            else:
                nxt = map_arr[k]

        # 每段第一個內容字在 clean 文字中的位置（強制單調遞增，避免逆序產生負長度 slice）
        positions: List = [None] * len(segments)
        prev = 0
        seen = set()
        for ci, (seg_idx, _) in enumerate(seg_content):
            if seg_idx in seen:
                continue
            seen.add(seg_idx)
            pos = max(punct_content[map_arr[ci]][0], prev)
            positions[seg_idx] = pos
            prev = pos

        result = []
        for seg_idx, seg in enumerate(segments):
            start = positions[seg_idx]
            if start is None:
                result.append({**seg, "text": ""})
                continue
            nxt_start = next(
                (positions[k] for k in range(seg_idx + 1, len(segments)) if positions[k] is not None),
                None,
            )
            if nxt_start is not None and nxt_start > start:
                text = clean[start:nxt_start].rstrip()
            else:
                text = clean[start:].strip()
            result.append({**seg, "text": text})

        return result
    except Exception:
        # 對齊出錯不可打斷轉錄 → 回原始 segments
        return segments


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
