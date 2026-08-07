"""發票資料存取層（SmilePay 電子發票）。

比照 order_repo.py 的形狀。核心是 `claim_for_processing` 的 lease 原子搶佔：
冪等與並發防護都在 invoices doc 上（不用 processed_webhooks，見設計文件 §3.1/§6）。
"""
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from bson import ObjectId

from ...utils.time_utils import get_utc_timestamp
from ...utils.logger import get_logger

log = get_logger(__name__)

_REISSUE_SEQ_RE = re.compile(r"-R(\d+)$")


def _oid(invoice_id) -> ObjectId:
    return invoice_id if isinstance(invoice_id, ObjectId) else ObjectId(invoice_id)


class InvoiceRepository:
    """發票資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.invoices

    async def create_indexes(self):
        await self.collection.create_index("data_id", unique=True)
        await self.collection.create_index("order_no")
        await self.collection.create_index("user_id")
        await self.collection.create_index([("status", 1), ("next_retry_at", 1)])

    # ── 建立 ───────────────────────────────────────────────────────────────

    async def create(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        now = get_utc_timestamp()
        invoice_data.setdefault("created_at", now)
        invoice_data.setdefault("updated_at", now)
        invoice_data.setdefault("claimed_until", None)
        invoice_data.setdefault("attempts", 0)
        invoice_data.setdefault("last_error", None)
        invoice_data.setdefault("allowance_numbers", [])
        result = await self.collection.insert_one(invoice_data)
        invoice_data["_id"] = result.inserted_id
        return invoice_data

    async def upsert_initial(
        self,
        *,
        order_no: str,
        user_id: str,
        data_id: str,
        buyer: Dict[str, Any],
        amount_twd: int,
        deadline_at: float,
    ) -> Dict[str, Any]:
        """建立（或取回既有）待處理發票 doc。data_id 是冪等鍵——重入不會產生第二筆。

        first_attempt_at / next_retry_at 只在「插入」時寫入（$setOnInsert），
        重入既有 doc 不覆蓋，確保跨期別判定與撈單條件穩定。
        """
        now = get_utc_timestamp()
        doc = await self.collection.find_one_and_update(
            {"data_id": data_id},
            {
                "$setOnInsert": {
                    "order_no": order_no,
                    "user_id": user_id,
                    "data_id": data_id,
                    "status": "pending",
                    "claimed_until": None,
                    "invoice_type": None,
                    "invoice_number": None,
                    "random_number": None,
                    "invoice_date": None,
                    "buyer": buyer,
                    "amount_twd": amount_twd,
                    "attempts": 0,
                    "first_attempt_at": now,
                    "next_retry_at": now,
                    "deadline_at": deadline_at,
                    "last_error": None,
                    "voided_at": None,
                    "void_reason": None,
                    "allowance_numbers": [],
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
            return_document=True,
        )
        return doc

    # ── 查詢 ───────────────────────────────────────────────────────────────

    async def get_by_id(self, invoice_id) -> Optional[Dict[str, Any]]:
        try:
            return await self.collection.find_one({"_id": _oid(invoice_id)})
        except Exception:
            return None

    async def get_by_data_id(self, data_id: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"data_id": data_id})

    async def get_issued_by_order_no(self, order_no: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"order_no": order_no, "status": "issued"})

    async def list_by_order_no(self, order_no: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"order_no": order_no}).sort("created_at", 1)
        return await cursor.to_list(length=100)

    async def next_reissue_seq(self, order_no: str) -> int:
        """回傳該 order 現有 invoices 中最大的 R{n} 序號 + 1（無重開紀錄則為 1）。"""
        docs = await self.list_by_order_no(order_no)
        max_seq = 0
        for d in docs:
            m = _REISSUE_SEQ_RE.search(d.get("data_id") or "")
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return max_seq + 1

    # ── Lease（並發防護）──────────────────────────────────────────────────

    async def claim_for_processing(self, invoice_id, lease_seconds: int = 120) -> Optional[Dict[str, Any]]:
        """原子搶佔：只有拿到 lease 的呼叫端可以送 SmilePay。拿不到回 None（代表另一 process 在處理）。"""
        now = get_utc_timestamp()
        return await self.collection.find_one_and_update(
            {
                "_id": _oid(invoice_id),
                "status": {"$in": ["pending", "failed"]},
                "$or": [{"claimed_until": None}, {"claimed_until": {"$lt": now}}],
            },
            {"$set": {"claimed_until": now + lease_seconds, "updated_at": now}},
            return_document=True,
        )

    async def release_claim(self, invoice_id) -> None:
        await self.collection.update_one(
            {"_id": _oid(invoice_id)},
            {"$set": {"claimed_until": None, "updated_at": get_utc_timestamp()}},
        )

    # ── 更新 ───────────────────────────────────────────────────────────────

    async def update(self, invoice_id, updates: Dict[str, Any]) -> bool:
        updates = dict(updates)
        updates["updated_at"] = get_utc_timestamp()
        result = await self.collection.update_one({"_id": _oid(invoice_id)}, {"$set": updates})
        return result.modified_count > 0

    # ── Sweep 撈單 ─────────────────────────────────────────────────────────

    async def iter_due_for_retry(self, now: float) -> AsyncIterator[Dict[str, Any]]:
        """status ∈ {pending, failed} 且到期者。★防守性地把 next_retry_at=null 也撈進來
        （建立時必寫 now，理論上不會是 null；此為 bug 防線，見設計 §4.2）。
        """
        cursor = self.collection.find({
            "status": {"$in": ["pending", "failed"]},
            "$or": [{"next_retry_at": {"$lte": now}}, {"next_retry_at": None}],
        })
        async for doc in cursor:
            yield doc

    async def iter_deadline_warnings(self, now: float, warn_before_seconds: int) -> AsyncIterator[Dict[str, Any]]:
        """未 issued/voided 且即將超過 deadline 者——獨立於 retry 條件之外的告警掃描。

        `deadline_alerted` 防止每 10 分鐘重複送同一張的 Sentry alert（同一張只提醒一次）。
        """
        cursor = self.collection.find({
            "status": {"$nin": ["issued", "voided"]},
            "deadline_at": {"$lte": now + warn_before_seconds},
            "deadline_alerted": {"$ne": True},
        })
        async for doc in cursor:
            yield doc

    async def mark_deadline_alerted(self, invoice_id) -> None:
        await self.collection.update_one(
            {"_id": _oid(invoice_id)},
            {"$set": {"deadline_alerted": True, "updated_at": get_utc_timestamp()}},
        )
