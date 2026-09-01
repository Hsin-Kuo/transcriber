"""91APP Payments 服務（訂閱首購 + 商戶自扣續扣）。

取代舊藍新 NewebPay。核心模型是 **merchant-initiated**：首期以 SDK 取得 txnToken →
後端 request-by-txnToken（BindingCard）拿可續扣的 cardToken；續期由商戶自行呼叫
request-by-cardToken（無 gateway 排程，見 Phase 2 續扣排程器）。

request/response 形狀與簽章公式皆經 Phase 0 sandbox 實測
（見 docs/PAYMENT_91APP_MIGRATION_ASSESSMENT.md §12）。
"""
import base64
import hashlib
import hmac
import json
import os
import re
from typing import Optional, Dict
from urllib.parse import quote

import httpx

from .config_loader import get_parameter, is_prod_aws

# callback 收到的 tradeId 未認證，直接嵌入 query path 前先驗證格式（體檢 P1-8）。
# 91APP tradeId 觀察形狀為半形英數，保守放行底線/連字號；router 亦會 import 此常數做早退檢查。
TRADE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Payments91APPService:
    """91APP Payments 服務（Singleton）。"""

    def __init__(self):
        self.api_key = get_parameter(
            "/transcriber/91app-api-key", fallback_env="PAYMENTS91_API_KEY", required=True
        )
        self.shared_secret = get_parameter(
            "/transcriber/91app-shared-secret", fallback_env="PAYMENTS91_SHARED_SECRET", required=True
        )
        # publishableKey 非機密，會下發給前端 SDK。
        self.publishable_key = get_parameter(
            "/transcriber/91app-publishable-key", fallback_env="PAYMENTS91_PUBLISHABLE_KEY", required=True
        )
        # storeCode 目前不需帶進 request body（API key 已識別商店），保留供對帳/多店參考。
        self.store_code = get_parameter(
            "/transcriber/91app-store-code", fallback_env="PAYMENTS91_STORE_CODE", required=True
        )
        self.env = os.getenv("PAYMENTS91_ENV", "sandbox")

        # P1-6 fail-fast：prod-aws 下 PAYMENTS91_ENV 必須顯式為 production，否則真客戶
        # 扣款/發票會打到 91APP sandbox。這裡的 raise 若發生在背景 sweep（例如
        # renewal_service 的迴圈），可能被 per-item try/except 吞掉只留 log——但仍是
        # fail-closed：操作沒執行 = 不會誤打測試環境。main.py startup 的
        # validate_payment_env() 負責讓設定錯誤在啟動當下「被人看到」。
        if is_prod_aws() and self.env != "production":
            raise RuntimeError("PAYMENTS91_ENV must be 'production' on prod (P1-6 fail-fast)")

    @property
    def base_url(self) -> str:
        if self.env == "production":
            return "https://api.payments.91app.com"
        return "https://api.developer.payments.91app.com"

    @property
    def sdk_server_type(self) -> str:
        """Web SDK setupSDK() 的第二參數。"""
        return "production" if self.env == "production" else "sandbox"

    # ── 簽章（Phase 0 實證：HMAC key = shared_secret 原字串）──────────

    def _sign(self, payload: str) -> str:
        """N1-DATA-SIGNATURE = base64(lowercase_hex(HMAC-SHA256(payload, shared_secret)))"""
        mac = hmac.new(
            self.shared_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        )
        return base64.b64encode(mac.hexdigest().encode("ascii")).decode("ascii")

    def _headers(self, signature: str, idempotency_key: Optional[str] = None) -> Dict:
        h = {
            "N1-API-KEY": self.api_key,
            "N1-DATA-SIGNATURE": signature,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            h["N1-IDEMPOTENCY-KEY"] = idempotency_key  # 1 小時冪等；衝突回 HTTP 409
        return h

    async def _post(
        self, path: str, body: Dict, idempotency_key: Optional[str] = None
    ) -> Dict:
        # 序列化一次：簽這段字串、也送這段 bytes，確保簽章輸入 == 實際送出。
        body_str = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        sig = self._sign(body_str)  # POST 簽 JSON body 原字串
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self.base_url + path,
                content=body_str.encode("utf-8"),
                headers=self._headers(sig, idempotency_key),
            )
        return self._parse(resp)

    async def _get(self, path_with_query: str) -> Dict:
        signed_input = path_with_query.replace("?", "")  # GET 簽 path+query（去 '?'）
        sig = self._sign(signed_input)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self.base_url + path_with_query, headers=self._headers(sig)
            )
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> Dict:
        try:
            data = resp.json()
        except ValueError:
            data = {"errorCode": "NonJSONResponse", "raw": resp.text[:500]}
        data.setdefault("_http_status", resp.status_code)
        return data

    # ── 首購（request-by-txnToken, BindingCard）────────────────────

    async def create_first_payment(
        self,
        txn_token: str,
        order_no: str,
        consumer_id: str,
        amount: int,
        redirect_url: str,
        callback_url: str,
        prod_name: str,
    ) -> Dict:
        """訂閱首期綁卡付款。回傳含 paymentUrl（3D）或直接成交結果 + cardToken。

        BindingCard + merchantConsumerId 才拿得到可 MIT 續扣的 cardToken（非 RememberCard）。
        """
        body = {
            "txnToken": txn_token,
            "initCardTokenType": "BindingCard",
            "merchantConsumerId": consumer_id,
            "merchantOrderId": order_no,
            "paymentMethods": [{"payType": "CreditCard", "amount": amount}],
            "productType": "Subscription",
            "extensionInfo": {"subscriptionType": "First"},
            "currency": "TWD",
            "products": [
                {"name": prod_name, "totalAmount": amount, "productType": "Subscription"}
            ],
            "redirectUrl": redirect_url,
            "callbackUrl": callback_url,
        }
        return await self._post(
            "/v2/payments/request-by-txnToken", body, idempotency_key=order_no
        )

    # ── 續扣（request-by-cardToken, MIT）— Phase 2 排程器呼叫 ────────

    async def charge_renewal(
        self,
        card_token: str,
        consumer_id: str,
        order_no: str,
        amount: int,
        redirect_url: str,
        callback_url: str,
        prod_name: str,
    ) -> Dict:
        """MIT 免 3D 續扣。productType=Subscription + subscriptionType=Renewal（缺一不可）。"""
        body = {
            "cardToken": card_token,
            "merchantConsumerId": consumer_id,
            "merchantOrderId": order_no,
            "paymentMethods": [{"payType": "CreditCard", "amount": amount}],
            "productType": "Subscription",
            "extensionInfo": {"subscriptionType": "Renewal"},
            "currency": "TWD",
            "products": [
                {"name": prod_name, "totalAmount": amount, "productType": "Subscription"}
            ],
            "redirectUrl": redirect_url,
            "callbackUrl": callback_url,
        }
        return await self._post(
            "/v2/payments/request-by-cardToken", body, idempotency_key=order_no
        )

    # ── 交易回查（callback 防禦：不信 payload，以此為準）────────────

    async def query_trade(self, trade_id: str) -> Dict:
        if not isinstance(trade_id, str) or not TRADE_ID_RE.fullmatch(trade_id):
            # 訊息不回帶原值：trade_id 來自未認證的 callback payload，避免注入內容進 log/Sentry。
            raise ValueError("invalid trade_id format")
        return await self._get(f"/v2/trades/{quote(trade_id, safe='')}")

    # ── 定價 ─────────────────────────────────────────────────────

    @staticmethod
    def get_subscription_price(tier: str, billing_cycle: str) -> Optional[int]:
        prices = {
            ("basic", "monthly"): int(os.getenv("PAYMENTS91_PRICE_BASIC_MONTHLY", "299")),
            ("basic", "yearly"): int(os.getenv("PAYMENTS91_PRICE_BASIC_YEARLY", "3289")),
            ("pro", "monthly"): int(os.getenv("PAYMENTS91_PRICE_PRO_MONTHLY", "999")),
            ("pro", "yearly"): int(os.getenv("PAYMENTS91_PRICE_PRO_YEARLY", "10989")),
        }
        return prices.get((tier, billing_cycle))


# ── 交易結果判讀 ─────────────────────────────────────────────────────────────
# 🔴 trade 回查 / callback 的 recordStatus（整數）才是「付款結果」的權威欄位。
# 回查回應裡的 statusCode 是「查詢是否成功」（trade 存在即 Success），**不是**交易結果——
# 誤用它會讓任何進得來的 callback 一律判成功（見 91APP OpenAPI spec）。
# recordStatus enum：1 待付款 / 2 付款失敗 / 3 付款取消 / 4 付款成功 / 5 請款成功 /
#                    6 部分退款 / 7 全部退款 / 8 付款處理中
_RECORD_SUCCESS = {4, 5}
_RECORD_PENDING = {1, 8}
# P1-5（金流體檢）：6/7 從 "failed" 拆成獨立的 "refunded" 語意——已付款單收到退款
# 通知不是「付款失敗」，混在 failed 分支會被 order_settlement 的 mark_failed_unless_paid
# （`$ne paid` 條件式寫入）直接擋掉，變成「錢退了、權益完全沒被撤銷」的靜默漏洞。
# 呼叫端（subscriptions.py callback）依此值分流到獨立的退款處理路徑。
_RECORD_REFUND = {6, 7}


def interpret_record_status(record_status) -> str:
    """依 recordStatus 判 'success' | 'pending' | 'failed' | 'refunded'。

    非法/未知一律當 failed（保守，fail-closed）。'refunded' 涵蓋部分退款(6)/全部退款(7)
    ——呼叫端（見 subscriptions.py payment_callback）需再依實際 record_status 分辨
    6 與 7 各自的處置（P1-5：6 轉人工、7 自動降級）。
    """
    try:
        rs = int(record_status)
    except (TypeError, ValueError):
        return "failed"
    if rs in _RECORD_SUCCESS:
        return "success"
    if rs in _RECORD_PENDING:
        return "pending"
    if rs in _RECORD_REFUND:
        return "refunded"
    return "failed"


_payments91_service: Optional[Payments91APPService] = None


def get_payments91_service() -> Payments91APPService:
    global _payments91_service
    if _payments91_service is None:
        _payments91_service = Payments91APPService()
    return _payments91_service
