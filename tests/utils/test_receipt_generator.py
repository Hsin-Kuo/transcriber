"""付款收據 PDF 產生器測試（中英雙語）。不比對像素，驗證有效 PDF + 項目描述邏輯。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.pdf.receipt_generator import (  # noqa: E402
    generate_receipt_pdf, _item_desc, _invoice_line, _payment_method, _lang,
)

ZH = _lang("zh-TW")
EN = _lang("en")


def _order(**over):
    base = {
        "merchant_order_no": "SLSUB1", "type": "subscription", "tier": "pro",
        "billing_cycle": "monthly", "amount_twd": 999, "trade_id": "PT1", "paid_at": 1784880548.0,
    }
    base.update(over)
    return base


class TestItemDesc:
    def test_subscription_zh(self):
        d = _item_desc(_order(tier="pro", billing_cycle="monthly"), ZH)
        assert "Pro" in d and "月繳" in d
        assert "年繳" in _item_desc(_order(billing_cycle="yearly"), ZH)

    def test_subscription_en(self):
        d = _item_desc(_order(tier="pro", billing_cycle="monthly"), EN)
        assert "Pro Plan" in d and "Monthly" in d and "Subscription" in d
        assert "Yearly" in _item_desc(_order(billing_cycle="yearly"), EN)

    def test_upgrade(self):
        assert "升級" in _item_desc(_order(type="upgrade_subscription"), ZH)
        assert "Upgrade" in _item_desc(_order(type="upgrade_subscription"), EN)

    def test_extra(self):
        o = _order(type="extra_quota", tier=None, billing_cycle=None, extra_duration_minutes=60)
        assert "60 分鐘" in _item_desc(o, ZH)
        assert "+60 transcription minutes" in _item_desc(o, EN)
        o2 = _order(type="extra_quota", tier=None, billing_cycle=None, extra_ai_summaries=10)
        assert "10 次" in _item_desc(o2, ZH)
        assert "+10 AI summaries" in _item_desc(o2, EN)


class TestInvoiceLine:
    def test_personal(self):
        assert "/ABC1234" in _invoice_line({"invoice_info": {"type": "personal", "carrier_num": "/ABC1234"}}, ZH)

    def test_company(self):
        line = _invoice_line({"invoice_info": {"type": "company", "company_tax_id": "12345678", "company_name": "測試"}}, EN)
        assert "12345678" in line and "Tax ID" in line

    def test_none(self):
        assert _invoice_line({}, ZH) is None


class TestPaymentMethod:
    def test_brand_and_last4(self):
        assert _payment_method({"card_brand": "VISA", "card_last4": "8452"}, ZH).endswith("VISA - 8452")
        assert _payment_method({"card_brand": "MasterCard", "card_last4": "1234"}, EN).endswith("MasterCard - 1234")

    def test_last4_only(self):
        assert "•••• 8452" in _payment_method({"card_last4": "8452"}, ZH)

    def test_fallback(self):
        assert "信用卡" in _payment_method({}, ZH)
        assert "Credit Card" in _payment_method({}, EN)


class TestGeneratePdf:
    def test_zh(self):
        pdf = generate_receipt_pdf(order=_order(), user={"email": "u@x.com"}, lang="zh-TW")
        assert pdf[:5] == b"%PDF-" and len(pdf) > 2000

    def test_en(self):
        pdf = generate_receipt_pdf(order=_order(), user={"email": "u@x.com"}, lang="en")
        assert pdf[:5] == b"%PDF-" and len(pdf) > 2000

    def test_default_lang(self):
        pdf = generate_receipt_pdf(order=_order(), user={"email": "u@x.com"})
        assert pdf[:5] == b"%PDF-"

    def test_missing_fields_no_crash(self):
        pdf = generate_receipt_pdf(order={"merchant_order_no": "X", "amount_twd": 0}, user={}, lang="en")
        assert pdf[:5] == b"%PDF-"


class TestMarkupInjection:
    """金流體檢 P0-4：company_name / trade_id 等使用者/外部可控欄位含 ReportLab markup
    時不得被當標籤解析（<img src> → SSRF；壞 markup → 500）。escape 後應正常產出 PDF。"""

    def test_company_name_with_img_markup_no_crash(self):
        user = {"email": "u@x.com", "invoice_info": {
            "type": "company", "company_tax_id": "12345678",
            "company_name": '<img src="http://169.254.169.254/latest/meta-data/" width="1"/>',
        }}
        pdf = generate_receipt_pdf(order=_order(), user=user, lang="zh-TW")
        assert pdf[:5] == b"%PDF-"  # 未因外部資源抓取失敗而 500，且不發出對外請求

    def test_trade_id_with_markup_no_crash(self):
        pdf = generate_receipt_pdf(
            order=_order(trade_id='<link href="file:///etc/passwd"/>'),
            user={"email": "u@x.com"}, lang="en",
        )
        assert pdf[:5] == b"%PDF-"

    def test_external_schemes_disabled(self):
        from reportlab import rl_config
        assert rl_config.trustedSchemes == []
