"""
Reservation Repository - 額度預扣管理

管理用戶轉錄/AI 摘要任務的「預扣」配額。任務上傳時 reserve、完成時 consume（刪除）、
失敗/取消時 release（刪除）。

主要用途：避免多檔批次上傳 race condition 造成超額處理（abuse 防護）。
"""
import asyncio
from typing import Optional, Dict, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException, status
from pymongo.errors import OperationFailure

from ...utils.time_utils import get_utc_timestamp
from src.models.quota import tier_default
from src.utils.logger import get_logger

log = get_logger(__name__)


# 預扣類型
RESERVATION_TYPE_TRANSCRIPTION = "transcription"

# Transaction retry 設定（用於 TransientTransactionError）
_MAX_RESERVATION_RETRIES = 3
_RETRY_BASE_DELAY_SEC = 0.01


class ReservationRepository:
    """預扣配額 Repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.reservations

    async def create_indexes(self):
        """建立索引"""
        await self.collection.create_index([("user_id", 1), ("type", 1)])
        await self.collection.create_index("task_id")
        log.info("reservation.indexes.created")

    async def reserve_transcription(
        self,
        user_id: str,
        task_id: str,
        duration_minutes: float,
    ) -> str:
        """原子 check-and-reserve 轉錄時長配額

        在 MongoDB transaction 內：
        1. 讀取用戶 quota / usage / extra_quota
        2. aggregate sum 該用戶所有同類型 active 預扣
        3. 檢查 usage + reserved + needed <= plan_max + extra
        4. 通過則插入新預扣記錄、回傳 reservation_id
        5. 不通過則 raise 429

        Raises:
            HTTPException 429: 額度不足
            HTTPException 404: 用戶不存在
        """
        if duration_minutes <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="duration_minutes 必須為正數"
            )

        # 先在 transaction 外觸發月配額重置（若該重置則寫入 DB；不重置則 no-op）
        # 這樣 transaction 內讀到的 usage 是最新的
        from src.auth.quota import QuotaManager
        user_for_reset = await self.db.users.find_one({"_id": ObjectId(user_id)})
        if user_for_reset:
            await QuotaManager._reset_monthly_quota_if_needed(
                user_for_reset, user_for_reset.get("usage", {}), db=self.db
            )

        # 為什麼需要 retry：MongoDB transaction 是 snapshot isolation，不是 serializable。
        # 兩個平行的 reserve 對同 user 都讀相同 snapshot、都通過 check、寫不同 reservation doc，
        # 兩個都會 commit 成功，造成總和超扣。
        # 解法：transaction 內對 user doc 做 sentinel write（強制兩個 txn 在 user doc 衝突），
        # 落敗那個會拿到 TransientTransactionError，由 retry 重新走一次（這次會看到對方的 reservation）。
        client = self.db.client
        last_error: Optional[Exception] = None
        for attempt in range(_MAX_RESERVATION_RETRIES):
            try:
                async with await client.start_session() as session:
                    async with session.start_transaction():
                        # 1. 讀用戶
                        user = await self.db.users.find_one(
                            {"_id": ObjectId(user_id)},
                            session=session,
                        )
                        if not user:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail="用戶不存在",
                            )

                        # 2. aggregate 計算當前已預扣總時長（包含其他並發 txn 已 commit 的）
                        agg_pipeline = [
                            {"$match": {
                                "user_id": user_id,
                                "type": RESERVATION_TYPE_TRANSCRIPTION,
                            }},
                            {"$group": {
                                "_id": None,
                                "total": {"$sum": "$duration_minutes"},
                            }},
                        ]
                        cursor = self.collection.aggregate(agg_pipeline, session=session)
                        docs = await cursor.to_list(length=1)
                        total_reserved = docs[0]["total"] if docs else 0.0

                        # 3. 檢查
                        plan_max = (user.get("quota") or {}).get("max_duration_minutes") or tier_default(user, "max_duration_minutes")
                        current_usage = (user.get("usage") or {}).get("duration_minutes", 0)
                        extra = (user.get("extra_quota") or {}).get("duration_minutes", 0)

                        plan_remaining = max(0.0, plan_max - current_usage)
                        available = plan_remaining + extra - total_reserved

                        if duration_minutes > available:
                            raise HTTPException(
                                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="轉錄時長配額不足"
                            )

                        # 4. Sentinel write：寫 user doc，強制平行 txn 在此衝突
                        now = get_utc_timestamp()
                        await self.db.users.update_one(
                            {"_id": ObjectId(user_id)},
                            {"$set": {"updated_at": now}},
                            session=session,
                        )

                        # 5. 插入預扣
                        doc = {
                            "user_id": user_id,
                            "task_id": task_id,
                            "type": RESERVATION_TYPE_TRANSCRIPTION,
                            "duration_minutes": duration_minutes,
                            "created_at": now,
                        }
                        result = await self.collection.insert_one(doc, session=session)
                        return str(result.inserted_id)
            except HTTPException:
                # 業務邏輯錯誤（404/429），不 retry
                raise
            except OperationFailure as e:
                last_error = e
                # 只 retry transient transaction error（如 WriteConflict）
                if e.has_error_label("TransientTransactionError") and attempt < _MAX_RESERVATION_RETRIES - 1:
                    await asyncio.sleep(_RETRY_BASE_DELAY_SEC * (2 ** attempt))
                    continue
                raise

        # 理論上不會走到這（要嘛 return、要嘛 raise），保底
        if last_error:
            raise last_error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="預扣失敗，請稍後再試",
        )

    async def release_by_task_id(self, task_id: str) -> bool:
        """釋放任務的預扣（失敗、取消、刪除時呼叫）

        若預扣已不存在（已被消耗或已釋放），回 False 但不報錯（idempotent）。
        """
        result = await self.collection.delete_one({"task_id": task_id})
        return result.deleted_count > 0

    async def sweep_orphaned_reservations(self, grace_seconds: int = 3600) -> int:
        """清掃孤兒轉錄預扣（背景任務用）

        孤兒 = 預扣記錄還在，但對應 task 已進入終態（completed/failed/cancelled）、
        已軟刪除、或根本不存在（reserve 成功後請求就崩潰，task doc 從未建立）。
        成因：process 在 reserve 之後、consume/release 之前崩潰。

        防誤刪設計：
        - 只掃 created_at 早於 grace_seconds 的記錄：避免誤刪剛 reserve、task doc
          還沒寫入 DB 的預扣（reserve 與 task 建立在同一請求內、相隔毫秒）。
        - 對 pending/processing 的 task 一律保留預扣（即使很舊），因為任務仍可能
          完成並 consume——寧可晚點清，也不要在任務還活著時清掉造成漏扣。

        Returns:
            清掉的預扣數量
        """
        cutoff = get_utc_timestamp() - grace_seconds
        removed = 0
        cursor = self.collection.find(
            {"type": RESERVATION_TYPE_TRANSCRIPTION, "created_at": {"$lt": cutoff}}
        )
        async for resv in cursor:
            task = await self.db.tasks.find_one(
                {"_id": resv.get("task_id")},
                {"status": 1, "deleted": 1},
            )
            is_orphan = (
                task is None
                or task.get("deleted")
                or task.get("status") in ("completed", "failed", "cancelled")
            )
            if is_orphan:
                result = await self.collection.delete_one({"_id": resv["_id"]})
                removed += result.deleted_count
        return removed


# ===== Sync helpers（給 worker 用 pymongo 同步 db）=====
#
# ⚠️ 設計決定：consume + pipeline 不用 transaction 包覆
# ----------------------------------------------------
# Caller（orchestrator._mark_completed，兩進程共用）會依序執行：
#   1. consume_reservation_sync()      # 刪預扣
#   2. db.users.update_one(pipeline)   # 套用扣款
#
# 兩步之間若 step 2 故障，會漏算一次（預扣已刪、扣款未套用）。
#
# 為何不用 transaction：
#   - 多 1 個 commit round-trip（~5–50ms），worker 高峰量可累積成本
#   - 失敗機率極低（要 step 1 成功但 step 2 失敗，網路時序窗 < 1ms）
#   - 影響有限（單次轉錄時長，非 abuse 攻擊路徑）
#   - 對比 reservation 端的 transaction 是「防 abuse 主防線」，這邊只是防禦性
#
# 監控：caller 在 step 2 失敗時會印 [QUOTA_LEAK] log，可在 CloudWatch/Grafana
# 設規則統計出現次數，若觀察到頻繁發生再評估補回 transaction。


def consume_reservation_sync(db, task_id: str) -> Optional[Dict[str, Any]]:
    """同步 consume：atomic findOneAndDelete

    用於 worker（pymongo sync db）。原子刪除預扣並回傳被刪的 doc。
    若已不存在則回 None；caller 應視為「已被處理過」並跳過扣款。
    """
    return db.reservations.find_one_and_delete({"task_id": task_id})


def release_reservation_sync(db, task_id: str) -> bool:
    """同步 release：用於 worker 失敗處理"""
    result = db.reservations.delete_one({"task_id": task_id})
    return result.deleted_count > 0


# ===== 背景清掃任務 =====


async def periodic_reservation_cleanup(db, interval_seconds: int = 1800) -> None:
    """定期清掃孤兒預扣（背景任務，由 main.py startup 啟動）

    同時清理兩種孤兒，成因都是 process 在 reserve 之後、consume/release 之前崩潰：
      - 轉錄預扣（reservations collection）：對應 task 已終結卻沒被 consume/release
      - AI 摘要預扣（users.reserved_ai_summaries 計數器）：請求中途崩潰留下的殘值

    正常流程一定會 consume 或 release，不會留下殘留——這只是防崩潰的保險。
    """
    reservation_repo = ReservationRepository(db)
    while True:
        try:
            await asyncio.sleep(interval_seconds)

            removed = await reservation_repo.sweep_orphaned_reservations()
            if removed:
                log.info("reservation.sweep.transcription.completed", removed=removed)

            from src.auth.quota import QuotaManager
            fixed = await QuotaManager.sweep_stale_ai_summary_reservations(db)
            if fixed:
                log.info("reservation.sweep.ai_summary.completed", fixed=fixed)
        except Exception as e:
            log.error("reservation.sweep.failed", error=str(e), exc_info=True)
