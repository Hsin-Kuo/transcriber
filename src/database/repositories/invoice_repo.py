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
        await self._ensure_active_invoice_unique_index()

    async def _ensure_active_invoice_unique_index(self):
        """P2-14：同一張 order 同時只允許一顆「活躍」發票 doc（issued/pending/failed）。

        `reissue()` 現有的併發防護（`claim_for_reissue` lease + `find_reissue_conflict`
        query）是 read-then-write，兩次查詢之間不是原子的——`find_reissue_conflict`
        本身查的就是這三個 status，跟這裡的 partialFilterExpression 對齊，讓 DB 在
        insert 當下再擋一次真正的原子防線（DuplicateKeyError，見 `reissue()` 的
        create 重試迴圈分流）。voided/needs_manual 不受限——同一個 order 可以有多顆
        voided（作廢又重開的歷史）或 needs_manual（設計上就是給人工善後的終局狀態），
        partial filter 刻意排除它們。

        建立失敗（代表歷史資料已有同一 order 多顆活躍 doc）**不自動修資料**：發票是
        稅務文件，不能像 orders 的 pending unique index 那樣自動 dedupe/supersede
        （這裡沒有安全的「保留哪一顆」判斷——兩顆都可能已經真的送出去給 SmilePay）。
        只記錯誤 + 讓應用照常啟動，PR 說明附人工清理指引（查出違規 order_no 後，
        逐筆到速買配後台核對哪一顆是真正有效的發票，再手動把其餘的改成 voided/
        needs_manual 讓 index 得以建立）。
        """
        try:
            await self.collection.create_index(
                [("order_no", 1)],
                unique=True,
                partialFilterExpression={"status": {"$in": ["issued", "pending", "failed"]}},
                name="uniq_active_invoice_per_order",
            )
        except Exception as e:
            log.error("invoice_repo.create_active_unique_index_failed", error=str(e))

    # ── 建立 ───────────────────────────────────────────────────────────────

    async def create(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        now = get_utc_timestamp()
        invoice_data.setdefault("created_at", now)
        invoice_data.setdefault("updated_at", now)
        invoice_data.setdefault("claimed_until", None)
        invoice_data.setdefault("reissue_claimed_until", None)
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
                    "reissue_claimed_until": None,
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

    async def exists_any_by_order_no(self, order_no: str) -> bool:
        """該 order 是否有**任何**狀態的 invoice doc（含 voided）——P2-13 gap sweep 專用。

        刻意不排除 voided：只要曾經落過地就代表「開票流程有跑過」，之後的狀態演進
        （作廢/重開）歸既有的 retry sweep / reissue 管，gap sweep 只負責補「doc 從未
        落地」這種完全沒有痕跡的洞，兩者互不重疊。
        """
        doc = await self.collection.find_one({"order_no": order_no}, {"_id": 1})
        return doc is not None

    async def get_active_by_order_no(self, order_no: str) -> Optional[Dict[str, Any]]:
        """該 order 目前「非 voided」的 invoice doc（issued/pending/failed/needs_manual）。

        issue_for_order 重入時要沿用同一顆 doc（含其現有 data_id，可能已被
        `_degrade_and_reopen` 改過），不能每次都用固定 data_id 去 upsert——否則會在
        降級後的重入路徑上意外插出第二顆 doc（見 invoice_service.issue_for_order 的說明）。
        voided 的舊發票要排除：作廢後應該走 `reissue()` 開一顆全新的 doc。
        """
        # reissue 後同一 order 會有 needs_manual 舊 doc + pending 新 doc，取最新的那顆
        return await self.collection.find_one(
            {"order_no": order_no, "status": {"$ne": "voided"}},
            sort=[("created_at", -1)],
        )

    async def update_if_status(self, invoice_id, allowed_statuses: list, updates: Dict[str, Any]) -> bool:
        """只在現值 status 仍屬 allowed_statuses 時更新（防 recovery 路徑覆蓋已終局的狀態）。"""
        updates = {**updates, "updated_at": get_utc_timestamp()}
        result = await self.collection.update_one(
            {"_id": invoice_id, "status": {"$in": allowed_statuses}},
            {"$set": updates},
        )
        return result.modified_count > 0

    async def list_by_order_no(self, order_no: str) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"order_no": order_no}).sort("created_at", 1)
        return await cursor.to_list(length=100)

    async def list_by_order_nos(self, order_nos: List[str]) -> List[Dict[str, Any]]:
        """批次查多個 order 的全部 invoices（使用者付款紀錄 join 用；一次 `$in`
        避免每筆訂單各查一次的 N+1——使用者的訂單數量少，記憶體組裝即可，見設計 §4.3）。
        """
        if not order_nos:
            return []
        cursor = self.collection.find({"order_no": {"$in": list(set(order_nos))}})
        return await cursor.to_list(length=1000)

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

    async def find_reissue_conflict(self, order_no: str) -> Optional[Dict[str, Any]]:
        """該 order 是否已有「開立成功或進行中」的發票（issued/pending/failed）。

        reissue 的 lease 只擋「同時飛」的請求；重開成功之後來源 doc 仍是 voided/
        needs_manual，若不查這個，admin 前後兩次按重開會開出兩張真發票。
        """
        return await self.collection.find_one(
            {"order_no": order_no, "status": {"$in": ["issued", "pending", "failed"]}}
        )

    async def claim_for_reissue(self, invoice_id, lease_seconds: int = 180) -> Optional[Dict[str, Any]]:
        """reissue 專用的獨立 lease（欄位 `reissue_claimed_until`，不與 `claimed_until`
        共用——那個是 sweep/issue 的 processing lease，語意不同，混用會互相誤擋）。

        只有 status ∈ {voided, needs_manual} 且沒有其他人正在 reissue 中才搶得到；
        拿不到回 None（PR-B 驗收 finding #2：防雙擊/兩 admin 併發重開出兩張真發票）。
        lease 180s：期間內要做 next_reissue_seq + create + SmilePay 呼叫（httpx timeout
        30s，載具降級時兩次）——60s 在 SmilePay 慢時可能過期，讓第二個請求搶進來。
        """
        now = get_utc_timestamp()
        return await self.collection.find_one_and_update(
            {
                "_id": _oid(invoice_id),
                "status": {"$in": ["voided", "needs_manual"]},
                "$or": [
                    {"reissue_claimed_until": None},
                    {"reissue_claimed_until": {"$lt": now}},
                ],
            },
            {"$set": {"reissue_claimed_until": now + lease_seconds, "updated_at": now}},
            return_document=True,
        )

    async def release_reissue_claim(self, invoice_id) -> None:
        await self.collection.update_one(
            {"_id": _oid(invoice_id)},
            {"$set": {"reissue_claimed_until": None, "updated_at": get_utc_timestamp()}},
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


# ── 使用者付款紀錄 join（PR-C，設計 §4.3）────────────────────────────────────

def pick_user_facing_invoice(invoices: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """使用者付款紀錄要附掛的發票摘要：語意比照 admin 的 `_invoice_lookup_stages`，
    但使用者端只認 issued/voided——pending/failed/needs_manual 一律回 None，
    不對使用者暴露開票中/失敗等內部狀態。

    一個 order 可能有多筆 invoice（作廢重開）：優先取最新一筆 status=issued；
    若無 issued，退而取最新一筆 voided；其他情況（doc 全非 issued/voided，或
    完全沒有 invoice）回 None。

    回傳欄位白名單化，只有 invoice_number/random_number/invoice_date/
    invoice_status 四個——絕不透出 data_id/last_error/attempts/buyer 等內部欄位。
    """
    issued = [d for d in invoices if d.get("status") == "issued"]
    if issued:
        return _user_facing_fields(max(issued, key=lambda d: d.get("created_at") or 0))
    voided = [d for d in invoices if d.get("status") == "voided"]
    if voided:
        return _user_facing_fields(max(voided, key=lambda d: d.get("created_at") or 0))
    return None


def _user_facing_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "invoice_number": doc.get("invoice_number"),
        "random_number": doc.get("random_number"),
        "invoice_date": doc.get("invoice_date"),
        "invoice_status": doc.get("status"),
    }
