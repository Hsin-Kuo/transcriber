"""藍新金流服務（NewebPay 定期定額 + MPG）

定期定額 API 文件：信用卡定期定額串接技術手冊 NDNP-1.0.7
"""
import hashlib
import json
import os
import time
import uuid
import urllib.parse
from typing import Optional, Dict, Tuple
from datetime import datetime, date, timedelta

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import httpx

from .config_loader import get_parameter


PERIOD_TIMES_MONTHLY = 99
PERIOD_TIMES_YEARLY = 10

# 定期定額 PeriodStartType
PERIOD_START_IMMEDIATE = 2   # 立即執行委託金額授權（新訂閱、升級）
PERIOD_START_SCHEDULED = 3   # 不授權，首扣日由 PeriodFirstdate 指定（降級排程）
# 注意：PeriodStartType=1 是十元驗證，不適合訂閱場景


class NewebpayService:
    """藍新金流服務（Singleton）"""

    def __init__(self):
        self.merchant_id = get_parameter(
            "/transcriber/newebpay-merchant-id",
            fallback_env="NEWEBPAY_MERCHANT_ID"
        )
        self.hash_key = get_parameter(
            "/transcriber/newebpay-hash-key",
            fallback_env="NEWEBPAY_HASH_KEY"
        )
        self.hash_iv = get_parameter(
            "/transcriber/newebpay-hash-iv",
            fallback_env="NEWEBPAY_HASH_IV"
        )
        self.env = os.getenv("NEWEBPAY_ENV", "sandbox")

    # ── URLs ────────────────────────────────────────────────────

    @property
    def period_gateway_url(self) -> str:
        if self.env == "production":
            return "https://core.newebpay.com/MPG/period"
        return "https://ccore.newebpay.com/MPG/period"

    @property
    def mpg_gateway_url(self) -> str:
        if self.env == "production":
            return "https://core.newebpay.com/MPG/mpg_gateway"
        return "https://ccore.newebpay.com/MPG/mpg_gateway"

    @property
    def alter_status_url(self) -> str:
        """修改委託狀態（暫停/啟用/終止）"""
        if self.env == "production":
            return "https://core.newebpay.com/MPG/period/AlterStatus"
        return "https://ccore.newebpay.com/MPG/period/AlterStatus"

    # ── 加解密 ──────────────────────────────────────────────────

    def _aes_encrypt(self, data: str) -> str:
        key = self.hash_key.encode("utf-8")
        iv = self.hash_iv.encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return cipher.encrypt(pad(data.encode("utf-8"), AES.block_size)).hex()

    def _aes_decrypt(self, data: str) -> str:
        key = self.hash_key.encode("utf-8")
        iv = self.hash_iv.encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(bytes.fromhex(data)), AES.block_size).decode("utf-8")

    def _sha256_sign(self, trade_info: str) -> str:
        raw = f"HashKey={self.hash_key}&{trade_info}&HashIV={self.hash_iv}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()

    # ── 訂單號 ───────────────────────────────────────────────────

    def generate_order_no(self, prefix: str = "SL") -> str:
        ts = int(time.time())
        suffix = uuid.uuid4().hex[:6].upper()
        return f"{prefix}{ts}{suffix}"

    # ── PeriodPoint 計算 ─────────────────────────────────────────

    @staticmethod
    def calc_period_point(billing_cycle: str, start_date: Optional[date] = None) -> str:
        """
        月繳：日期字串 01~31（藍新自動處理當月無此日的情況）
        年繳：MMDD 格式
        日繳（降級排程）：30 or 365
        """
        d = start_date or date.today()
        if billing_cycle == "monthly":
            return f"{d.day:02d}"
        elif billing_cycle == "yearly":
            return f"{d.month:02d}{d.day:02d}"
        else:
            return "30"

    # ── 定期定額表單（新訂閱 / 升級）────────────────────────────

    def create_period_form(
        self,
        order_no: str,
        amount_twd: int,
        billing_cycle: str,   # "monthly" | "yearly"
        prod_desc: str,
        payer_email: str,
        return_url: str,
        notify_url: str,
        start_date: Optional[date] = None,
    ) -> Dict:
        """
        建立定期定額表單（立即首期授權，PeriodStartType=2）。
        用於新訂閱、升級。
        """
        period_type = "M" if billing_cycle == "monthly" else "Y"
        period_times = PERIOD_TIMES_MONTHLY if billing_cycle == "monthly" else PERIOD_TIMES_YEARLY
        period_point = self.calc_period_point(billing_cycle, start_date)

        params: Dict = {
            "RespondType": "JSON",
            "Version": "1.5",
            "TimeStamp": str(int(time.time())),
            "MerOrderNo": order_no,
            "ProdDesc": prod_desc,
            "PeriodAmt": amount_twd,
            "PeriodType": period_type,
            "PeriodPoint": period_point,
            "PeriodStartType": PERIOD_START_IMMEDIATE,
            "PeriodTimes": period_times,
            "PayerEmail": payer_email,
            "EmailModify": 0,
            "PaymentInfo": "N",
            "OrderInfo": "N",
            "ReturnURL": return_url,
            "NotifyURL": notify_url,
            "BackURL": return_url,  # 用戶取消時也返回同一個 return handler
            # 電子發票：待確認定期定額發票參數後補入
        }

        post_data = self._aes_encrypt(urllib.parse.urlencode(params))
        return {
            "MerchantID_": self.merchant_id,
            "PostData_": post_data,
            "gateway_url": self.period_gateway_url,
        }

    def create_period_form_scheduled(
        self,
        order_no: str,
        amount_twd: int,
        billing_cycle: str,
        prod_desc: str,
        payer_email: str,
        return_url: str,
        notify_url: str,
        first_date: str,       # YYYY/MM/DD，首次扣款日
    ) -> Dict:
        """
        建立定期定額表單（指定首扣日，PeriodStartType=3）。
        PeriodFirstdate 僅在 PeriodType=D + PeriodStartType=3 時有效。
        用於降級排程：以 D 型（固定天期）模擬月/年繳。
        """
        period_point = "30" if billing_cycle == "monthly" else "365"
        period_times = PERIOD_TIMES_MONTHLY if billing_cycle == "monthly" else PERIOD_TIMES_YEARLY

        params: Dict = {
            "RespondType": "JSON",
            "Version": "1.5",
            "TimeStamp": str(int(time.time())),
            "MerOrderNo": order_no,
            "ProdDesc": prod_desc,
            "PeriodAmt": amount_twd,
            "PeriodType": "D",
            "PeriodPoint": period_point,
            "PeriodStartType": PERIOD_START_SCHEDULED,
            "PeriodTimes": period_times,
            "PeriodFirstdate": first_date,
            "PayerEmail": payer_email,
            "EmailModify": 0,
            "PaymentInfo": "N",
            "OrderInfo": "N",
            "ReturnURL": return_url,
            "NotifyURL": notify_url,
        }

        post_data = self._aes_encrypt(urllib.parse.urlencode(params))
        return {
            "MerchantID_": self.merchant_id,
            "PostData_": post_data,
            "gateway_url": self.period_gateway_url,
        }

    # ── MPG 一次性付款表單 ───────────────────────────────────────

    def create_mpg_form(
        self,
        order_no: str,
        amount_twd: int,
        item_desc: str,
        email: str,
        return_url: str,
        notify_url: str,
        carrier_type: str = "",
        carrier_num: str = "",
        buyer_uni_num: str = "",
        buyer_name: str = "",
    ) -> Dict:
        """建立 MPG 一次性付款表單（含電子發票）"""
        params: Dict = {
            "RespondType": "JSON",
            "TimeStamp": str(int(time.time())),
            "MerchantOrderNo": order_no,
            "Amt": amount_twd,
            "ItemDesc": item_desc,
            "TradeLimit": 900,
            "Email": email,
            "ReturnURL": return_url,
            "NotifyURL": notify_url,
            "LoginType": 0,
            "CREDIT": 1,
            "InvoiceStatus": 1,
            "InvoiceTermsType": 0,
            "InvoiceTaxType": 1,
            "InvoiceCategory": "B2C",
            "BuyerEmail": email,
        }

        if carrier_type and carrier_num:
            params["CarrierType"] = carrier_type
            params["CarrierNum"] = carrier_num

        if buyer_uni_num:
            params["InvoiceCategory"] = "B2B"
            params["BuyerUniNum"] = buyer_uni_num
            params["BuyerName"] = buyer_name

        trade_info_str = urllib.parse.urlencode(params)
        trade_info = self._aes_encrypt(trade_info_str)
        trade_sha = self._sha256_sign(trade_info)

        return {
            "MerchantID": self.merchant_id,
            "TradeInfo": trade_info,
            "TradeSha": trade_sha,
            "TimeStamp": params["TimeStamp"],
            "gateway_url": self.mpg_gateway_url,
        }

    # ── 定期定額 Notify 解密 ─────────────────────────────────────

    def decrypt_period_notify(self, post_data: Dict) -> Optional[Dict]:
        """
        解密藍新定期定額 Notify。
        Notify 以 AES 加密的 Period 欄位回傳，解密後為 JSON。

        回傳 None 表示驗證失敗或解密失敗。
        """
        period_encrypted = post_data.get("Period", "")
        if not period_encrypted:
            return None
        try:
            decrypted = self._aes_decrypt(period_encrypted)
            data = json.loads(decrypted)
            # 基本驗證：MerchantID 須符合
            result = data.get("Result", {})
            if result.get("MerchantID") and result["MerchantID"] != self.merchant_id:
                return None
            return data
        except Exception:
            return None

    def verify_and_decrypt_mpg_notify(self, trade_info: str, trade_sha: str) -> Optional[Dict]:
        """驗證並解密 MPG Notify（AES + SHA256）"""
        expected_sha = self._sha256_sign(trade_info)
        if expected_sha != trade_sha:
            return None
        try:
            decrypted = self._aes_decrypt(trade_info)
            return dict(urllib.parse.parse_qsl(decrypted))
        except Exception:
            return None

    # ── 修改委託狀態 ─────────────────────────────────────────────

    async def terminate_period_contract(
        self, merchant_order_no: str, period_no: str
    ) -> Tuple[bool, str]:
        """
        終止定期定額委託（AlterType=terminate）。
        回傳 (success, message)。
        """
        params = {
            "RespondType": "JSON",
            "Version": "1.0",
            "TimeStamp": str(int(time.time())),
            "MerOrderNo": merchant_order_no,
            "PeriodNo": period_no,
            "AlterType": "terminate",
        }
        post_data = self._aes_encrypt(urllib.parse.urlencode(params))

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.alter_status_url,
                data={"MerchantID_": self.merchant_id, "PostData_": post_data},
            )

        # 回傳格式：form-encoded，period 欄位為 AES 加密字串
        # 嘗試 form-encoded → JSON 兩種方式解析
        period_enc = ""
        try:
            parsed = dict(urllib.parse.parse_qsl(resp.text))
            period_enc = parsed.get("period", "") or parsed.get("Period", "")
        except Exception:
            pass

        if not period_enc:
            try:
                body = resp.json()
                period_enc = body.get("period", "") or body.get("Period", "")
            except Exception:
                pass

        if period_enc:
            try:
                result = json.loads(self._aes_decrypt(period_enc))
                ok = result.get("Status") == "SUCCESS"
                return ok, result.get("Message", "")
            except Exception:
                pass

        return False, f"解析回應失敗（HTTP {resp.status_code}）"

    # ── 定價查表 ─────────────────────────────────────────────────

    @staticmethod
    def get_subscription_price(tier: str, billing_cycle: str) -> Optional[int]:
        prices = {
            ("basic", "monthly"): int(os.getenv("NEWEBPAY_PRICE_BASIC_MONTHLY", "299")),
            ("basic", "yearly"):  int(os.getenv("NEWEBPAY_PRICE_BASIC_YEARLY",  "3289")),
            ("pro",   "monthly"): int(os.getenv("NEWEBPAY_PRICE_PRO_MONTHLY",   "899")),
            ("pro",   "yearly"):  int(os.getenv("NEWEBPAY_PRICE_PRO_YEARLY",    "9889")),
        }
        return prices.get((tier, billing_cycle))

    # ── 計費週期日期 ─────────────────────────────────────────────

    @staticmethod
    def calc_period_end(billing_cycle: str, start: Optional[datetime] = None) -> datetime:
        s = start or datetime.utcnow()
        if billing_cycle == "monthly":
            return s + timedelta(days=30)
        return s + timedelta(days=365)


_newebpay_service: Optional[NewebpayService] = None


def get_newebpay_service() -> NewebpayService:
    global _newebpay_service
    if _newebpay_service is None:
        _newebpay_service = NewebpayService()
    return _newebpay_service
