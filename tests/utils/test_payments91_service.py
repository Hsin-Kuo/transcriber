"""Payments91APPService 單元測試：簽章公式（Phase 0 sandbox 實證向量）+ request body 組裝。"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# service __init__ 從 env 讀金鑰，先設好再 import 建物件
os.environ.setdefault("PAYMENTS91_API_KEY", "test-api-key")
os.environ.setdefault("PAYMENTS91_SHARED_SECRET", "testsecret")
os.environ.setdefault("PAYMENTS91_PUBLISHABLE_KEY", "test-pk")
os.environ.setdefault("PAYMENTS91_STORE_CODE", "STORE01")

from src.utils.payments91_service import (  # noqa: E402
    Payments91APPService,
    interpret_record_status,
)


class TestInterpretRecordStatus:
    """recordStatus（付款結果）判讀——別誤用查詢層的 statusCode。"""

    def test_success_states(self):
        assert interpret_record_status(4) == "success"   # 付款成功
        assert interpret_record_status(5) == "success"   # 請款成功
        assert interpret_record_status("4") == "success"  # 字串亦可

    def test_failed_states(self):
        assert interpret_record_status(2) == "failed"    # 付款失敗（3D 失敗）
        assert interpret_record_status(3) == "failed"    # 付款取消

    def test_pending_states(self):
        assert interpret_record_status(1) == "pending"   # 待付款
        assert interpret_record_status(8) == "pending"   # 處理中

    def test_refunded_states(self):
        # P1-5：6/7 從 "failed" 拆成獨立的 "refunded" 語意（不再被 mark_failed_unless_paid
        # 的 `$ne paid` 條件式寫入吃掉，見 order_settlement.handle_full_refund/flag_partial_refund）。
        assert interpret_record_status(6) == "refunded"  # 部分退款
        assert interpret_record_status(7) == "refunded"  # 全部退款
        assert interpret_record_status("7") == "refunded"  # 字串亦可

    def test_unknown_is_failed(self):
        assert interpret_record_status(None) == "failed"
        assert interpret_record_status("") == "failed"
        assert interpret_record_status("Success") == "failed"  # 誤把查詢 statusCode 丟進來 → 保守判失敗


def _svc():
    return Payments91APPService()


class TestSignature:
    def test_sign_matches_phase0_vector(self):
        # Phase 0 sandbox 實測：shared_secret="testsecret" + '{"a":1}' 的簽章。
        # 在 instance 上設 secret，不依賴全域 env（避免跨 test 檔 setdefault 汙染）。
        svc = _svc()
        svc.shared_secret = "testsecret"
        expected = (
            "MGY0YTYwNGE5ZTlhZDE4MjAzNGIzMjI0ZmI2MTcyNGE5ZWYxMjdjMmQ1ZGUz"
            "NTU0OTk1Y2MzMWY5Y2MzYzQ5OQ=="
        )
        assert svc._sign('{"a":1}') == expected

    def test_sign_is_base64_of_lowercase_hex(self):
        import base64, hashlib, hmac
        svc = _svc()
        svc.shared_secret = "testsecret"
        payload = '{"merchantOrderId":"SLSUB1"}'
        h = hmac.new(b"testsecret", payload.encode(), hashlib.sha256).hexdigest()
        assert base64.b64decode(svc._sign(payload)).decode() == h  # 還原回小寫 hex
        assert h == h.lower()


class TestEnvRouting:
    def test_sandbox_base_url_and_sdk_type(self):
        svc = _svc()
        svc.env = "sandbox"
        assert svc.base_url == "https://api.developer.payments.91app.com"
        assert svc.sdk_server_type == "sandbox"

    def test_production_base_url_and_sdk_type(self):
        svc = _svc()
        svc.env = "production"
        assert svc.base_url == "https://api.payments.91app.com"
        assert svc.sdk_server_type == "production"


class TestPricing:
    def test_prices(self):
        p = Payments91APPService.get_subscription_price
        assert p("basic", "monthly") == 299
        assert p("basic", "yearly") == 3289
        assert p("pro", "monthly") == 999
        assert p("pro", "yearly") == 10989
        assert p("free", "monthly") is None


class TestRequestBodies:
    async def test_first_payment_body_uses_binding_card_and_first(self):
        svc = _svc()
        captured = {}

        async def fake_post(path, body, idempotency_key=None):
            captured["path"] = path
            captured["body"] = body
            captured["idem"] = idempotency_key
            return {"statusCode": "Success", "paymentUrl": ""}

        svc._post = fake_post
        await svc.create_first_payment(
            txn_token="TXN", order_no="SLSUB1", consumer_id="u1", amount=299,
            redirect_url="https://x/return", callback_url="https://x/cb", prod_name="SoundLite Basic 方案",
        )
        b = captured["body"]
        assert captured["path"] == "/v2/payments/request-by-txnToken"
        assert captured["idem"] == "SLSUB1"
        assert b["initCardTokenType"] == "BindingCard"        # ★ 非 RememberCard
        assert b["merchantConsumerId"] == "u1"
        assert b["productType"] == "Subscription"
        assert b["extensionInfo"]["subscriptionType"] == "First"
        # 首期 paymentMethods.amount 必須為 0（prod 400 SubscriptionFirstPaymentAmountNotAllowed）,
        # 實際扣款額走 extensionInfo.subscriptionProductInfo.amount
        assert b["paymentMethods"] == [{"payType": "CreditCard", "amount": 0}]
        assert b["extensionInfo"]["subscriptionProductInfo"]["amount"] == 299
        assert b["redirectUrl"] == "https://x/return"
        assert b["callbackUrl"] == "https://x/cb"

    async def test_renewal_body_uses_card_token_and_renewal(self):
        svc = _svc()
        captured = {}

        async def fake_post(path, body, idempotency_key=None):
            captured["path"] = path
            captured["body"] = body
            return {"statusCode": "Success"}

        svc._post = fake_post
        await svc.charge_renewal(
            card_token="CT1", consumer_id="u1", order_no="SLREN1", amount=299,
            redirect_url="https://x/return", callback_url="https://x/cb", prod_name="SoundLite Basic 方案",
        )
        b = captured["body"]
        assert captured["path"] == "/v2/payments/request-by-cardToken"
        assert b["cardToken"] == "CT1"
        assert b["merchantConsumerId"] == "u1"
        assert b["productType"] == "Subscription"
        assert b["extensionInfo"]["subscriptionType"] == "Renewal"  # ★ 免 3D 關鍵
        assert "initCardTokenType" not in b

    # ── subscriptionProductInfo（91APP 正式環境必填，sandbox 不驗；2026-09-01
    #    go-live 首筆實測 400 SubscriptionProductInfoRequired 才炸出）────────────

    async def test_first_payment_includes_subscription_product_info(self):
        svc = _svc()
        captured = {}

        async def fake_post(path, body, idempotency_key=None):
            captured["body"] = body
            return {"statusCode": "Success"}

        svc._post = fake_post
        await svc.create_first_payment(
            txn_token="TXN", order_no="SLSUB1", consumer_id="u1", amount=3289,
            redirect_url="https://x/return", callback_url="https://x/cb",
            prod_name="SoundLite Basic 方案", billing_cycle="yearly",
        )
        spi = captured["body"]["extensionInfo"]["subscriptionProductInfo"]
        assert spi["priceName"] == "SoundLite Basic 方案"
        assert spi["amount"] == 3289
        assert spi["recurring"] == {"type": "Year", "interval": 1}  # 無 periods=無限期

    async def test_first_payment_one_time_uses_periods_1(self):
        """加購（extra_quota）：periods=1 表達單期扣款。"""
        svc = _svc()
        captured = {}

        async def fake_post(path, body, idempotency_key=None):
            captured["body"] = body
            return {"statusCode": "Success"}

        svc._post = fake_post
        await svc.create_first_payment(
            txn_token="TXN", order_no="SLEXT1", consumer_id="u1", amount=39,
            redirect_url="https://x/return", callback_url="https://x/cb",
            prod_name="加購 AI 總結", billing_cycle="monthly", periods=1,
        )
        spi = captured["body"]["extensionInfo"]["subscriptionProductInfo"]
        assert spi["recurring"] == {"type": "Month", "interval": 1, "periods": 1}

    async def test_renewal_includes_subscription_product_info(self):
        svc = _svc()
        captured = {}

        async def fake_post(path, body, idempotency_key=None):
            captured["body"] = body
            return {"statusCode": "Success"}

        svc._post = fake_post
        await svc.charge_renewal(
            card_token="CT1", consumer_id="u1", order_no="SLREN1", amount=299,
            redirect_url="https://x/return", callback_url="https://x/cb",
            prod_name="SoundLite Basic 方案（續扣）", billing_cycle="monthly",
        )
        spi = captured["body"]["extensionInfo"]["subscriptionProductInfo"]
        assert spi["amount"] == 299
        assert spi["recurring"] == {"type": "Month", "interval": 1}
        # subscriptionType 不被 subscriptionProductInfo 蓋掉
        assert captured["body"]["extensionInfo"]["subscriptionType"] == "Renewal"

    async def test_query_trade_signs_get(self):
        svc = _svc()
        captured = {}

        async def fake_get(path_with_query):
            captured["path"] = path_with_query
            return {"statusCode": "Success", "merchantOrderId": "SLSUB1"}

        svc._get = fake_get
        out = await svc.query_trade("PT123")
        assert captured["path"] == "/v2/trades/PT123"
        assert out["merchantOrderId"] == "SLSUB1"


class TestQueryTradeTradeIdValidation:
    """🔴 P1-8：trade_id 來自未認證 callback payload，直接嵌入 path 前需驗證格式（避免注入）。"""

    async def test_invalid_trade_id_raises_without_calling_get(self):
        svc = _svc()
        svc._get = AsyncMock()
        with pytest.raises(ValueError):
            await svc.query_trade("X?merchantOrderId=victim")
        svc._get.assert_not_awaited()

    @pytest.mark.parametrize("non_string_trade_id", [12345, True, ["PT1"], {"x": "PT1"}, None])
    async def test_non_string_trade_id_raises_without_calling_get(self, non_string_trade_id):
        # F2 回歸：query_trade 自身也要守 isinstance，不能只靠 router 那層檢查。
        svc = _svc()
        svc._get = AsyncMock()
        with pytest.raises(ValueError):
            await svc.query_trade(non_string_trade_id)
        svc._get.assert_not_awaited()

    async def test_valid_trade_id_is_quoted_into_path(self):
        svc = _svc()
        captured = {}

        async def fake_get(path_with_query):
            captured["path"] = path_with_query
            return {"statusCode": "Success"}

        svc._get = fake_get
        await svc.query_trade("PT0260724700004T")
        assert captured["path"] == "/v2/trades/PT0260724700004T"
