"""訂單資料存取層"""
import asyncio
from typing import Optional, Dict, Any, List
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
        await self.collection.create_index("period_no")
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

    async def get_by_period_no(self, period_no: str) -> Optional[Dict[str, Any]]:
        return await self.collection.find_one({"period_no": period_no})

    async def find_orphan_contracts(
        self, user_id: str, keep_period_no: str
    ) -> List[Dict[str, Any]]:
        """找出該 user 名下「已 paid 但 period_no ≠ 目前 active」的其他藍新委託。

        供 OrderSettlement 的孤兒委託對帳收斂用：訂閱啟動後終止這些多出來的委託，
        防雙重完成造成每月重複扣款。已標記 contract_terminated_at 的不再列入。
        """
        cursor = self.collection.find({
            "user_id": user_id,
            "status": "paid",
            "type": {"$in": ["subscription", "upgrade_subscription", "downgrade_subscription"]},
            "period_no": {"$nin": [None, keep_period_no]},
            "contract_terminated_at": {"$exists": False},
        })
        return [o async for o in cursor]

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
