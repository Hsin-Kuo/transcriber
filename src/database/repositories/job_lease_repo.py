"""背景 job 的 per-window leader lease。

P0-2(a)：prod 用 `uvicorn --workers 2`，兩個 worker process 都會跑 main.py 啟動的背景
sweep（renewal / invoice retry / subscription expiry / order cleanup）。這些 sweep 會動
金流/訂閱狀態，若不做窗口互斥，同一輪掃描被兩個 worker 各跑一次，會造成重複續扣嘗試、
重複降級判定等併發面。

形狀比照 processed_webhook_repo 的 claim()：`_id` unique insert + DuplicateKeyError 判斷
輸贏，靠 Mongo `_id` 唯一約束達成「同一時間窗至多一個 worker 執行」，不需要額外鎖或
transaction。`_id` 用 deterministic key `<job>:<window>`（window = 目前時間整除 window 秒數），
同一個時間窗內不論哪個 worker 先呼叫都只有一個能 insert 成功。

⚠️ 誠實列出這個機制**不**保證的事（F3/F8，第二意見審查）：
- 只保證「同一個時間窗」互斥；不保證跨窗不重疊——若某輪 sweep 實際執行時間超過
  window_seconds（例如卡在慢速外部 API），下一個窗開始時舊的一輪可能還沒跑完，
  兩輪會並行。呼叫端的 sweep 邏輯必須自己冪等（本 repo 現有 sweep 皆是）。
- 贏家（claim 成功的那個 worker）中途 crash，該時間窗**不會**被釋放重跑——`_id`
  已經 insert 成功，直到 TTL（7 天）到期前不會有第二個 worker 能再搶到同一個窗。
  也就是說這是「盡量只跑一次」而非「保證跑一次」，跟 processed_webhook_repo 的
  claim/release 語意不同（那邊失敗會主動 release 讓人重試；這裡沒有 release）。
  若某個 sweep 的漏跑代價很高，呼叫端要自己加上額外的補償機制（例如更短的
  window、或另一個對帳 sweep）。
"""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from ...utils.time_utils import get_utc_timestamp
from ...utils.logger import get_logger

log = get_logger(__name__)


class JobLeaseRepository:
    """跨背景 job 共用的 window lease 記錄。"""

    def __init__(self, db):
        self.db = db
        self.collection = db.job_leases

    async def create_indexes(self):
        # _id 預設 unique（達成互斥）；TTL 用 created_at，保留 7 天供事後排查即可清掉。
        await self.collection.create_index(
            "created_at",
            expireAfterSeconds=7 * 24 * 3600,
        )

    async def claim_window(self, job: str, window_seconds: int) -> bool:
        """搶當前時間窗的執行權。

        Returns:
            True: 這個 (job, window) 目前由我搶到，本輪應該執行。
            False: 已有別的 worker/replica 搶到，本輪應該略過。
        """
        window = int(get_utc_timestamp() // window_seconds)
        key = f"{job}:{window}"
        try:
            await self.collection.insert_one({
                "_id": key,
                "job": job,
                "window": window,
                "created_at": datetime.now(timezone.utc),
            })
            return True
        except DuplicateKeyError:
            return False
