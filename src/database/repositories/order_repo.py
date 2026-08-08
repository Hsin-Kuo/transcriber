"""訂單資料存取層"""
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from ...utils.time_utils import get_utc_timestamp
from ...utils.logger import get_logger

log = get_logger(__name__)


class DuplicatePendingOrderError(Exception):
    """同 user+type 已有 in-flight 的 pending 單（由 DB partial unique index 攔下）。

    代表並發的重複建單嘗試，呼叫端應轉為 429 而非 500。
    """

    def __init__(self, user_id: str = "", order_type: str = ""):
        self.user_id = user_id
        self.order_type = order_type
        super().__init__(f"pending order already in-flight: user={user_id} type={order_type}")


class OrderRepository:
    """訂單資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.orders

    _PENDING_UNIQUE_INDEX = "uniq_pending_per_user_type"

    async def create_indexes(self):
        await self.collection.create_index("merchant_order_no", unique=True)
        await self.collection.create_index("user_id")
        await self.collection.create_index("status")
        await self._ensure_pending_unique_index()

    async def _ensure_pending_unique_index(self):
        """同 (user_id, type) 同時只允許一張 pending 單（DB 層防並發重複建單）。

        partial unique index：只對 status=pending 的文件生效，supersede/付款後狀態
        改變即釋放唯一槽。既有重複 pending 會讓 index 無法建立，故失敗時先去重再重試。
        """
        try:
            await self.collection.create_index(
                [("user_id", 1), ("type", 1)],
                unique=True,
                partialFilterExpression={"status": "pending"},
                name=self._PENDING_UNIQUE_INDEX,
            )
        except Exception:
            await self._dedupe_pending_orders()
            await self.collection.create_index(
                [("user_id", 1), ("type", 1)],
                unique=True,
                partialFilterExpression={"status": "pending"},
                name=self._PENDING_UNIQUE_INDEX,
            )

    async def _dedupe_pending_orders(self):
        """同 (user,type) 多筆 pending 時保留最新一筆、其餘標記 superseded（供建 unique index 前清理）。"""
        now = get_utc_timestamp()
        pipeline = [
            {"$match": {"status": "pending"}},
            {"$sort": {"created_at": -1}},
            {"$group": {"_id": {"u": "$user_id", "t": "$type"}, "ids": {"$push": "$_id"}}},
            {"$match": {"$expr": {"$gt": [{"$size": "$ids"}, 1]}}},
        ]
        async for grp in self.collection.aggregate(pipeline):
            stale = grp["ids"][1:]  # 保留最新（第一筆），其餘 superseded
            await self.collection.update_many(
                {"_id": {"$in": stale}},
                {"$set": {"status": "superseded", "updated_at": now}},
            )

    async def create(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        now = get_utc_timestamp()
        order_data.setdefault("created_at", now)
        order_data.setdefault("updated_at", now)
        if order_data.get("status") == "pending":
            order_data.setdefault("expires_at", now + 3600)
        try:
            result = await self.collection.insert_one(order_data)
        except DuplicateKeyError as e:
            # 撞到 pending partial unique index（user_id+type）→ 並發重複建單，轉為 domain 例外。
            # merchant_order_no 的 unique 撞鍵則屬罕見 bug，原樣拋出（讓上層 500）。
            key_pattern = (getattr(e, "details", None) or {}).get("keyPattern", {}) or {}
            if "user_id" in key_pattern and "type" in key_pattern:
                raise DuplicatePendingOrderError(
                    order_data.get("user_id", ""), order_data.get("type", "")
                ) from e
            raise
        order_data["_id"] = result.inserted_id
        return order_data

    async def get_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self.collection.find_one({"_id": ObjectId(order_id)})
        except Exception:
            return None

    async def get_by_order_no(self, merchant_order_no: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"merchant_order_no": merchant_order_no})

    async def get_active_subscription_order(self, user_id: str) -> Optional[Dict[str, Any]]:
        """取得用戶目前有效的訂閱訂單（type=subscription, status=paid）"""
        return await self.collection.find_one({
            "user_id": user_id,
            "type": {"$in": ["subscription", "upgrade_subscription", "downgrade_subscription"]},
            "status": "paid",
        }, sort=[("created_at", -1)])

    async def has_recent_pending_order(
        self, user_id: str, order_type: str, cooldown_seconds: int = 30
    ) -> bool:
        """防連點冷卻：是否有「cooldown_seconds 內建立」的同類型 pending 單。

        僅擋極短時間內的重複送出（誤觸 / 連點）；較舊的 pending 單不擋，
        交由 supersede_pending_orders() 取代，讓使用者可幾乎立即重新付款。
        """
        cutoff = get_utc_timestamp() - cooldown_seconds
        doc = await self.collection.find_one({
            "user_id": user_id,
            "type": order_type,
            "status": "pending",
            "created_at": {"$gt": cutoff},
        })
        return doc is not None

    async def supersede_pending_orders(self, user_id: str, order_type: str) -> int:
        """開新 checkout 前，把同類型既有 pending 單標記為 superseded，回傳筆數。

        目的：使用者中途離開付款頁後，不累積多筆 pending 垃圾單，且可立即重試。
        注意：superseded 只代表「商店端不再預期這筆」，不阻擋其 Notify——若該筆
        其實已在藍新完成授權，Notify 仍會被正常認列（get_by_order_no 不過濾狀態）。
        """
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {"user_id": user_id, "type": order_type, "status": "pending"},
            {"$set": {"status": "superseded", "updated_at": now}},
        )
        return result.modified_count

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 20,
        skip: int = 0,
        statuses: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"user_id": user_id}
        if statuses:
            query["status"] = {"$in": statuses}
        cursor = self.collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    # ── Admin 全域分頁查詢（PR-B，設計文件 §7.1）─────────────────────────────

    @staticmethod
    def _invoice_lookup_stages() -> List[Dict[str, Any]]:
        """`$lookup` invoices（依 order_no）並算出摘要規則（設計 §7.1）：取最新一筆
        「非 voided」的 invoice；若全部都是 voided（或沒有 invoice），取最新一筆 voided；
        完全沒有 invoice 則 `_invoice_doc` 為 None。抽成獨立方法給兩條查詢路徑共用
        （見 `admin_list_with_invoices` 的效能註記）。
        """
        return [
            {"$lookup": {
                "from": "invoices",
                "let": {"order_no": "$merchant_order_no"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$order_no", "$$order_no"]}}},
                    {"$sort": {"created_at": -1}},
                ],
                "as": "_invoices",
            }},
            {"$addFields": {
                "_non_voided": {
                    "$filter": {
                        "input": "$_invoices", "as": "inv",
                        "cond": {"$ne": ["$$inv.status", "voided"]},
                    }
                },
            }},
            {"$addFields": {
                "_invoice_doc": {
                    "$cond": [
                        {"$gt": [{"$size": "$_non_voided"}, 0]},
                        {"$arrayElemAt": ["$_non_voided", 0]},
                        {"$arrayElemAt": ["$_invoices", 0]},
                    ]
                },
            }},
            {"$addFields": {"_invoice_status": {"$ifNull": ["$_invoice_doc.status", None]}}},
        ]

    @staticmethod
    def _attach_invoice_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
        inv_doc = doc.pop("_invoice_doc", None)
        doc.pop("_invoices", None)
        doc.pop("_non_voided", None)
        doc.pop("_invoice_status", None)
        invoice = None
        if inv_doc:
            invoice = {
                "status": inv_doc.get("status"),
                "invoice_number": inv_doc.get("invoice_number"),
                "invoice_date": inv_doc.get("invoice_date"),
            }
        doc["invoice"] = invoice
        return doc

    async def admin_list_with_invoices(
        self,
        mongo_filter: Dict[str, Any],
        invoice_status: Optional[str],
        skip: int,
        limit: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """管理後台訂單列表：附掛「摘要發票」一筆（規則見 `_invoice_lookup_stages`）。

        效能（PR-B 驗收 finding #10）：`invoice_status` 是衍生欄位，只能在 `$lookup`
        之後才能拿來 `$match`，篩它的時候沒得選，只能整批 `$lookup` 完再 `$facet`
        分頁/計數。但這是少數情境——常見的「不篩發票狀態」路徑改成先用 `count_documents`
        算 total、再 `$match/$sort/$skip/$limit` truncate 到當頁之後才 `$lookup`，
        避免訂單量大時整張表都跑一次 `$lookup`（撞 aggregation 100MB 記憶體上限的風險）。
        """
        if not invoice_status:
            return await self._admin_list_page_then_lookup(mongo_filter, skip, limit)
        return await self._admin_list_lookup_then_filter(mongo_filter, invoice_status, skip, limit)

    async def _admin_list_page_then_lookup(
        self, mongo_filter: Dict[str, Any], skip: int, limit: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        total = await self.collection.count_documents(mongo_filter)
        pipeline: List[Dict[str, Any]] = [
            {"$match": mongo_filter},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
        ] + self._invoice_lookup_stages()
        docs = await self.collection.aggregate(pipeline).to_list(length=limit)
        return [self._attach_invoice_summary(d) for d in docs], total

    async def _admin_list_lookup_then_filter(
        self, mongo_filter: Dict[str, Any], invoice_status: str, skip: int, limit: int,
    ) -> Tuple[List[Dict[str, Any]], int]:
        pipeline: List[Dict[str, Any]] = [{"$match": mongo_filter}] + self._invoice_lookup_stages()
        match_value = None if invoice_status == "none" else invoice_status
        pipeline.append({"$match": {"_invoice_status": match_value}})
        pipeline.append({
            "$facet": {
                "data": [
                    {"$sort": {"created_at": -1}},
                    {"$skip": skip},
                    {"$limit": limit},
                ],
                "total": [{"$count": "count"}],
            }
        })

        result = await self.collection.aggregate(pipeline).to_list(length=1)
        facet = result[0] if result else {"data": [], "total": []}
        total = facet["total"][0]["count"] if facet["total"] else 0
        return [self._attach_invoice_summary(d) for d in facet["data"]], total

    async def update(self, order_id: str, updates: Dict[str, Any]) -> bool:
        updates["updated_at"] = get_utc_timestamp()
        result = await self.collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def update_by_order_no(self, merchant_order_no: str, updates: Dict[str, Any]) -> bool:
        updates["updated_at"] = get_utc_timestamp()
        result = await self.collection.update_one(
            {"merchant_order_no": merchant_order_no},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def sweep_expired_pending_orders(self) -> int:
        """將過期的 pending 訂單標記為 expired（保留記錄便於審計）"""
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {"status": "pending", "expires_at": {"$lt": now}},
            {"$set": {"status": "expired", "updated_at": now}}
        )
        return result.modified_count

    async def purge_old_superseded_orders(self, older_than_seconds: int = 30 * 24 * 3600) -> int:
        """刪除夠舊的 superseded 訂單（被取代的廢棄付款嘗試），避免無限累積。

        預設保留 30 天供審計後刪除。superseded 單從未成功付款，刪除安全。
        """
        cutoff = get_utc_timestamp() - older_than_seconds
        result = await self.collection.delete_many(
            {"status": "superseded", "updated_at": {"$lt": cutoff}}
        )
        return result.deleted_count


async def periodic_order_cleanup(db, interval_seconds: int = 300) -> None:
    """定期清掃過期未付款訂單（背景任務，由 main.py startup 啟動）"""
    order_repo = OrderRepository(db)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            expired = await order_repo.sweep_expired_pending_orders()
            purged = await order_repo.purge_old_superseded_orders()
            if expired or purged:
                log.info("order.sweep.completed", expired=expired, purged_superseded=purged)
        except Exception as e:
            log.error("order.sweep.failed", error=str(e), exc_info=True)
