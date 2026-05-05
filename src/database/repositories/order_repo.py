"""訂單資料存取層"""
from typing import Optional, Dict, Any, List
from bson import ObjectId

from ...utils.time_utils import get_utc_timestamp


class OrderRepository:
    """訂單資料庫操作"""

    def __init__(self, db):
        self.db = db
        self.collection = db.orders

    async def create_indexes(self):
        await self.collection.create_index("merchant_order_no", unique=True)
        await self.collection.create_index("user_id")
        await self.collection.create_index("period_no")
        await self.collection.create_index("status")

    async def create(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        now = get_utc_timestamp()
        order_data.setdefault("created_at", now)
        order_data.setdefault("updated_at", now)
        result = await self.collection.insert_one(order_data)
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

    async def get_active_subscription_order(self, user_id: str) -> Optional[Dict[str, Any]]:
        """取得用戶目前有效的訂閱訂單（type=subscription, status=paid）"""
        return await self.collection.find_one({
            "user_id": user_id,
            "type": {"$in": ["subscription", "upgrade_subscription", "downgrade_subscription"]},
            "status": "paid",
        }, sort=[("created_at", -1)])

    async def has_pending_order(self, user_id: str, order_type: str) -> bool:
        """檢查用戶是否已有進行中的同類型訂單（防止重複付款）"""
        five_minutes_ago = get_utc_timestamp() - 300
        doc = await self.collection.find_one({
            "user_id": user_id,
            "type": order_type,
            "status": "pending",
            "created_at": {"$gt": five_minutes_ago},
        })
        return doc is not None

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
