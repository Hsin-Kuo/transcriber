"""計費週期 / 訂單編號 純工具（provider 無關）。

從 newebpay_service 抽出,讓 order_settlement / subscriptions 不再依賴任何金流 provider
就能算週期結束日與產生訂單號。91APP 商戶自扣模型下,週期由本地判斷（見 quota.py 到期掃描
與 Phase 2 續扣排程器）。
"""
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional


def calc_period_end(billing_cycle: str, start: Optional[datetime] = None) -> datetime:
    """月繳 +30 天 / 年繳 +365 天。"""
    s = start or datetime.utcnow()
    if billing_cycle == "monthly":
        return s + timedelta(days=30)
    return s + timedelta(days=365)


def generate_order_no(prefix: str = "SL") -> str:
    """商店訂單編號：<prefix><unix_ts><6碼uuid>。符合 91APP merchantOrderId ≤50 字元規則。"""
    ts = int(time.time())
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{ts}{suffix}"
