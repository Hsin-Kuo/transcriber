"""Unicode 字符 → 應該用哪個 Noto Sans CJK 字體。

ReportLab Paragraph 用 inline `<font name=...>` tag 切換字體。我們把連續同
script 的字元 group 成一個 chunk，每個 chunk 套對應字體，輸出一段 mixed-font
HTML 給 ReportLab 渲染。

判定規則（純 Unicode range）：
- Hiragana / Katakana → JP
- Hangul → KR
- CJK Han ideographs → 依 primary_lang 選 TC/SC/JP/KR（漢字字形差異）
- Latin / 其他 → 預設 TC（NotoSans CJK 自帶 Latin glyph，免得跨字體跳行高不一）
"""
from __future__ import annotations
from enum import Enum
from html import escape
from typing import Iterable


class Script(Enum):
    LATIN = "latin"
    CJK_HAN = "cjk_han"
    HIRAGANA = "hiragana"
    KATAKANA = "katakana"
    HANGUL = "hangul"
    OTHER = "other"


# 4 個字體名稱與 ReportLab pdfmetrics.registerFont 註冊時一致
FONT_TC = "NotoSansTC"
FONT_SC = "NotoSansSC"
FONT_JP = "NotoSansJP"
FONT_KR = "NotoSansKR"

_LANG_TO_HAN_FONT = {
    "zh-TW": FONT_TC, "zh-Hant": FONT_TC, "zh": FONT_TC,
    "zh-CN": FONT_SC, "zh-Hans": FONT_SC,
    "ja": FONT_JP, "ja-JP": FONT_JP,
    "ko": FONT_KR, "ko-KR": FONT_KR,
}


def detect_char_script(ch: str) -> Script:
    """單字元 → Script。"""
    cp = ord(ch)
    # 高頻 ASCII 先判（performance）
    if cp < 0x80:
        return Script.LATIN
    if 0x3040 <= cp <= 0x309F:
        return Script.HIRAGANA
    if 0x30A0 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
        return Script.KATAKANA
    if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0xA960 <= cp <= 0xA97F:
        return Script.HANGUL
    # CJK Unified Ideographs (basic + ext A + ext B/C/D/E/F via supplementary plane)
    if (0x4E00 <= cp <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0x20000 <= cp <= 0x2FFFF
            or 0xF900 <= cp <= 0xFAFF):  # Compatibility Ideographs
        return Script.CJK_HAN
    # Latin Extended、希臘、Cyrillic 等通通歸 LATIN（這些 Noto CJK 也 cover）
    if cp < 0x0500:
        return Script.LATIN
    return Script.OTHER


def font_for_script(script: Script, primary_lang: str = "zh-TW") -> str:
    """Script → 字體名（已註冊到 ReportLab pdfmetrics）。"""
    if script == Script.HIRAGANA or script == Script.KATAKANA:
        return FONT_JP
    if script == Script.HANGUL:
        return FONT_KR
    if script == Script.CJK_HAN:
        # 漢字字形依文檔主語言：簡繁日韓共用同一個 code point，但字形不同
        return _LANG_TO_HAN_FONT.get(primary_lang, FONT_TC)
    # Latin / Other：用主語言對應的 CJK 字體（自帶 Latin glyph），避免字體切換
    return _LANG_TO_HAN_FONT.get(primary_lang, FONT_TC)


# ── 字型涵蓋 fallback ──────────────────────────────────────────
# 各 Noto 字型實際涵蓋的 codepoints，由 pdf_generator.preload_fonts 在 ReportLab 註冊字型後
# 填入（取自 font.face.charToGlyph）。用途：NotoSansTC 缺部分簡體字（这/简…），單純依
# primary_lang 把所有漢字都導到 TC 會讓那些字變豆腐 → 逐字檢查涵蓋、缺則 fallback。
_FONT_COVERAGE: dict[str, frozenset] = {}

# fallback 順序：NotoSansSC 是 CJK superset（TC+SC 全包）擺第一，補得最齊；其餘依序。
_FALLBACK_ORDER = (FONT_SC, FONT_TC, FONT_JP, FONT_KR)


def register_font_coverage(name: str, codepoints) -> None:
    """登記某字型涵蓋的 codepoints（供 resolve_font fallback）。pdf_generator 註冊字型後呼叫。"""
    _FONT_COVERAGE[name] = frozenset(codepoints)


def resolve_font(preferred: str, codepoint: int) -> str:
    """首選字型涵蓋此字 → 用首選；否則 fallback 到第一個涵蓋它的字型；都沒有/未建表 → 回首選。"""
    if not _FONT_COVERAGE:
        return preferred  # 涵蓋表未建立（理論上 preload 後才用）→ 保持原行為，不退化
    if codepoint in _FONT_COVERAGE.get(preferred, frozenset()):
        return preferred
    for name in _FALLBACK_ORDER:
        if codepoint in _FONT_COVERAGE.get(name, frozenset()):
            return name
    return preferred


def wrap_text_with_font_tags(text: str, primary_lang: str = "zh-TW") -> str:
    """把字串切成同 script 連續 chunk，每段包 <font name=...> tag。

    輸出可直接餵給 ReportLab Paragraph。HTML 特殊字元（&<>）會被 escape。
    換行 \n → <br/> 給 ReportLab 換行。
    """
    if not text:
        return ""

    out_parts: list[str] = []
    current_font: str | None = None
    current_buf: list[str] = []

    def flush():
        if current_buf and current_font:
            # escape 內容防 ReportLab markup 衝突，再用 font tag 包起來
            escaped = escape("".join(current_buf)).replace("\n", "<br/>")
            out_parts.append(f"<font name=\"{current_font}\">{escaped}</font>")

    for ch in text:
        script = detect_char_script(ch)
        # 先依 script/primary_lang 選字型，再逐字確認該字型真的有這個字、缺則 fallback
        font = resolve_font(font_for_script(script, primary_lang), ord(ch))
        if font != current_font:
            flush()
            current_font = font
            current_buf = [ch]
        else:
            current_buf.append(ch)
    flush()

    return "".join(out_parts)


def primary_font_for_lang(primary_lang: str = "zh-TW") -> str:
    """文檔預設字體（套在 ParagraphStyle 上，作為沒切到 font tag 時的 fallback）。"""
    return _LANG_TO_HAN_FONT.get(primary_lang, FONT_TC)
