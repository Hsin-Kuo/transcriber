"""訂單資料存取層"""
import asyncio
from typing import Optional, Dict, Any, List, Tuple, AsyncIterator
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ...utils.time_utils import get_utc_timestamp
from ...utils.logger import get_logger

log = get_logger(__name__)


# P1-5（金流體檢）：全額退款時效檢查用的訂閱型 order type 白名單。刻意在這裡獨立
# 定義一份、不從 services/order_settlement.py 匯入同名常數——repository 層不應該
# 依賴 service 層（會造成循環 import：order_settlement 已經 import 這個 repo 模組）。
_SUBSCRIPTION_ORDER_TYPES = ("subscription", "upgrade_subscription", "downgrade_subscription", "renewal")


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
        # P1-9 對帳 sweep：查「有 trade_id 的 pending/expired 單」的複合索引。
        await self.collection.create_index([("status", 1), ("trade_id", 1)])
        # P1-5 退款稽核 sweep：paid 單 30 天窗口 + refund_audited_at 排序——沒有這顆，
        # orders 累積後會全量掃 paid 單 + in-memory sort（32MB 上限炸掉整輪，而這支
        # 是 paid 單退款的唯一 fallback）。
        await self.collection.create_index([("status", 1), ("paid_at", -1)])
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

    async def clear_card_token(self, merchant_order_no: str) -> bool:
        """`$unset` order 的 card_token（P2-10，金流體檢）。

        settle 把 order.card_token 搬進 subscription 之後呼叫——orders 那份只是
        搬移中繼，訂閱已有（加密）副本，留著等於免 CVV 續扣憑證雙份留存，徒增
        暴露面。`update_by_order_no` 是 `$set` 語意做不到 unset，故獨立一支方法。
        """
        result = await self.collection.update_one(
            {"merchant_order_no": merchant_order_no},
            {"$unset": {"card_token": ""}},
        )
        return result.modified_count > 0

    async def claim_paid(
        self, merchant_order_no: str, extra_updates: Optional[Dict[str, Any]] = None
    ) -> bool:
        """原子搶單：只有 status != paid 時才寫入 paid + paid_at（含 extra_updates）。

        這是 settle() 的權威重入防線（P0-1/P0-3）：不論首購或續扣、不論走 /callback
        webhook 或 renewal sweep，同一張 order 只有一個呼叫者能把 status 從非 paid
        翻成 paid——回傳 True 才代表「這次呼叫贏得了施加權益的權利」。搶不到（False）
        代表已有別的 worker/路徑結算過這張單，caller 應回 ALREADY_PAID、不再施加任何
        權益副作用（$inc 配額、展期等），避免同一筆付款被重放成雙倍權益。
        """
        now = get_utc_timestamp()
        updates: Dict[str, Any] = {"status": "paid", "paid_at": now, "updated_at": now}
        if extra_updates:
            updates.update(extra_updates)
        result = await self.collection.update_one(
            {"merchant_order_no": merchant_order_no, "status": {"$ne": "paid"}},
            {"$set": updates},
        )
        return result.modified_count == 1

    async def mark_failed_unless_paid(self, merchant_order_no: str, updates: Dict[str, Any]) -> bool:
        """標記失敗，但不得覆寫已 paid 的單。

        遲到的舊 trade 失敗通知（例如重試中的某一封先被結算成功，另一封較舊的失敗
        通知才姍姍來遲）不能把已經付款成功的單打成 failed。回傳是否真的寫入。
        """
        updates = dict(updates)
        updates["updated_at"] = get_utc_timestamp()
        result = await self.collection.update_one(
            {"merchant_order_no": merchant_order_no, "status": {"$ne": "paid"}},
            {"$set": updates},
        )
        return result.modified_count == 1

    async def sweep_expired_pending_orders(self) -> int:
        """將過期的 pending 訂單標記為 expired（保留記錄便於審計）。

        P1-9 分工：有 `trade_id`（代表已進入 91APP 付款流程，callback 可能遺失）的
        pending 單不再由這個 1 小時 sweep 直接標 expired——它們歸
        `payment_reconciliation.run_reconciliation_sweep` 主動回查 91APP 收斂管轄，
        避免「callback 逾時 500 → 91APP 不重送 → 這裡在 T+1h 把已扣款的單標成
        expired」的靜默漏單（金流體檢 P1-9）。沒有 trade_id＝從未成功發起付款
        （例如 checkout 建單後使用者直接關頁），維持原本 1 小時過期邏輯。
        """
        now = get_utc_timestamp()
        result = await self.collection.update_many(
            {
                "status": "pending",
                "expires_at": {"$lt": now},
                "trade_id": {"$in": [None, ""]},
            },
            {"$set": {"status": "expired", "updated_at": now}}
        )
        return result.modified_count

    # ── P1-9 對帳補償 sweep ──────────────────────────────────────────────────

    # 單輪對帳上限：每筆最壞情況會觸發 91APP query_trade（httpx timeout 30s），
    # 若懸而不決的單一輪撈太多，sweep 本身可能跑超過 lease 窗（見
    # payment_reconciliation.periodic_payment_reconciliation 的 window-lease），
    # 讓下一輪還沒開始上一輪就還在跑。50 筆 * 最壞 30s ≈ 25 分鐘，留在單一 lease
    # 窗（預設 600 秒間隔）的合理量級內；沒清完的下一輪繼續掃（沒有遺漏，只是分批）。
    RECONCILIATION_BATCH_LIMIT = 50

    async def claim_marker(self, merchant_order_no: str, marker: str) -> bool:
        """一次性 order-level marker 搶閘（P0-3 系列「先搶後施」延伸）。

        `$inc` 型權益副作用（例如 add_extra_quota）若沒有原子閘門，補償 sweep 重跑
        會造成重複發放。改用 marker 先搶（`$ne True` → `$set True`），贏了才施加
        `$inc`——`modified_count == 1` 才算贏，之後同一個 marker 再呼叫一律輸，天然
        冪等。

        🔴 第二意見審查 P2-H 更正：「marker 已領但 $inc 未施」只可能發生在這兩行
        之間極窄的 crash 窗口（`claim_marker` 的 `update_one` 已經 commit，但緊接著
        的 `add_extra_quota` `$inc` 還沒執行就掛了）——`resettle_entitlement` 重跑
        到這裡時無法區分「$inc 已經真的施加過」與「就是卡在這個窄縫」，只能兩者都
        視為「已施加」而跳過（`claim_marker` 回 False 就不再呼叫 `add_extra_quota`）。
        這是已接受的殘餘風險（延續 P0-3「寧少發勿重發」），**不**對這個情況告警——
        marker=False 絕大多數時候代表的是正常情況（$inc 已經成功施加過），對它告警
        只會製造噪音，真正需要人工介入的是 handler 本身拋例外的路徑（那條路徑走
        `_handle_resettle_failure` 的 needs_manual/Sentry，見 order_settlement.py）。
        """
        now = get_utc_timestamp()
        result = await self.collection.update_one(
            {"merchant_order_no": merchant_order_no, marker: {"$ne": True}},
            {"$set": {marker: True, "updated_at": now}},
        )
        return result.modified_count == 1

    async def increment_entitlement_retry(self, merchant_order_no: str) -> int:
        """`$inc entitlement_retry_count`，回傳遞增後的新值（供呼叫端判斷是否達重試上限）。"""
        doc = await self.collection.find_one_and_update(
            {"merchant_order_no": merchant_order_no},
            {"$inc": {"entitlement_retry_count": 1}, "$set": {"updated_at": get_utc_timestamp()}},
            return_document=ReturnDocument.AFTER,
        )
        return int((doc or {}).get("entitlement_retry_count", 0))

    async def stamp_reconciliation_first_seen(self, merchant_order_no: str, ts: float) -> None:
        """僅在欄位不存在時寫入「sweep 第一次遭遇這筆單」的時間戳（條件式寫入，
        `$setOnInsert` 只能用在 upsert，這裡不是 upsert 場景，改用 filter 排除已存在
        欄位的方式達成同樣的「只寫一次」效果）。

        供 `_maybe_give_up` 的 72 小時放棄時鐘計時起點：改用「sweep 首次遭遇」而非
        `created_at`，避免上線當下 backfill 到一批已經建立超過 72 小時的歷史 pending
        單，第一輪掃描就把它們全部判定放棄+告警風暴（見金流體檢 P1-9 第二意見審查
        P1-D）。
        """
        await self.collection.update_one(
            {"merchant_order_no": merchant_order_no, "reconciliation_first_seen_at": {"$exists": False}},
            {"$set": {"reconciliation_first_seen_at": ts, "updated_at": ts}},
        )

    async def iter_for_reconciliation(self, age_gate_seconds: int) -> AsyncIterator[Dict[str, Any]]:
        """撈「已進入付款（有 trade_id）但仍 pending/expired」且已過 age gate 的單。

        age gate（預設 15 分鐘）避免跟進行中的 3D 導頁流程賽跑——使用者可能還在
        銀行頁面，這時單子必然還是 pending，主動回查只是浪費一次 API 呼叫。
        `reconciliation_gave_up: True`（72h 仍懸而不決，本地放棄）與
        `refund_seen: True`（已認出是退款，P1-5 範圍前不再處理）的單都已有明確
        終局判定，排除在外不再重查。`.limit()` 見 `RECONCILIATION_BATCH_LIMIT`。

        排序用 `last_reconciled_at` 升冪（缺欄位＝從未處理過，BSON 排序在最前）：
        搭配 sweep 每筆處理前 stamp 該欄位，讓積壓超過 batch 上限時批次會輪替——
        否則 unresolved 單不改任何欄位，每輪撈到完全相同的前 50 筆，尾端的單要等
        頭部 72h gave_up 才輪得到（第二意見審查的飢餓觀察）。
        """
        cutoff = get_utc_timestamp() - age_gate_seconds
        cursor = self.collection.find({
            "status": {"$in": ["pending", "expired"]},
            "trade_id": {"$nin": [None, ""]},
            "created_at": {"$lte": cutoff},
            "reconciliation_gave_up": {"$ne": True},
            "refund_seen": {"$ne": True},
        }).sort("last_reconciled_at", 1).limit(self.RECONCILIATION_BATCH_LIMIT)
        async for doc in cursor:
            yield doc

    async def iter_entitlement_pending(self, max_retry: int) -> AsyncIterator[Dict[str, Any]]:
        """撈「已 paid 但權益可能未施加完整」（entitlement_pending）且未達重試上限的單。

        🔴 第二意見審查 P0-A 修正：**不能用 `$lt`**。MongoDB 的比較運算子（`$lt`/
        `$gt`/`$gte`/`$lte`）採 type bracketing——只跟「型別相容」的值比較，缺欄位
        的文件**不會**被 range 運算子匹配到（這跟 `sort()` 的 BSON 排序規則 null <
        數字是兩回事，range query 不適用那套排序）。若 `entitlement_retry_count`
        缺欄位（`_mark_entitlement_pending` 若忘記初始化就會是這樣），`$lt` 永遠
        查不到它，真實 crash 留下的單會被這支 sweep 永久忽略。改用 `$not: {"$gte":
        max_retry}}`——`$not` 對「查詢條件不成立」（含欄位不存在、比較不適用型別）
        一律視為滿足，缺欄位與退回的整數值都能正確匹配。此修正已用真 Mongo 驗證，
        見 tests/database/test_order_repo_mongo.py。
        """
        cursor = self.collection.find({
            "entitlement_pending": True,
            "entitlement_retry_count": {"$not": {"$gte": max_retry}},
            # F1（跨 PR 複檢）：已被退款流程處置過的單不得再補施權益——否則
            # 「首購 crash 留 entitlement_pending → 全額退款撤訂閱 → resettle 又把訂閱
            # 開回來、甚至重開一張真發票」。refund_seen 是全額(claim_refund_processed)
            # 與部分(flag_partial_refund)退款都會寫的共同旗標。resettle_entitlement 進入
            # 時另有重讀守門擋住 cursor 讀取後才退款的競態。
            "refund_seen": {"$ne": True},
        })
        async for doc in cursor:
            yield doc

    # ── P1-5 退款/爭議款處置 ─────────────────────────────────────────────────

    async def claim_refund_processed(self, merchant_order_no: str) -> bool:
        """退款處理冪等閘門（P1-5）：形狀比照 `claim_paid`——只有第一個呼叫者能把
        `refund_processed` 從未設定（或非 True）翻成 True。`/callback` 與對帳
        sweep（`payment_reconciliation._reconcile_one`）都可能對同一筆退款通知觸發
        `OrderSettlement.handle_full_refund`/`flag_partial_refund`，只有贏得這個
        閘門的呼叫者才該執行後續動作（自動降級/標記人工/扣回額度/作廢發票），輸家
        回 False，呼叫端應視為 "already_processed" 直接跳過——避免重複降級、重複
        扣額度、重複告警。

        一併寫入 `refund_seen: True`：`OrderRepository.iter_for_reconciliation` 的
        查詢層排除條件本來就是 `refund_seen: {"$ne": True}`（P1-C 遺留），這裡沿用
        同一個旗標當作「這筆退款已經有結果了，對帳 sweep 不用再重查」的天然停止點，
        不需要另外改查詢條件。
        """
        now = get_utc_timestamp()
        result = await self.collection.update_one(
            {"merchant_order_no": merchant_order_no, "refund_processed": {"$ne": True}},
            {"$set": {"refund_processed": True, "refunded_at": now, "refund_seen": True}},
        )
        return result.modified_count == 1

    async def has_newer_paid_subscription_order(self, user_id: str, paid_at: Optional[float]) -> bool:
        """該 user 是否存在『比 `paid_at` 更新』的已付款訂閱型訂單（P1-5 時效檢查）。

        fail-safe 核心：全額退款 callback 對應到的可能是舊期別的單——若使用者在那之後
        已經重新付款過（新單的 `paid_at` 晚於這張退款單），代表訂閱早就被新單接手，
        這時自動降級是誤殺（會把使用者剛付的新期別也降掉），必須轉人工判斷，不能
        自動處理。

        `paid_at` 為 None 時（理論上不會發生——呼叫端只在 order.status=="paid" 之後
        才會走到這裡，`claim_paid` 保證寫入 `paid_at`；防禦性處理仍保留）視為「任何
        一筆已付款訂閱單都算更新」，一律回 True 轉人工，不冒險自動降級。
        """
        query: Dict[str, Any] = {
            "user_id": user_id,
            "type": {"$in": list(_SUBSCRIPTION_ORDER_TYPES)},
            "status": "paid",
        }
        query["paid_at"] = {"$gt": paid_at} if paid_at is not None else {"$exists": True}
        doc = await self.collection.find_one(query)
        return doc is not None

    # M3（第二意見審查）：paid 單退款稽核 lane——`/callback` 是 paid 單退款唯一即時
    # 路徑，91APP 若真的沒打 callback（或打到但被吃掉），一張已 paid 的訂閱/加購單
    # 被使用者事後對發卡行申訴退款，系統完全沒有第二條路能發現。這是唯一 fallback。
    REFUND_AUDIT_BATCH_LIMIT = 200
    REFUND_AUDIT_WINDOW_SECONDS = 30 * 24 * 3600

    async def iter_for_refund_audit(self) -> AsyncIterator[Dict[str, Any]]:
        """撈「30 天內 paid、還沒被退款流程認領過」的訂閱型/extra_quota 單。

        30 天窗口：91APP/發卡行的退款爭議申訴實務上不會拖超過這個量級，且訂閱大多
        月繳/年繳循環，避免每天對帳量隨帳期無限累積。排除條件用 `refund_seen`
        而非 `refund_processed`（第二意見複核 N1）：M5 拆閘門後 `flag_partial_refund`
        只寫 refund_seen 不寫 refund_processed——若排除鍵用後者，部分退款單會在
        30 天窗口內每天被重新 query_trade + 重呼（claim_marker 擋住無副作用，但白燒
        API 額度且讓 refund_partial 計數每日虛增）。refund_seen 是兩條退款路徑都會
        寫的共同旗標，語意即「這筆退款已有結果」。

        排序用 `refund_audited_at` 升冪（缺欄位＝從未稽核過，BSON 排序在最前）：
        搭配每筆處理前先 stamp 該欄位（見 `stamp_refund_audited`），讓積壓超過
        batch 上限時批次會輪替，比照 `iter_for_reconciliation` 的既有手法。
        """
        cutoff = get_utc_timestamp() - self.REFUND_AUDIT_WINDOW_SECONDS
        cursor = self.collection.find({
            "status": "paid",
            "type": {"$in": list(_SUBSCRIPTION_ORDER_TYPES) + ["extra_quota"]},
            "refund_seen": {"$ne": True},
            "paid_at": {"$gte": cutoff},
        }).sort("refund_audited_at", 1).limit(self.REFUND_AUDIT_BATCH_LIMIT)
        async for doc in cursor:
            yield doc

    async def stamp_refund_audited(self, merchant_order_no: str, ts: float) -> None:
        """輪替 stamp（比照 `_reconcile_one` 的 `last_reconciled_at`）：每筆處理前
        先寫，讓 `iter_for_refund_audit` 依此升冪撈單時，積壓超過 batch 上限的單
        不會永遠卡在佇列頭部沒被排到。"""
        await self.collection.update_one(
            {"merchant_order_no": merchant_order_no},
            {"$set": {"refund_audited_at": ts}},
        )

    # P2-13（金流體檢）：開票補洞 sweep——settle() 的 `create_background_task(issue_for_order(...))`
    # 是唯一的開票起點，若該 asyncio task 在 upsert_initial 落地前就被 process kill
    # （部署重啟、OOM），這筆訂單永遠不會有 invoice doc，且不留任何痕跡（沒有例外、
    # 沒有 log）。既有的 `run_invoice_retry_sweep` 只掃「已存在」的 invoices doc，
    # 對這種「doc 從未落地」的洞完全補不到，需要反過來從 orders 找。
    INVOICE_GAP_MIN_AGE_SECONDS = 600   # 給正常 fire-and-forget 路徑跑完的時間，避免跟它賽跑
    INVOICE_GAP_MAX_AGE_SECONDS = 7 * 24 * 3600  # 控制掃描量，超過這個窗的漏單交人工
    INVOICE_GAP_BATCH_LIMIT = 50

    async def iter_paid_invoice_gap_candidates(
        self, now: float, epoch: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        """撈「已付款、可能從未觸發開票」的候選單（doc 是否真的存在由呼叫端查 invoice_repo 判斷）。

        `is_duplicate`/`refund_processed` 已終局的單排除在外——它們的 settle 路徑本來
        就不會（或不該再）觸發開票，不算「洞」。時間窗見上方兩個常數的說明。

        `epoch`（第二意見審查 M2）：只補 `paid_at >= epoch` 的單。防首次部署一次性 retro
        補開過去 7 天所有無 doc 的 paid 單——這些單可能已在速買配後台人工開過票，重複開
        真發票是不可逆的稅務事件。epoch 由 INVOICE_GAP_EPOCH env 明確給定（見 sweep）。

        排序用 `invoice_gap_checked_at` 升冪（缺欄位＝從未檢查過，BSON 排序在最前，M1）：
        搭配 sweep 每筆檢查後 stamp 該欄位，積壓超過 batch 上限時批次會輪替；否則候選集
        （paid_at 區間，不因檢查而改變）每輪固定回傳最舊 50 筆，較新的洞要等前面的單老出
        7 天窗才輪得到，補洞延遲從 10 分鐘退化成近 7 天。
        """
        lower = max(now - self.INVOICE_GAP_MAX_AGE_SECONDS, epoch)
        cursor = self.collection.find({
            "status": "paid",
            "paid_at": {
                "$gte": lower,
                "$lte": now - self.INVOICE_GAP_MIN_AGE_SECONDS,
            },
            "is_duplicate": {"$ne": True},
            "refund_processed": {"$ne": True},
        }).sort("invoice_gap_checked_at", 1).limit(self.INVOICE_GAP_BATCH_LIMIT)
        async for doc in cursor:
            yield doc

    async def stamp_invoice_gap_checked(self, merchant_order_no: str, ts: float) -> None:
        """gap sweep 檢查過一筆就 stamp（不論補開或已有 doc）——推進輪替游標（M1）。"""
        await self.collection.update_one(
            {"merchant_order_no": merchant_order_no},
            {"$set": {"invoice_gap_checked_at": ts}},
        )

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
    """定期清掃過期未付款訂單（背景任務，由 main.py startup 啟動）。

    🔴 P0-2(a)：prod 兩個 uvicorn worker 都跑這個背景任務，用 JobLeaseRepository 對
    本輪時間窗搶執行權，避免同一輪清掃被跑兩次。lease 檢查本身失敗（DB 例外）採
    fail-open，照跑本輪並記警告——sweep 冪等，寧可偶發重跑也不要背景任務全停。
    """
    from .job_lease_repo import JobLeaseRepository
    order_repo = OrderRepository(db)
    lease_repo = JobLeaseRepository(db)
    while True:
        await asyncio.sleep(interval_seconds)
        should_run = True
        try:
            should_run = await lease_repo.claim_window("order_cleanup", interval_seconds)
        except Exception as e:
            log.warning("order.sweep.lease_check_failed", error=str(e))
        if not should_run:
            continue
        try:
            expired = await order_repo.sweep_expired_pending_orders()
            purged = await order_repo.purge_old_superseded_orders()
            if expired or purged:
                log.info("order.sweep.completed", expired=expired, purged_superseded=purged)
        except Exception as e:
            log.error("order.sweep.failed", error=str(e), exc_info=True)
