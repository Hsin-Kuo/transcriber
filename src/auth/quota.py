"""配額管理器"""
import asyncio
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status

from src.database.repositories.job_lease_repo import JobLeaseRepository
from src.models.quota import QUOTA_TIERS, QuotaTier, tier_default, build_quota_from_tier
from src.utils.time_utils import get_utc_timestamp, timestamp_to_datetime
from src.utils.logger import get_logger

log = get_logger(__name__)

# pipeline 在 DB 端無法跑 tier 判斷，缺欄位時對齊 FREE 設定（唯一真實來源）
_FREE_DURATION_DEFAULT = QUOTA_TIERS[QuotaTier.FREE]["max_duration_minutes"]

_PAID_ACTIVE_STATUSES = ("active", "trialing", "past_due")


def _to_datetime(value):
    """把 timestamp(float) / naive datetime / aware datetime 統一成 naive UTC datetime；
    無法辨識回 None。

    已知地雷（quota.py 舊版）：last_reset 在不同寫入路徑型別不一致——
    註冊/admin 手動重置寫 int timestamp，自動重置寫 naive datetime。若混入
    aware datetime（例如未來改用 timezone-aware 來源）會在 `>` 比較時拋
    TypeError。這裡統一轍收斂成同一種 naive UTC，讓所有比較安全。
    """
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return None


def _compute_current_period_start(user: dict, now: datetime, status_override: str = None) -> tuple:
    """算出「現在」所在週期的起點（naive UTC）與週期類型。

    單一真實來源：`_reset_monthly_quota_if_needed`（是否該重置）與
    `compute_period_usage`（admin 用量顯示）都呼叫這裡，避免兩套規則漂移。

    - 付費（active/trialing/past_due）且訂閱有 `current_period_start`（anchor）：
      anchor 制。回傳 anchor 往後推「N 個週月格」後的起點，N = 從 anchor 到
      now 經過的完整週月數（`_months_elapsed`，year 訂閱在週期內也按月格推進，
      與 `_due_monthly_refill` 判斷同一套算法）。
    - 其餘（free / 到期降級 / 無訂閱 / 缺 anchor）：UTC 日曆月（當月 1 號 00:00）。

    status_override：`_reset_monthly_quota_if_needed` 在偵測到訂閱到期
    （guard 命中降級）後，會把本地變數 `sub_status` 改成 "expired" 再繼續走
    免費邏輯，但 `_expire_subscription` 不會回寫 `user["subscription"]["status"]`
    （in-memory 的 subscription 子字典仍是 "active"）。若這裡重新從 user dict
    讀 status，會誤判成還在付費、走 anchor 制而不重置。呼叫端必須傳入本地判定
    後的 sub_status 覆寫，才能反映「已到期」這個事實。`compute_period_usage`
    沒有到期判定邏輯，不傳這個參數、直接讀 user dict 現況即可。

    回傳 (period_start: datetime, period_type: "billing_cycle" | "calendar_month")。
    """
    sub = user.get("subscription", {}) or {}
    sub_status = status_override if status_override is not None else sub.get("status")
    if sub_status in _PAID_ACTIVE_STATUSES:
        anchor = _to_datetime(sub.get("current_period_start"))
        if anchor is not None:
            months = _months_elapsed(anchor, now)
            return anchor + relativedelta(months=months), "billing_cycle"
    return datetime(now.year, now.month, 1), "calendar_month"


def _months_elapsed(anchor: datetime, point: datetime) -> int:
    """anchor → point 之間經過的完整月數（週月制；relativedelta 自動處理 1/31→2/28）。"""
    if point < anchor:
        return 0
    delta = relativedelta(point, anchor)
    return delta.years * 12 + delta.months


def _due_monthly_refill(period_start: datetime, last_reset: datetime, now: datetime) -> bool:
    """計費週期內：當 now 已跨入比 last_reset 更後面的「週月格」時為 True（冪等）。

    以 period_start 為錨，讓年繳訂閱在年度週期內也能每月 refill（不必等續扣）。
    """
    return _months_elapsed(period_start, now) > _months_elapsed(period_start, last_reset)


def _get_tier_default(user: dict, field: str, fallback=None):
    # 對齊 QUOTA_TIERS（tier 不明時退回 FREE 設定，而非硬編 fallback）
    return tier_default(user, field)


class QuotaManager:
    """配額管理器"""

    @staticmethod
    async def check_transcription_quota(user: dict, audio_duration: float, db=None):
        """檢查轉錄配額（方案額度優先，不足時使用 extra_quota）"""
        quota = user.get("quota", {})
        usage = user.get("usage", {})
        extra_quota = user.get("extra_quota", {})

        usage = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=db)

        duration_minutes = audio_duration / 60
        current_usage = usage.get("duration_minutes", 0)
        plan_limit = quota.get("max_duration_minutes") or _get_tier_default(user, "max_duration_minutes")
        plan_remaining = max(0.0, plan_limit - current_usage)
        extra_remaining = max(0.0, extra_quota.get("duration_minutes", 0))
        total_available = plan_remaining + extra_remaining

        if total_available < duration_minutes:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "message": f"轉錄時數不足（方案剩餘 {plan_remaining:.1f} 分鐘，額外額度 {extra_remaining:.1f} 分鐘）",
                    "quota": {
                        "plan_used": current_usage,
                        "plan_limit": plan_limit,
                        "plan_remaining": plan_remaining,
                        "extra_remaining": extra_remaining,
                        "total_available": total_available,
                        "requested": duration_minutes,
                        "type": "duration_minutes",
                    }
                }
            )
        return True

    @staticmethod
    async def check_concurrent_tasks(user: dict, active_count: int):
        """檢查並發任務數"""
        quota = user.get("quota", {})
        max_concurrent = quota.get("max_concurrent_tasks") or _get_tier_default(user, "max_concurrent_tasks")

        if active_count >= max_concurrent:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"已達並發任務數上限 ({max_concurrent} 個)",
                    "quota": {
                        "current": active_count,
                        "limit": max_concurrent,
                        "type": "concurrent_tasks",
                    }
                }
            )

    @staticmethod
    def _ai_summary_plan_limit(user: dict) -> int:
        """取得用戶的方案 AI 摘要上限（quota 未設定時 fallback 到 tier 預設）"""
        quota = user.get("quota", {}) or {}
        return quota.get("max_ai_summaries") or _get_tier_default(user, "max_ai_summaries")

    @staticmethod
    async def reserve_ai_summary(db, user_id: str, user: dict = None):
        """原子預扣 1 次 AI 摘要配額（防並發超扣 / 防被刷 Gemini 費用）

        方案B：只動 user doc 單一文件，用 $expr filter 做 atomic check-and-reserve，
        不需要獨立 collection、transaction、retry（與轉錄的 reservation 機制不同）。

        檢查條件（在 DB 端原子計算）：
            usage.ai_summaries + reserved_ai_summaries + 1
                <= plan_limit + extra_quota.ai_summaries
        通過則 $inc reserved_ai_summaries；find_one_and_update 回 None 代表額度不足。

        呼叫此方法成功後，務必接著呼叫：
          - consume_ai_summary()  → Gemini 成功，預扣轉為實際使用量
          - release_ai_summary()  → Gemini 失敗 / 例外，單純釋放預扣
        """
        from bson import ObjectId

        # 先觸發月配額重置（與 ReservationRepository.reserve_transcription 一致）：
        # 重置會把 usage.ai_summaries 歸零寫回 DB，下面的 $expr 才讀得到最新值。
        if user is None:
            user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用戶不存在",
            )
        await QuotaManager._reset_monthly_quota_if_needed(user, user.get("usage", {}), db=db)

        plan_limit = QuotaManager._ai_summary_plan_limit(user)

        result = await db.users.find_one_and_update(
            {
                "_id": ObjectId(user_id),
                "$expr": {
                    "$lte": [
                        {"$add": [
                            {"$ifNull": ["$usage.ai_summaries", 0]},
                            {"$ifNull": ["$reserved_ai_summaries", 0]},
                            1,
                        ]},
                        {"$add": [
                            plan_limit,
                            {"$ifNull": ["$extra_quota.ai_summaries", 0]},
                        ]},
                    ]
                },
            },
            {
                "$inc": {"reserved_ai_summaries": 1},
                "$set": {
                    # 給背景清掃任務判斷孤兒用：記錄最近一次 reserve 的時間
                    "reserved_ai_summaries_at": get_utc_timestamp(),
                    "updated_at": get_utc_timestamp(),
                },
            },
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "QUOTA_EXCEEDED",
                    "message": "AI 摘要次數不足",
                    "quota": {"type": "ai_summaries"},
                }
            )
        return True

    @staticmethod
    async def consume_ai_summary(db, user_id: str, user: dict = None):
        """將預扣轉為實際使用量（Gemini 成功後呼叫）

        原子 pipeline：扣 reserved_ai_summaries 1，並依方案餘額把這 1 次分流到
        usage.ai_summaries 或 extra_quota.ai_summaries。
        """
        from bson import ObjectId

        plan_limit = QuotaManager._ai_summary_plan_limit(user) if user else 3
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            build_ai_summary_consumption_pipeline(plan_limit, get_utc_timestamp()),
        )

    @staticmethod
    async def release_ai_summary(db, user_id: str):
        """釋放預扣（Gemini 失敗 / 例外時呼叫），不影響使用量

        用 filter 條件確保 reserved_ai_summaries 不會被扣成負數。
        """
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id), "reserved_ai_summaries": {"$gt": 0}},
            {
                "$inc": {"reserved_ai_summaries": -1},
                "$set": {"updated_at": get_utc_timestamp()},
            },
        )

    @staticmethod
    async def sweep_stale_ai_summary_reservations(db, grace_seconds: int = 1800) -> int:
        """清掃孤兒 AI 摘要預扣（背景任務用）

        AI 摘要的 reserve → consume/release 都在單一 HTTP 請求內同步完成，
        一個請求不可能跑超過 grace_seconds（預設 30 分鐘）。因此
        「reserved_ai_summaries > 0 且 reserved_ai_summaries_at 早於 cutoff」
        必定是 process 在請求中途崩潰留下的孤兒，直接歸零釋放。

        正常流程必定會 consume 或 release，不會留下殘留；只有崩潰才會。

        Returns:
            被修正的用戶數
        """
        cutoff = get_utc_timestamp() - grace_seconds
        result = await db.users.update_many(
            {
                "reserved_ai_summaries": {"$gt": 0},
                "reserved_ai_summaries_at": {"$lt": cutoff},
            },
            {
                "$set": {
                    "reserved_ai_summaries": 0,
                    "updated_at": get_utc_timestamp(),
                }
            },
        )
        return result.modified_count

    @staticmethod
    async def _reset_monthly_quota_if_needed(user: dict, usage: dict, db=None, now: datetime = None) -> dict:
        """
        重置每月配額（如需要）+ 偵測訂閱到期。

        付費用戶：新計費週期開始、或計費週期內每跨一個「週月」（解年繳一年只補一次）
        免費用戶：日曆月制
        到期偵測：current_period_end < now → 自動降為 free

        now 可注入（測試用）；預設為 utcnow()。
        """
        last_reset = usage.get("last_reset")
        if not last_reset:
            return usage

        # F1：正規化型別（int timestamp / naive / aware datetime 全部收斂成 naive UTC），
        # 消除舊版 aware/naive 混用比較拋 TypeError 的地雷。
        last_reset = _to_datetime(last_reset)
        if last_reset is None:
            return usage

        now = now or datetime.utcnow()
        sub = user.get("subscription", {})
        sub_status = sub.get("status")
        billing_cycle = sub.get("billing_cycle")
        should_reset = False
        reset_reason = None

        # ── 訂閱到期偵測 ───────────────────────────────────────
        # 只有「已排定取消」的訂閱到期才 lazy 降 free（使用者主動取消 → 期末 lapse）。
        # auto-renew 的 active 訂閱過期末不在此降級——交給 renewal_service 續扣（過期→扣款窗內仍視為有效）；
        # past_due 的寬限期滿降級也由 renewal_service 負責（單一責任，避免雙重降級）。
        if sub_status == "active" and sub.get("cancel_at_period_end"):
            period_end_dt = _to_datetime(sub.get("current_period_end"))
            if period_end_dt and period_end_dt < now:
                # F5：只在 guard 命中（真的降級）時才把本地狀態當成 expired。db 為 None
                # （純 in-memory 判定、無寫入競態）或寫入異常時沿用原保守行為當作已過期。
                expired = True
                if db is not None:
                    try:
                        expired = await QuotaManager._expire_subscription(db, user)
                    except Exception as e:
                        log.warning("quota.subscription.expire.writeback_failed", error=str(e))
                        expired = True
                if expired:
                    # 繼續走免費用戶邏輯
                    sub_status = "expired"

        # ── 重置判斷 ────────────────────────────────────────────
        # active/trialing/past_due：在「新計費週期開始」或「週期內每跨一個週月」時 refill。
        #   past_due 寬限期沿用付費 tier refill（保留服務）；後者讓年繳週期內也能每月補額。
        if sub_status in ("active", "trialing", "past_due"):
            raw_anchor = _to_datetime(sub.get("current_period_start"))
            if raw_anchor is not None:
                # F2：與 compute_period_usage 共用同一套「本週期起點」算法
                # （_compute_current_period_start），避免兩套規則漂移。
                # 數學上等價於原本的兩條件：
                #   period_start_dt > last_reset  ⟺  raw_anchor 本身晚於 last_reset
                #     （新計費週期開始）或 _due_monthly_refill 成立（週期內跨週月）。
                period_start_dt, _ptype = _compute_current_period_start(user, now, status_override=sub_status)
                if period_start_dt > last_reset:
                    should_reset = True
                    reset_reason = (
                        "billing_period_start" if raw_anchor > last_reset else "monthly_anniversary"
                    )
        else:
            # free / 到期降級 / 無訂閱：日曆月制（與 compute_period_usage 共用同一套算法）。
            # status_override=sub_status 是關鍵：sub_status 可能已被上面的到期偵測改成
            # "expired"，但 user["subscription"]["status"] 這個 dict 欄位本身沒被動過
            # （_expire_subscription 只改 DB + user["quota"]），若讓 helper 重新從 dict
            # 讀 status 會誤判成仍是 active 而走錯 anchor 制。
            period_start_dt, _ptype = _compute_current_period_start(user, now, status_override=sub_status)
            if period_start_dt > last_reset:
                should_reset, reset_reason = True, "calendar_month"

        if should_reset:
            new_usage = {
                "transcriptions": 0,
                "duration_minutes": 0,
                "ai_summaries": 0,
                "last_reset": now,
                "total_transcriptions": usage.get("total_transcriptions", 0),
                "total_duration_minutes": usage.get("total_duration_minutes", 0),
                "total_ai_summaries": usage.get("total_ai_summaries", 0),
            }

            # D4：是否在 refill 時重套最新方案（額度 + features）。
            #   - 年繳訂閱「週期內」refill 不重套 → 凍結繳費當下的額度直到換約。
            #   - free / 到期降級 / 月繳 → 重套最新，讓 QUOTA_TIERS 調整在下個週期自動生效（免 backfill）。
            yearly_intra_period = (
                sub_status in ("active", "trialing", "past_due") and billing_cycle == "yearly"
            )
            fresh_quota = None
            if not yearly_intra_period:
                tier = (user.get("quota") or {}).get("tier") or QuotaTier.FREE.value
                try:
                    fresh_quota = build_quota_from_tier(tier)
                except (KeyError, ValueError):
                    fresh_quota = None  # 無法辨識的 tier 不覆寫，避免破壞資料

            if db is not None:
                try:
                    from bson import ObjectId
                    set_fields = {
                        "usage.transcriptions": 0,
                        "usage.duration_minutes": 0,
                        "usage.ai_summaries": 0,
                        "usage.last_reset": now,
                        "updated_at": get_utc_timestamp(),
                    }
                    if fresh_quota is not None:
                        set_fields["quota"] = fresh_quota
                    await db.users.update_one(
                        {"_id": ObjectId(str(user["_id"]))},
                        {"$set": set_fields},
                    )
                except Exception as e:
                    log.warning("quota.monthly_reset.writeback_failed", error=str(e))

            log.info(
                "quota.monthly_reset",
                user_id=str(user.get("_id")),
                reason=reset_reason,
                reapplied_quota=fresh_quota is not None,
            )

            # 同步記憶體中的 user，讓同一請求後續讀到的是新方案
            if fresh_quota is not None:
                user["quota"] = fresh_quota
            return new_usage

        return usage

    @staticmethod
    async def _expire_subscription(db, user: dict) -> bool:
        """訂閱到期：更新狀態並降為 free 配額。回傳是否真的降級（guard 命中）。

        F5（跨 PR 複檢）：sweep 是「cursor 撈單 → 逐筆處理」，撈單與這裡的寫入之間使用者
        可能成功 /reactivate（把 cancel_at_period_end 設 False、current_period_end 續期）。
        update_one 的 filter 原子重申 sweep 的選取條件（status=active + cancel_at_period_end
        + current_period_end<now），reactivate 後這些不再成立 → 不寫入、不動 in-memory
        quota、不 reconcile 釘選音檔——否則會靜默把剛恢復的付費訂閱蓋回 expired+free，而
        續扣 sweep 只查 active/past_due，這帳號再也不會被撈到、無告警。#324 對其他訂閱寫入
        建立的樂觀鎖紀律，這支 sweep 補齊。
        """
        from bson import ObjectId
        from src.models.quota import QUOTA_TIERS, QuotaTier

        user_id = str(user["_id"])
        now = datetime.utcnow()
        free_config = QUOTA_TIERS[QuotaTier.FREE]
        free_quota = {
            "tier": "free",
            **{k: v for k, v in free_config.items() if k not in ("name", "price")},
        }

        result = await db.users.update_one(
            {
                "_id": ObjectId(user_id),
                "subscription.status": "active",
                "subscription.cancel_at_period_end": True,
                "subscription.current_period_end": {"$lt": now.timestamp()},
            },
            {
                "$set": {
                    "subscription.status": "expired",
                    "subscription.updated_at": now.timestamp(),
                    "quota": free_quota,
                    "updated_at": get_utc_timestamp(),
                }
            }
        )
        if result.matched_count == 0:
            # guard 未命中：使用者在撈單後、寫入前 reactivate（或狀態已被其他路徑改動）。
            # 不降級、不動 in-memory quota、不釋放釘選音檔。
            log.info("quota.subscription.expire.skipped_reactivated", user_id=user_id)
            return False
        # 同步 in-memory user，避免同一次呼叫後續（月配額重置的 tier 重套）讀到 stale 的付費 tier
        user["quota"] = free_quota
        log.warning("quota.subscription.expired", user_id=user_id, downgraded_to="free")

        # 降為 free（quota 已 commit）：釋放超過 free 額度的釘選音檔進寬限期。
        #   best-effort：reconcile 自行吞例外；此處再包一層防呆，確保到期降級流程不被拖垮。
        try:
            from src.services.pinned_audio_reconciler import reconcile_pinned_audio
            await reconcile_pinned_audio(db, user_id, "free")
        except Exception as e:
            log.warning("quota.subscription.expire.reconcile_failed", user_id=user_id, error=str(e))

        # 期末取消生效降 free 通知信（best-effort，絕不拖垮到期 sweep）。只在真的降級
        # （guard 命中，走到這裡）才寄；guard 未命中的 no-op（上方 return False）不寄。
        await QuotaManager._send_subscription_ended_email(user)
        return True

    @staticmethod
    async def _send_subscription_ended_email(user: dict) -> None:
        """訂閱到期轉免費通知（best-effort，例外只 log，絕不拖垮呼叫端的到期 sweep）。

        `user` 是降級前的快照——本函式呼叫時 DB 已被上面的 update_one 改成
        expired/free，但傳入的 `user` dict 只有 `quota` 欄位被本函式重寫成
        free_quota，`user["subscription"]` 這個子字典本身沒被動過，因此 tier 仍是
        降級前的方案（用快照的 tier 才對，不能讀已被覆寫的 quota.tier）。
        """
        try:
            to = user.get("email")
            if not to or user.get("email_bounced"):
                return
            lang = (user.get("preferences") or {}).get("language", "zh-TW")
            tier = (user.get("subscription") or {}).get("tier")
            try:
                if lang == "en":
                    plan = str(QuotaTier(tier).value).capitalize()
                else:
                    plan = QUOTA_TIERS[QuotaTier(tier)]["name"]
            except (ValueError, KeyError):
                plan = str(tier).capitalize()

            from src.utils.email_service import get_email_service
            svc = get_email_service()
            await svc.send_subscription_email(to_email=to, kind="subscription_ended", lang=lang, plan=plan)
        except Exception as e:
            log.error(
                "quota.subscription_ended_email.failed",
                user_id=str(user.get("_id")), error=str(e), exc_info=True,
            )

    @staticmethod
    async def reset_user_monthly_quota(db, user_id: str):
        """手動重置用戶每月配額（新計費週期開始時）"""
        from bson import ObjectId

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "usage.transcriptions": 0,
                    "usage.duration_minutes": 0,
                    "usage.ai_summaries": 0,
                    "usage.last_reset": datetime.utcnow(),
                    "updated_at": get_utc_timestamp(),
                }
            }
        )


def compute_period_usage(user: dict, now: datetime = None) -> dict:
    """算出使用者「本週期」的用量 / 額度 / 加購剩餘（純函數，不寫 DB）。

    給 admin 用戶列表 / 詳情頁顯示用——admin 讀取路徑不能觸發 lazy reset 寫入，
    所以這裡只讀 user snapshot 自行推算，不呼叫 `_reset_monthly_quota_if_needed`。

    週期邊界規則與 `_reset_monthly_quota_if_needed` 共用 `_compute_current_period_start`
    （同一套 anchor / 日曆月算法），避免兩套規則漂移。

    used_minutes 判定：若 `usage.last_reset` 早於本週期起點，代表 lazy reset
    尚未被使用者的下一次請求觸發、DB 裡的 `usage.duration_minutes` 是上期舊快照
    （寫入者才會真正歸零，見 `_reset_monthly_quota_if_needed` 的 `should_reset`
    分支），此時視為本期已用 0；否則快照本身就是本期最新用量，直接讀。

    顯示不能比 reset 樂觀：`_reset_monthly_quota_if_needed` 在下面兩種情況下永遠
    是 no-op（不會歸零 usage，也不會寫入任何東西）——
      1. `usage.last_reset` 根本不存在（`if not last_reset: return usage`）；
      2. 付費戶（active/trialing/past_due）但 `subscription.current_period_start`
         缺失或無法解析（`raw_anchor is not None` 這個 guard 沒過，`should_reset`
         永遠是 False）。
    這兩種情況下若這裡仍套用「last_reset 早於 period_start → used=0」的判定，
    會顯示出一個 reset 從未也不會發生的「0」，比實際狀態樂觀、誤導 admin 以為
    用戶本期還沒用。因此這兩種情況一律直接回讀 `usage.duration_minutes`
    （不歸零），周期區間仍照常算給 admin 參考。

    extra_remaining_minutes：`extra_quota.duration_minutes` 語義是「剩餘餘額」
    （非「已用量」）——購買 / 訂閱升級結轉時用 `$inc` 增加
    （`user_repo.add_extra_quota`），扣抵時用
    `build_transcription_consumption_pipeline` 的 `$subtract` 原子扣減、並用
    `$max`/`$min` 保證不為負；沒有任何 expires 欄位（grep 全 repo 找不到
    extra_quota 相關的到期時間欄位）。因此這裡直接取值、下限夾在 0，
    不需要另外扣「已用量」。
    """
    now = now or datetime.utcnow()
    period_start, period_type = _compute_current_period_start(user, now)
    period_end = period_start + relativedelta(months=1)

    usage = user.get("usage", {}) or {}
    raw_used_minutes = float(usage.get("duration_minutes", 0) or 0)
    last_reset = _to_datetime(usage.get("last_reset"))

    sub_status = (user.get("subscription", {}) or {}).get("status")
    anchor_missing_for_paid = (
        sub_status in _PAID_ACTIVE_STATUSES
        and _to_datetime((user.get("subscription", {}) or {}).get("current_period_start")) is None
    )

    if last_reset is None or anchor_missing_for_paid:
        # reset 路徑在這兩種情況下永遠不會觸發 → 顯示不得比它樂觀，直接回讀快照
        used_minutes = raw_used_minutes
    elif last_reset < period_start:
        used_minutes = 0.0
    else:
        used_minutes = raw_used_minutes

    limit_minutes = (user.get("quota", {}) or {}).get("max_duration_minutes") \
        or _get_tier_default(user, "max_duration_minutes")

    extra_quota = user.get("extra_quota", {}) or {}
    extra_remaining_minutes = max(0.0, extra_quota.get("duration_minutes", 0) or 0)

    return {
        "period_type": period_type,
        "period_start": period_start.replace(tzinfo=timezone.utc).isoformat(),
        "period_end": period_end.replace(tzinfo=timezone.utc).isoformat(),
        "used_minutes": used_minutes,
        "limit_minutes": limit_minutes,
        "extra_remaining_minutes": extra_remaining_minutes,
    }


def build_transcription_consumption_pipeline(duration_minutes: float, now_ts: int) -> list:
    """建立轉錄消耗的 MongoDB pipeline update

    在 DB 端原子計算：
      plan_remaining = max(0, quota.max_duration_minutes - usage.duration_minutes)
      from_plan = min(plan_remaining, duration_minutes)
      from_extra = min(duration_minutes - from_plan, extra_quota.duration_minutes)

      usage.duration_minutes += from_plan
      extra_quota.duration_minutes -= from_extra
      usage.transcriptions += 1
      usage.total_transcriptions += 1
      usage.total_duration_minutes += duration_minutes  (永遠記實際時長)

    保證 extra_quota.duration_minutes 永不為負（被 $min 與 $max 雙重保護）。
    若 race 導致 plan + extra 不足，會「扣不完」（小幅免費），但不會破壞資料。

    Args:
        duration_minutes: 此次要扣的實際時長（分鐘）
        now_ts: updated_at 時間戳

    Returns:
        MongoDB aggregation pipeline（list of stages），給 update_one 用
    """
    return [
        # Stage 1: 算 plan_remaining
        {"$set": {
            "_plan_remaining": {
                "$max": [
                    0,
                    {"$subtract": [
                        {"$ifNull": ["$quota.max_duration_minutes", _FREE_DURATION_DEFAULT]},
                        {"$ifNull": ["$usage.duration_minutes", 0]},
                    ]},
                ]
            }
        }},
        # Stage 2: 算 from_plan
        {"$set": {
            "_from_plan": {"$min": ["$_plan_remaining", duration_minutes]}
        }},
        # Stage 3: 算 from_extra（被當下 extra 餘額 cap）
        {"$set": {
            "_from_extra": {
                "$min": [
                    {"$subtract": [duration_minutes, "$_from_plan"]},
                    {"$ifNull": ["$extra_quota.duration_minutes", 0]},
                ]
            }
        }},
        # Stage 4: 套用扣款 + 累加統計
        {"$set": {
            "usage.duration_minutes": {
                "$add": [{"$ifNull": ["$usage.duration_minutes", 0]}, "$_from_plan"]
            },
            "extra_quota.duration_minutes": {
                "$subtract": [
                    {"$ifNull": ["$extra_quota.duration_minutes", 0]},
                    "$_from_extra",
                ]
            },
            "usage.transcriptions": {
                "$add": [{"$ifNull": ["$usage.transcriptions", 0]}, 1]
            },
            "usage.total_transcriptions": {
                "$add": [{"$ifNull": ["$usage.total_transcriptions", 0]}, 1]
            },
            "usage.total_duration_minutes": {
                "$add": [{"$ifNull": ["$usage.total_duration_minutes", 0]}, duration_minutes]
            },
            "updated_at": now_ts,
        }},
        # Stage 5: 清掉暫存欄位
        {"$unset": ["_plan_remaining", "_from_plan", "_from_extra"]},
    ]


def build_ai_summary_consumption_pipeline(plan_limit: int, now_ts: int) -> list:
    """建立 AI 摘要消耗的 MongoDB pipeline update（每次固定扣 1 次）

    在 DB 端原子計算：
      plan_remaining = max(0, plan_limit - usage.ai_summaries)
      from_plan = min(plan_remaining, 1)   # 1 或 0
      from_extra = 1 - from_plan

      usage.ai_summaries += from_plan
      usage.total_ai_summaries += 1
      extra_quota.ai_summaries -= from_extra
      reserved_ai_summaries = max(0, reserved_ai_summaries - 1)  # 把預扣轉成實際使用

    與 build_transcription_consumption_pipeline 同樣的設計：方案額度優先，
    不足才動 extra_quota，且 extra_quota 永不為負。

    Args:
        plan_limit: 用戶方案的 AI 摘要上限
        now_ts: updated_at 時間戳

    Returns:
        MongoDB aggregation pipeline（list of stages），給 update_one 用
    """
    return [
        # Stage 1: 算 plan_remaining
        {"$set": {
            "_plan_remaining": {
                "$max": [
                    0,
                    {"$subtract": [
                        plan_limit,
                        {"$ifNull": ["$usage.ai_summaries", 0]},
                    ]},
                ]
            }
        }},
        # Stage 2: 算 from_plan（1 或 0）
        {"$set": {
            "_from_plan": {"$min": ["$_plan_remaining", 1]}
        }},
        # Stage 3: 套用扣款 + 累加統計 + 釋放預扣
        {"$set": {
            "usage.ai_summaries": {
                "$add": [{"$ifNull": ["$usage.ai_summaries", 0]}, "$_from_plan"]
            },
            "usage.total_ai_summaries": {
                "$add": [{"$ifNull": ["$usage.total_ai_summaries", 0]}, 1]
            },
            "extra_quota.ai_summaries": {
                "$subtract": [
                    {"$ifNull": ["$extra_quota.ai_summaries", 0]},
                    {"$subtract": [1, "$_from_plan"]},
                ]
            },
            "reserved_ai_summaries": {
                "$max": [
                    0,
                    {"$subtract": [{"$ifNull": ["$reserved_ai_summaries", 0]}, 1]},
                ]
            },
            "updated_at": now_ts,
        }},
        # Stage 4: 清掉暫存欄位
        {"$unset": ["_plan_remaining", "_from_plan"]},
    ]


async def periodic_subscription_expiry_check(db, interval_seconds: int = 3600) -> None:
    """定期掃描「已排定取消且到期」的訂閱，主動降級為 free。

    解決：用戶排定期末取消但從未登入，DB 中 status 永遠顯示 active 的問題。
    現有 lazy 機制（_reset_monthly_quota_if_needed）只在用戶請求時觸發。

    ⚠️ 只處理 cancel_at_period_end 的 lapse。auto-renew 的 active 訂閱過期末由
    renewal_service 續扣（不在此降級）；past_due 寬限期滿降級也由 renewal_service 負責。

    啟動嘗試搶當前時間窗執行權，搶到才立即跑第一次（不等 interval），避免 restart
    緊接的時段沒被 sweep 覆蓋；搶不到就等下一輪。之後每 interval_seconds 跑一次。

    🔴 P0-2(a)：prod 兩個 uvicorn worker 都跑這個背景任務，用 JobLeaseRepository 對本輪
    時間窗搶執行權，避免同一輪 lapse 掃描被跑兩次。lease 檢查失敗（DB 例外）fail-open，
    照跑本輪並記警告——sweep 冪等，寧可偶發重跑也不要背景任務全停。
    """
    lease_repo = JobLeaseRepository(db)
    while True:
        should_run = True
        try:
            should_run = await lease_repo.claim_window("subscription_expiry", interval_seconds)
        except Exception as e:
            log.warning("subscription.expiry_sweep.lease_check_failed", error=str(e))
        if not should_run:
            await asyncio.sleep(interval_seconds)
            continue
        try:
            now_ts = get_utc_timestamp()
            cursor = db.users.find(
                {
                    "subscription.status": "active",
                    "subscription.cancel_at_period_end": True,
                    "subscription.current_period_end": {"$lt": now_ts},
                },
                {"_id": 1, "subscription": 1}
            )
            expired_count = 0
            async for user in cursor:
                # F5：只計真的降級的（guard 命中）。reactivate 競態 no-op 回 False 不計入，
                # 避免 expired 遙測指標膨脹。
                if await QuotaManager._expire_subscription(db, user):
                    expired_count += 1
            if expired_count:
                log.info("subscription.expiry_sweep.completed", expired=expired_count)
        except Exception as e:
            log.error("subscription.expiry_sweep.failed", error=str(e), exc_info=True)
        await asyncio.sleep(interval_seconds)
