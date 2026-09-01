"""SmilePay（速買配）電子發票服務（transport 層）。

形狀比照 payments91_service.py：class + get_parameter + httpx.AsyncClient POST +
lazy singleton + 不自 log（呼叫端負責 log，且絕不可 log Verify_key）。

API 規格與 spike 實測結果見 docs/INVOICE_SMILEPAY_API.md、
docs/INVOICE_SMILEPAY_INTEGRATION_PLAN.md §4.1/§9：
- 一律 POST（含列印代抓），Verify_key 不進 URL query string。
- 回應是 XML，root tag 不保證一致（開立是 `SmilePayEinvoice`，
  實測作廢回應卻是 `SmilePayEinvoiceModify`）——`_parse()` 用 defusedxml 解析、
  不檢查 root tag，只取子節點。
- 非 XML / HTTP 5xx 一律包成 `{"Status": "-9999", "raw": text[:500]}`，不 raise
  （交由 invoice_service.classify_invoice_error 分類為 transient 重試）。
"""
import os
from typing import Any, Dict, Optional

import httpx
from defusedxml import ElementTree as DET

from .config_loader import get_parameter, is_prod_aws


class SmilePayService:
    """SmilePay 電子發票服務（Singleton）。"""

    def __init__(self):
        self.grvc = get_parameter(
            "/transcriber/smilepay-grvc", fallback_env="SMILEPAY_GRVC", required=True
        )
        self.verify_key = get_parameter(
            "/transcriber/smilepay-verify-key", fallback_env="SMILEPAY_VERIFY_KEY", required=True
        )
        self.env = os.getenv("SMILEPAY_ENV", "test")

        # P1-6 fail-fast：prod-aws 下 SMILEPAY_ENV 必須顯式為 production，否則真客戶
        # 發票（PII）會打到測試 endpoint（/api_test/，不入財政部）——真扣款卻無有效發票。
        # raise 在背景 sweep 可能被 per-item try/except 吞掉只留 log，但仍是 fail-closed：
        # 發票發不出去 ≠ 開成無效發票。main.py startup 的 validate_payment_env() 負責讓
        # 設定錯誤在啟動當下「被人看到」。
        if is_prod_aws() and self.env != "production":
            raise RuntimeError("SMILEPAY_ENV must be 'production' on prod (P1-6 fail-fast)")

    @property
    def base_url(self) -> str:
        if self.env == "production":
            return "https://ssl.smse.com.tw/api/"
        return "https://ssl.smse.com.tw/api_test/"

    @property
    def print_base_url(self) -> str:
        """列印畫面網域（與資料 API 不同網域）。Phase 1 未使用（§9 spike 移除代抓），保留供未來 issue 參考。"""
        if self.env == "production":
            return "https://einvoice.smilepay.net/einvoice/"
        return "https://einvoice.smilepay.net/einvoice_test/"

    # ── transport ──────────────────────────────────────────────────────────

    async def _post(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {"Grvc": self.grvc, "Verify_key": self.verify_key}
        for k, v in params.items():
            if v is not None:
                body[k] = v
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.base_url + path, data=body)
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> Dict[str, Any]:
        # HTTP 層 5xx：ASP 後端錯誤頁通常非 XML，直接歸類成可重試的 transient（見
        # invoice_service.classify_invoice_error 的 "-9999" 分支），不強行硬解析。
        if resp.status_code >= 500:
            return {"Status": "-9999", "raw": resp.text[:500]}
        try:
            root = DET.fromstring(resp.content)
        except Exception:
            return {"Status": "-9999", "raw": resp.text[:500]}
        # 不檢查 root tag（實測作廢回應是 SmilePayEinvoiceModify，非文件寫的 SmilePayEinvoice）。
        return {child.tag: (child.text or "") for child in root}

    # ── 開立 ───────────────────────────────────────────────────────────────

    async def issue_invoice(self, **fields: Any) -> Dict[str, Any]:
        return await self._post("SPEinvoice_Storage.asp", fields)

    # ── 作廢 / 註銷 ────────────────────────────────────────────────────────

    async def void_invoice(self, invoice_number: str, invoice_date: str, reason: str) -> Dict[str, Any]:
        return await self._post("SPEinvoice_Storage_Modify.asp", {
            "types": "Cancel",
            "InvoiceNumber": invoice_number,
            "InvoiceDate": invoice_date,
            "CancelReason": reason[:20],
        })

    async def cancel_allowance(self, allowance_number: str, allowance_date: Optional[str], reason: str) -> Dict[str, Any]:
        return await self._post("SPEinvoice_Storage_Modify.asp", {
            "types": "CancelAllowance",
            "AllowanceNumber": allowance_number,
            "AllowanceDate": allowance_date,
            "CancelReason": reason[:20],
        })

    # ── 折讓單（預留，非本次目標；不做 UI）───────────────────────────────────

    async def create_allowance(self, **fields: Any) -> Dict[str, Any]:
        return await self._post("SPEinvoice_Storage_Allowance.asp", fields)


_smilepay_service: Optional[SmilePayService] = None


def get_smilepay_service() -> SmilePayService:
    global _smilepay_service
    if _smilepay_service is None:
        _smilepay_service = SmilePayService()
    return _smilepay_service
