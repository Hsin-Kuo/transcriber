"""subscriptions.py 發票欄位驗證 + `_handle_invoice_save` 覆蓋語意單測（設計 §3.3）。

直接測 Pydantic request model 與 router 內部 helper，不經 FastAPI TestClient/Mongo，
比照 test_subscriptions_callback.py 的風格。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")
os.environ.setdefault("SMILEPAY_GRVC", "SEI1004730")
os.environ.setdefault("SMILEPAY_VERIFY_KEY", "7C623AEFC6C2AEB7F11047CD29B50F4E")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError  # noqa: E402

from src.routers import subscriptions as subs  # noqa: E402


# ── request model 驗證（設計 §3.3.1）─────────────────────────────────────────

class TestCheckoutRequestValidation:
    def test_valid_personal_with_carrier(self):
        req = subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="personal",
                                    carrier_num="/AB12345")
        assert req.carrier_num == "/AB12345"

    def test_invalid_carrier_format_rejected(self):
        with pytest.raises(ValidationError):
            subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="personal",
                                  carrier_num="not-a-carrier")

    def test_valid_company_tax_id(self):
        req = subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="company",
                                    company_tax_id="12345678", company_name="測試公司")
        assert req.company_tax_id == "12345678"

    def test_invalid_company_tax_id_rejected(self):
        with pytest.raises(ValidationError):
            subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="company",
                                  company_tax_id="123", company_name="測試公司")

    def test_company_without_name_rejected(self):
        with pytest.raises(ValidationError):
            subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="company",
                                  company_tax_id="12345678")

    def test_no_invoice_fields_is_fine(self):
        req = subs.CheckoutRequest(tier="pro", billing="monthly")
        assert req.invoice_type is None


class TestPurchaseExtraRequestValidation:
    """PurchaseExtraRequest 共用同一組 pattern（三個 request model 各自定義，設計未要求合併）。"""

    def test_invalid_carrier_rejected(self):
        with pytest.raises(ValidationError):
            subs.PurchaseExtraRequest(package_id="p1", invoice_type="personal", carrier_num="bad")

    def test_company_without_name_rejected(self):
        with pytest.raises(ValidationError):
            subs.PurchaseExtraRequest(package_id="p1", invoice_type="company", company_tax_id="12345678")


# ── _handle_invoice_save：整包覆蓋語意（設計 §3.3.2）─────────────────────────

class TestHandleInvoiceSave:
    async def test_personal_without_carrier_clears_company_fields(self):
        """修正重點：型態切回 personal 但沒帶 carrier_num 時，過去不會呼叫 update（殘留舊值）；
        現在應整包覆蓋清空 company 欄位。
        """
        user_repo = MagicMock()
        user_repo.update_invoice_info = AsyncMock(return_value=True)
        req = subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="personal", save_invoice=True)
        await subs._handle_invoice_save(req, "u1", user_repo)
        user_repo.update_invoice_info.assert_awaited_once()
        saved = user_repo.update_invoice_info.await_args.args[1]
        assert saved == {
            "type": "personal", "carrier_type": "1", "carrier_num": "",
            "company_tax_id": "", "company_name": "",
        }

    async def test_company_overwrite_clears_carrier_fields(self):
        user_repo = MagicMock()
        user_repo.update_invoice_info = AsyncMock(return_value=True)
        req = subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="company",
                                    company_tax_id="12345678", company_name="測試公司", save_invoice=True)
        await subs._handle_invoice_save(req, "u1", user_repo)
        saved = user_repo.update_invoice_info.await_args.args[1]
        assert saved["type"] == "company"
        assert saved["carrier_type"] == "" and saved["carrier_num"] == ""
        assert saved["company_tax_id"] == "12345678"

    async def test_save_invoice_false_skips_write(self):
        user_repo = MagicMock()
        user_repo.update_invoice_info = AsyncMock(return_value=True)
        req = subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="personal", save_invoice=False)
        await subs._handle_invoice_save(req, "u1", user_repo)
        user_repo.update_invoice_info.assert_not_awaited()

    async def test_no_invoice_type_skips_write(self):
        user_repo = MagicMock()
        user_repo.update_invoice_info = AsyncMock(return_value=True)
        req = subs.CheckoutRequest(tier="pro", billing="monthly", save_invoice=True)
        await subs._handle_invoice_save(req, "u1", user_repo)
        user_repo.update_invoice_info.assert_not_awaited()


# ── invoice_snapshot 建構整合（checkout 用 request 直組；不需 key 對映）───────

class TestInvoiceSnapshotFromCheckoutRequest:
    def test_personal_snapshot_shape(self):
        from src.services.invoice_service import build_invoice_snapshot_from_request
        req = subs.CheckoutRequest(tier="pro", billing="monthly", invoice_type="personal",
                                    carrier_num="/AB12345")
        snap = build_invoice_snapshot_from_request(req)
        assert snap == {
            "invoice_type": "personal", "carrier_type": None, "carrier_num": "/AB12345",
            "company_tax_id": None, "company_name": None,
        }
