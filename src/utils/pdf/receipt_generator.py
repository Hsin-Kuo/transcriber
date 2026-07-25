"""付款收據 PDF 產生器（ReportLab）。

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


def _fmt_dt(ts) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.utcfromtimestamp(float(ts)) + _TW_OFFSET
        return dt.strftime("%Y-%m-%d %H:%M") + " (UTC+8)"
    except (ValueError, TypeError, OSError):
        return "-"


def _item_desc(order: dict) -> str:
    t = order.get("type")
    tier = (order.get("tier") or "").capitalize()
    cycle = "年繳" if order.get("billing_cycle") == "yearly" else "月繳"
    if t == "extra_quota":
        dur = order.get("extra_duration_minutes") or 0
        ai = order.get("extra_ai_summaries") or 0
        if dur:
            return f"加購：轉錄額度 +{dur} 分鐘"
        if ai:
            return f"加購：AI 摘要 +{ai} 次"
        return "加購額度"
    if t == "upgrade_subscription":
        return f"{tier} 方案（升級）"
    # subscription / renewal / downgrade_subscription
    return f"{tier} 方案（{cycle}）訂閱"


def _invoice_line(user: dict) -> Optional[str]:
    info = user.get("invoice_info") or {}
    if info.get("type") == "personal" and info.get("carrier_num"):
        return f"手機條碼載具　{info['carrier_num']}"
    if info.get("type") == "company" and info.get("company_tax_id"):
        name = info.get("company_name") or ""
        return f"統一編號　{info['company_tax_id']}　{name}".rstrip()
    return None


def generate_receipt_pdf(*, order: dict, user: dict) -> bytes:
    """產生單筆訂單的付款收據 PDF，回傳 bytes。"""
    preload_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title="SoundLite 付款收據",
    )

    base = ParagraphStyle("base", fontName=FONT_TC, fontSize=10, leading=15, textColor=colors.HexColor("#333333"))
    title = ParagraphStyle("title", parent=base, fontSize=20, leading=24, textColor=colors.black)
    label = ParagraphStyle("label", parent=base, textColor=colors.HexColor("#888888"))
    footer = ParagraphStyle("footer", parent=base, fontSize=8.5, leading=13, textColor=colors.HexColor("#888888"))
    amount_r = ParagraphStyle("amt", parent=base, alignment=2)  # right
    total_style = ParagraphStyle("total", parent=base, fontSize=13, leading=18, textColor=colors.black)
    total_r = ParagraphStyle("totalr", parent=total_style, alignment=2)

    story = []

    # ── 標題列：付款收據（左）+ 黑色 logo（右上角）──
    logo_cell = ""
    if os.path.exists(_LOGO_PATH):
        img = Image(_LOGO_PATH, width=13 * mm, height=13 * mm)
        img.hAlign = "RIGHT"
        logo_cell = img
    header = Table(
        [[Paragraph("付款收據", title), logo_cell]],
        colWidths=[None, 16 * mm],
    )
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
        ("收據編號", order.get("merchant_order_no", "-")),
        ("付款日期", _fmt_dt(order.get("paid_at") or order.get("created_at"))),
        ("交易序號", order.get("trade_id") or "-"),
        ("買受人", user.get("email", "-")),
    ]
    inv = _invoice_line(user)
    if inv:
        meta_rows.append(("發票資訊", inv))
    meta_data = [[Paragraph(k, label), Paragraph(str(v), base)] for k, v in meta_rows]
    meta = Table(meta_data, colWidths=[26 * mm, None])
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
    label_r = ParagraphStyle("label_r", parent=label, alignment=2)  # 右對齊表頭
    items = Table(
        [
            [Paragraph("項目", label), Paragraph("金額", label_r)],
            [Paragraph(_item_desc(order), base), Paragraph(amt_str, amount_r)],
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
    total = Table(
        [[Paragraph("合計", total_style), Paragraph(amt_str, total_r)]],
        colWidths=[None, 40 * mm],
    )
    total.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(total)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("付款方式　信用卡", base))
    story.append(Spacer(1, 10 * mm))

    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e0e0e0")))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("本收據為付款證明，非統一發票；統一發票將另行開立。", footer))
    story.append(Paragraph("SoundLite　語音轉文字平台　soundlite.app", footer))

    doc.build(story)
    return buf.getvalue()
