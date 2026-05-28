"""ReportLab PDF generator — 對齊 frontend pdfmake (useTranscriptDownload.js)
的 doc 結構與樣式。

Public API:
    generate_pdf(...) -> bytes

字體在 module import 時 lazy register（首次呼叫 generate_pdf 時觸發），
避免 import 階段就 IO。
"""
from __future__ import annotations
import os
import threading
from io import BytesIO
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from .script_detect import (
    FONT_JP,
    FONT_KR,
    FONT_SC,
    FONT_TC,
    primary_font_for_lang,
    wrap_text_with_font_tags,
)

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_REGISTER_LOCK = threading.Lock()
_REGISTERED = False


def _register_fonts() -> None:
    """Idempotent + thread-safe font registration."""
    global _REGISTERED
    if _REGISTERED:
        return
    with _REGISTER_LOCK:
        if _REGISTERED:
            return
        for name in (FONT_TC, FONT_SC, FONT_JP, FONT_KR):
            path = os.path.join(_FONTS_DIR, f"{name}-Regular.ttf")
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"PDF font missing: {path}. "
                    "Run tools/build-fonts.sh to regenerate."
                )
            pdfmetrics.registerFont(TTFont(name, path))
        _REGISTERED = True


# i18n 字串（backend 不接 vue-i18n，直接 hardcode 兩個 locale，足以對應 frontend）
_I18N: dict[str, dict[str, str]] = {
    "zh-TW": {
        "aiSummary.title": "AI 摘要",
        "aiSummary.type": "類型",
        "aiSummary.executiveSummary": "摘要",
        "aiSummary.keyPoints": "重點",
        "aiSummary.contentSegments": "內容段落",
        "aiSummary.keywords": "關鍵詞",
        "aiSummary.actionItems": "待辦事項",
        "downloadDialog.transcriptSection": "逐字稿",
    },
    "en": {
        "aiSummary.title": "AI Summary",
        "aiSummary.type": "Type",
        "aiSummary.executiveSummary": "Executive Summary",
        "aiSummary.keyPoints": "Key Points",
        "aiSummary.contentSegments": "Content Segments",
        "aiSummary.keywords": "Keywords",
        "aiSummary.actionItems": "Action Items",
        "downloadDialog.transcriptSection": "Transcript",
    },
}


def _t(key: str, locale: str) -> str:
    table = _I18N.get(locale) or _I18N["en"]
    return table.get(key) or _I18N["en"].get(key) or key


def _build_styles(primary_font: str) -> dict[str, ParagraphStyle]:
    """ParagraphStyle 對齊 frontend useTranscriptDownload.js 的 hasChineseFont 分支。"""
    return {
        "title": ParagraphStyle(
            "title", fontName=primary_font, fontSize=20, leading=26,
            textColor=HexColor("#333333"), spaceAfter=20,
        ),
        "sectionHeader": ParagraphStyle(
            "sectionHeader", fontName=primary_font, fontSize=16, leading=22,
            textColor=HexColor("#444444"), spaceAfter=12,
        ),
        "subHeader": ParagraphStyle(
            "subHeader", fontName=primary_font, fontSize=13, leading=18,
            textColor=HexColor("#555555"), spaceBefore=8, spaceAfter=6,
        ),
        "topicTitle": ParagraphStyle(
            "topicTitle", fontName=primary_font, fontSize=14, leading=20,
            textColor=HexColor("#333333"), spaceAfter=12,
        ),
        "segmentTitle": ParagraphStyle(
            "segmentTitle", fontName=primary_font, fontSize=12, leading=16,
            textColor=HexColor("#666666"), spaceBefore=6, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", fontName=primary_font, fontSize=11, leading=15.4,
            textColor=HexColor("#333333"), spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "meta", fontName=primary_font, fontSize=10, leading=14,
            textColor=HexColor("#888888"), spaceAfter=8,
        ),
        "keywords": ParagraphStyle(
            "keywords", fontName=primary_font, fontSize=10, leading=14,
            textColor=HexColor("#666666"), spaceAfter=8,
        ),
    }


def _p(text: str, style: ParagraphStyle, primary_lang: str) -> Paragraph:
    """建立 Paragraph：把 text 用 wrap_text_with_font_tags 包好。"""
    return Paragraph(wrap_text_with_font_tags(text, primary_lang), style)


def _summary_flowables(
    summary: dict[str, Any],
    styles: dict[str, ParagraphStyle],
    primary_lang: str,
    locale: str,
) -> list[Any]:
    """對應 frontend formatSummaryForPdf()。

    summary 結構（同 frontend）：
    {
        "content": {
            "meta": {"type": "...", "detected_topic": "..."},
            "summary": "...",
            "key_points" | "highlights": [...],
            "segments": [{"topic": "...", "content": "...", "keywords": [...]}],
            "action_items": [{"task": "...", "owner": "...", "deadline": "..."}],
        }
    }
    """
    out: list[Any] = []
    content = (summary or {}).get("content")
    if not content:
        return out

    out.append(_p(_t("aiSummary.title", locale), styles["sectionHeader"], primary_lang))

    meta = content.get("meta") or {}
    if meta.get("type"):
        meta_text = f"{_t('aiSummary.type', locale)}: {meta['type']}"
        out.append(_p(meta_text, styles["meta"], primary_lang))
    if meta.get("detected_topic"):
        out.append(_p(meta["detected_topic"], styles["topicTitle"], primary_lang))

    if content.get("summary"):
        out.append(_p(_t("aiSummary.executiveSummary", locale), styles["subHeader"], primary_lang))
        out.append(_p(content["summary"], styles["body"], primary_lang))

    key_points_raw = content.get("key_points") or content.get("highlights") or []
    key_points: list[str] = []
    for p in key_points_raw:
        if isinstance(p, str):
            key_points.append(p)
        elif isinstance(p, dict):
            key_points.append(p.get("text") or p.get("point") or p.get("content") or "")
    key_points = [p for p in key_points if p]
    if key_points:
        out.append(_p(_t("aiSummary.keyPoints", locale), styles["subHeader"], primary_lang))
        out.append(ListFlowable(
            [ListItem(_p(p, styles["body"], primary_lang)) for p in key_points],
            bulletType="bullet", leftIndent=18, bulletFontName=primary_font_for_lang(primary_lang),
        ))

    segments = content.get("segments") or []
    if segments:
        out.append(_p(_t("aiSummary.contentSegments", locale), styles["subHeader"], primary_lang))
        for seg in segments:
            if seg.get("topic"):
                out.append(_p(seg["topic"], styles["segmentTitle"], primary_lang))
            if seg.get("content"):
                out.append(_p(seg["content"], styles["body"], primary_lang))
            keywords = seg.get("keywords") or []
            if keywords:
                kw_text = f"{_t('aiSummary.keywords', locale)}: {', '.join(keywords)}"
                out.append(_p(kw_text, styles["keywords"], primary_lang))

    action_items = content.get("action_items") or []
    if action_items:
        out.append(_p(_t("aiSummary.actionItems", locale), styles["subHeader"], primary_lang))
        action_strs = []
        for item in action_items:
            task = item.get("task", "")
            extras = [v for v in (item.get("owner"), item.get("deadline")) if v]
            if extras:
                task = f"{task} ({' / '.join(extras)})"
            if task:
                action_strs.append(task)
        if action_strs:
            out.append(ListFlowable(
                [ListItem(_p(s, styles["body"], primary_lang)) for s in action_strs],
                bulletType="bullet", leftIndent=18,
                bulletFontName=primary_font_for_lang(primary_lang),
            ))

    out.append(Spacer(1, 12))
    out.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#cccccc")))
    out.append(Spacer(1, 12))
    return out


def _transcript_flowables(
    transcript_text: str,
    styles: dict[str, ParagraphStyle],
    primary_lang: str,
    locale: str,
) -> list[Any]:
    """對應 frontend formatTranscriptForPdf()."""
    out: list[Any] = [
        _p(_t("downloadDialog.transcriptSection", locale), styles["sectionHeader"], primary_lang)
    ]
    for line in transcript_text.split("\n"):
        if line.strip():
            out.append(_p(line, styles["body"], primary_lang))
        else:
            out.append(Spacer(1, 4))
    return out


def generate_pdf(
    *,
    title: str,
    summary: dict[str, Any] | None = None,
    transcript_text: str | None = None,
    include_summary: bool = True,
    include_transcript: bool = True,
    primary_lang: str = "zh-TW",
    locale: str = "zh-TW",
) -> bytes:
    """產生 PDF bytes。

    Args:
        title: PDF 抬頭（通常是 transcript title 或 filename）
        summary: AI 摘要 dict（{"content": {...}}），None 或空則跳過 summary section
        transcript_text: 已格式化的逐字稿純文字（frontend 端先按 paragraph /
                          subtitle mode 處理過），None 或空則跳過 transcript section
        include_summary / include_transcript: 對應 frontend 下載對話框勾選
        primary_lang: 影響漢字字形選擇（zh-TW/zh-CN/ja/ko）
        locale: i18n locale（zh-TW / en），影響 section title 等固定字串
    """
    _register_fonts()

    primary_font = primary_font_for_lang(primary_lang)
    styles = _build_styles(primary_font)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40,
        title=title,
    )

    flowables: list[Any] = [_p(title, styles["title"], primary_lang)]

    if include_summary and summary:
        flowables.extend(_summary_flowables(summary, styles, primary_lang, locale))

    if include_transcript and transcript_text:
        flowables.extend(_transcript_flowables(transcript_text, styles, primary_lang, locale))

    doc.build(flowables)
    return buffer.getvalue()
