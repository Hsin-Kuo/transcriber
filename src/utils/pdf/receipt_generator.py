"""付款收據 PDF 產生器（ReportLab，中英雙語）。

注意：這是「付款收據」（付款證明），**非統一發票**。統一發票須另接 ezPay 開立。
重用 pdf_generator 的字體註冊（NotoSansTC，涵蓋中英）。右上角為黑色品牌 logo。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as _canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle

from .pdf_generator import preload_fonts
from .script_detect import FONT_TC

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "soundlite_logo_black.png")
_TW_OFFSET = timedelta(hours=8)  # Asia/Taipei（無 DST）

# 中英字串
_STR = {
    "zh-TW": {
        "title": "付款收據",
        "receipt_no": "收據編號",
        "date": "付款日期",
        "trade_no": "交易序號",
        "buyer": "買受人",
        "invoice": "發票資訊",
        "item": "項目",
        "amount": "金額",
        "total": "合計",
        "payment_label": "付款方式",
        "credit_card": "信用卡",
        "carrier": "手機條碼載具",
        "uni_no": "統一編號",
        "disclaimer": "本收據為付款證明，非統一發票；統一發票將另行開立。",
        "brand": "SoundLite　語音轉文字平台　soundlite.app",
        "page_fmt": "第 {page} 頁，共 {total} 頁",
        "monthly": "月繳",
        "yearly": "年繳",
        "sub_fmt": "{tier} 方案（{cycle}）訂閱",
        "upgrade_fmt": "{tier} 方案（升級）",
        "extra_dur_fmt": "加購：轉錄額度 +{n} 分鐘",
        "extra_ai_fmt": "加購：AI 摘要 +{n} 次",
        "extra_generic": "加購額度",
    },
    "en": {
        "title": "Payment Receipt",
        "receipt_no": "Receipt No.",
        "date": "Payment Date",
        "trade_no": "Transaction ID",
        "buyer": "Billed To",
        "invoice": "Invoice Info",
        "item": "Item",
        "amount": "Amount",
        "total": "Total",
        "payment_label": "Payment Method",
        "credit_card": "Credit Card",
        "carrier": "Mobile Barcode Carrier",
        "uni_no": "Tax ID",
        "disclaimer": "This is a payment receipt, not an official tax invoice (GUI); a tax invoice will be issued separately.",
        "brand": "SoundLite   Speech-to-Text Platform   soundlite.app",
        "page_fmt": "Page {page} of {total}",
        "monthly": "Monthly",
        "yearly": "Yearly",
        "sub_fmt": "{tier} Plan ({cycle}) Subscription",
        "upgrade_fmt": "{tier} Plan (Upgrade)",
        "extra_dur_fmt": "Add-on: +{n} transcription minutes",
        "extra_ai_fmt": "Add-on: +{n} AI summaries",
        "extra_generic": "Add-on quota",
    },
}


def _lang(lang: Optional[str]) -> dict:
    return _STR.get(lang or "zh-TW", _STR["zh-TW"])


def _make_numbered_canvas(page_fmt: str):
    """回傳一個 Canvas 子類：兩趟繪製，於每頁底部畫分隔線 + 「Page X of Y」（需總頁數）。"""
    class _NumberedCanvas(_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_states = []

        def showPage(self):
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_states)
            for state in self._saved_states:
                self.__dict__.update(state)
                self._draw_page_footer(total)
                super().showPage()
            super().save()

        def _draw_page_footer(self, total):
            w, _ = self._pagesize
            gray = colors.HexColor("#aaaaaa")
            # 分隔線（與上方頁尾內容區隔）
            self.setStrokeColor(gray)
            self.setLineWidth(0.5)
            self.line(22 * mm, 14 * mm, w - 22 * mm, 14 * mm)
            # 頁碼
            self.setFont(FONT_TC, 8)
            self.setFillColor(gray)
            self.drawCentredString(
                w / 2, 9 * mm,
                page_fmt.format(page=self._pageNumber, total=total),
            )

    return _NumberedCanvas


def _fmt_dt(ts) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.utcfromtimestamp(float(ts)) + _TW_OFFSET
        return dt.strftime("%Y-%m-%d %H:%M") + " (UTC+8)"
    except (ValueError, TypeError, OSError):
        return "-"


def _item_desc(order: dict, s: dict) -> str:
    t = order.get("type")
    tier = (order.get("tier") or "").capitalize()
    cycle = s["yearly"] if order.get("billing_cycle") == "yearly" else s["monthly"]
    if t == "extra_quota":
        dur = order.get("extra_duration_minutes") or 0
        ai = order.get("extra_ai_summaries") or 0
        if dur:
            return s["extra_dur_fmt"].format(n=dur)
        if ai:
            return s["extra_ai_fmt"].format(n=ai)
        return s["extra_generic"]
    if t == "upgrade_subscription":
        return s["upgrade_fmt"].format(tier=tier)
    return s["sub_fmt"].format(tier=tier, cycle=cycle)


def _payment_method(order: dict, s: dict) -> str:
    """付款方式行：有卡別+末四碼 → 「VISA - 8452」；否則「信用卡 / Credit Card」。"""
    brand = order.get("card_brand")
    last4 = order.get("card_last4")
    if brand and last4:
        method = f"{brand} - {last4}"
    elif last4:
        method = f"•••• {last4}"
    else:
        method = s["credit_card"]
    return f"{s['payment_label']}　{method}"


def _invoice_line(user: dict, s: dict) -> Optional[str]:
    info = user.get("invoice_info") or {}
    if info.get("type") == "personal" and info.get("carrier_num"):
        return f"{s['carrier']}　{info['carrier_num']}"
    if info.get("type") == "company" and info.get("company_tax_id"):
        name = info.get("company_name") or ""
        return f"{s['uni_no']}　{info['company_tax_id']}　{name}".rstrip()
    return None


def generate_receipt_pdf(*, order: dict, user: dict, lang: str = "zh-TW") -> bytes:
    """產生單筆訂單的付款收據 PDF（lang: 'zh-TW' | 'en'），回傳 bytes。"""
    s = _lang(lang)
    preload_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"SoundLite {s['title']}",
    )

    base = ParagraphStyle("base", fontName=FONT_TC, fontSize=10, leading=15, textColor=colors.HexColor("#333333"))
    title = ParagraphStyle("title", parent=base, fontSize=20, leading=24, textColor=colors.black)
    label = ParagraphStyle("label", parent=base, textColor=colors.HexColor("#888888"))
    label_r = ParagraphStyle("label_r", parent=label, alignment=2)
    footer = ParagraphStyle("footer", parent=base, fontSize=8.5, leading=13, textColor=colors.HexColor("#888888"))
    amount_r = ParagraphStyle("amt", parent=base, alignment=2)
    total_style = ParagraphStyle("total", parent=base, fontSize=13, leading=18, textColor=colors.black)
    total_r = ParagraphStyle("totalr", parent=total_style, alignment=2)

    story = []

    # ── 標題列：付款收據（左）+ 黑色 logo（右上角）──
    logo_cell = ""
    if os.path.exists(_LOGO_PATH):
        img = Image(_LOGO_PATH, width=13 * mm, height=13 * mm)
        img.hAlign = "RIGHT"
        logo_cell = img
    header = Table([[Paragraph(s["title"], title), logo_cell]], colWidths=[None, 16 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e0e0e0")))
    story.append(Spacer(1, 5 * mm))

    # ── Meta ──
    meta_rows = [
        (s["receipt_no"], order.get("merchant_order_no", "-")),
        (s["date"], _fmt_dt(order.get("paid_at") or order.get("created_at"))),
        (s["trade_no"], order.get("trade_id") or "-"),
        (s["buyer"], user.get("email", "-")),
    ]
    inv = _invoice_line(user, s)
    if inv:
        meta_rows.append((s["invoice"], inv))
    meta = Table([[Paragraph(k, label), Paragraph(str(v), base)] for k, v in meta_rows], colWidths=[30 * mm, None])
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(meta)
    story.append(Spacer(1, 6 * mm))

    # ── 明細 ──
    amt = int(order.get("amount_twd") or 0)
    amt_str = f"NT$ {amt:,}"
    items = Table(
        [
            [Paragraph(s["item"], label), Paragraph(s["amount"], label_r)],
            [Paragraph(_item_desc(order, s), base), Paragraph(amt_str, amount_r)],
        ],
        colWidths=[None, 40 * mm],
    )
    items.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cccccc")),
        ("LINEBELOW", (0, 1), (-1, 1), 0.5, colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(items)
    story.append(Spacer(1, 2 * mm))

    # ── 合計 + 付款方式 ──
    total = Table([[Paragraph(s["total"], total_style), Paragraph(amt_str, total_r)]], colWidths=[None, 40 * mm])
    total.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(total)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(_payment_method(order, s), base))
    story.append(Spacer(1, 10 * mm))

    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e0e0e0")))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(s["disclaimer"], footer))
    story.append(Paragraph(s["brand"], footer))

    doc.build(story, canvasmaker=_make_numbered_canvas(s["page_fmt"]))
    return buf.getvalue()
