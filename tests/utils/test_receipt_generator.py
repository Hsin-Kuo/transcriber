"""付款收據 PDF 產生器測試（不比對像素，驗證產出有效 PDF + 項目描述邏輯）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.pdf.receipt_generator import generate_receipt_pdf, _item_desc, _invoice_line  # noqa: E402


def _order(**over):
    base = {
        "merchant_order_no": "SLSUB1", "type": "subscription", "tier": "pro",
        "billing_cycle": "monthly", "amount_twd": 999, "trade_id": "PT1", "paid_at": 1784880548.0,
    }
    base.update(over)
    return base


class TestItemDesc:
    def test_subscription(self):
        assert "Pro" in _item_desc(_order(tier="pro", billing_cycle="monthly"))
        assert "月繳" in _item_desc(_order(billing_cycle="monthly"))
        assert "年繳" in _item_desc(_order(billing_cycle="yearly"))

    def test_upgrade(self):
        assert "升級" in _item_desc(_order(type="upgrade_subscription", tier="pro"))

    def test_extra_duration(self):
        assert "60 分鐘" in _item_desc(_order(type="extra_quota", tier=None, billing_cycle=None, extra_duration_minutes=60))

    def test_extra_ai(self):
        assert "10 次" in _item_desc(_order(type="extra_quota", tier=None, billing_cycle=None, extra_ai_summaries=10))


class TestInvoiceLine:
    def test_personal_carrier(self):
        assert "/ABC1234" in _invoice_line({"invoice_info": {"type": "personal", "carrier_num": "/ABC1234"}})

    def test_company(self):
        line = _invoice_line({"invoice_info": {"type": "company", "company_tax_id": "12345678", "company_name": "測試公司"}})
        assert "12345678" in line and "測試公司" in line

    def test_none(self):
        assert _invoice_line({}) is None


class TestGeneratePdf:
    def test_produces_valid_pdf(self):
        pdf = generate_receipt_pdf(order=_order(), user={"email": "u@x.com", "invoice_info": {"type": "personal", "carrier_num": "/ABC1234"}})
        assert pdf[:5] == b"%PDF-"       # PDF magic
        assert len(pdf) > 2000

    def test_extra_quota_pdf(self):
        pdf = generate_receipt_pdf(
            order=_order(type="extra_quota", tier=None, billing_cycle=None, amount_twd=39, extra_duration_minutes=60),
            user={"email": "u@x.com"},
        )
        assert pdf[:5] == b"%PDF-"

    def test_missing_fields_no_crash(self):
        pdf = generate_receipt_pdf(order={"merchant_order_no": "X", "amount_twd": 0}, user={})
        assert pdf[:5] == b"%PDF-"
