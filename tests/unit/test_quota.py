"""T5-b QuotaManager 單元測試。

純單元——不碰 DB。覆蓋 tier 預設查找、轉錄/並發配額檢查、AI 摘要方案上限、
月配額重置判斷，以及兩個純函式 consumption pipeline builder。

需 DB 的方法（reserve/consume/release_ai_summary、sweep、_expire_subscription）
不在此檔——那些走 motor，留給整合測試。
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.auth.quota import (  # noqa: E402
    QuotaManager,
    _get_tier_default,
    build_ai_summary_consumption_pipeline,
    build_transcription_consumption_pipeline,
)
from src.models.quota import has_feature, public_tier_plans  # noqa: E402


class TestHasFeature:
    """feature gating 的唯一真實來源——batch_operations 等 flag。"""

    def test_free_lacks_batch_operations(self):
        assert has_feature({"quota": {"tier": "free", "features": {"batch_operations": False}}}, "batch_operations") is False

    def test_free_has_speaker_diarization(self):
        # free 方案提供說話者辨識（與方案頁一致），不做 gating
        assert has_feature({"quota": {"tier": "free"}}, "speaker_diarization") is True

    @pytest.mark.parametrize("tier", ["pro", "enterprise"])
    def test_priority_processing_on_for_pro_and_enterprise(self, tier):
        # 優先佇列路由的真實來源（intake 用 has_feature 決定 is_priority）
        assert has_feature({"quota": {"tier": tier}}, "priority_processing") is True

    @pytest.mark.parametrize("tier", ["free", "basic"])
    def test_priority_processing_off_for_free_and_basic(self, tier):
        assert has_feature({"quota": {"tier": tier}}, "priority_processing") is False

    def test_priority_processing_honors_per_user_override(self):
        # per-user quota.features 覆寫優先於 tier 預設（這正是改走 has_feature 的理由）
        assert has_feature(
            {"quota": {"tier": "free", "features": {"priority_processing": True}}},
            "priority_processing",
        ) is True

    def test_priority_processing_fails_safe_on_bad_tier(self):
        # 壞/缺 tier → 退回 free 預設 False，不誤升級到優先佇列
        assert has_feature({"quota": {"tier": "bogus"}}, "priority_processing") is False
        assert has_feature({}, "priority_processing") is False


class TestPublicTierPlans:
    """方案頁資料的唯一真實來源——前端 PlanPanel 改抓此 API，不再自行 hardcode。"""

    def test_returns_free_basic_pro_only(self):
        # enterprise 走業務洽談，不在自助方案頁
        assert [p["key"] for p in public_tier_plans()] == ["free", "basic", "pro"]

    def test_shape_matches_frontend_fields(self):
        free = next(p for p in public_tier_plans() if p["key"] == "free")
        assert set(free) == {"key", "duration", "concurrent", "aiSummaries", "audioRetention", "keepAudio", "features"}
        assert free["duration"] == 180
        assert free["features"]["batch_operations"] is False
        assert free["features"]["speaker_diarization"] is True

    def test_no_price_leaked(self):
        # 價格綁金流設定，不從此 API 下發
        assert all("price" not in p and "name" not in p for p in public_tier_plans())

    def test_basic_has_batch_operations(self):
        assert has_feature({"quota": {"tier": "basic", "features": {"batch_operations": True}}}, "batch_operations") is True

    def test_legacy_doc_missing_features_falls_back_to_tier(self):
        # 舊 user 文件缺 features → 退回該 tier 在 QUOTA_TIERS 的預設，不可誤判為有權限
        assert has_feature({"quota": {"tier": "free"}}, "batch_operations") is False
        assert has_feature({"quota": {"tier": "basic"}}, "batch_operations") is True

    def test_missing_quota_defaults_to_free(self):
        assert has_feature({}, "batch_operations") is False

    def test_unknown_feature_is_false(self):
        assert has_feature({"quota": {"tier": "pro"}}, "nonexistent_feature") is False


class TestGetTierDefault:
    def test_known_tier_returns_field(self):
        assert _get_tier_default({"quota": {"tier": "pro"}}, "max_duration_minutes", 0) == 3000

    def test_unknown_tier_falls_back_to_free_default(self):
        # 未知 tier → 退回 FREE 的權威值（180），不再採用傳入的硬編 fallback，
        # 確保所有 fallback 都對齊 QUOTA_TIERS 唯一真實來源。
        assert _get_tier_default({"quota": {"tier": "bogus"}}, "max_duration_minutes", 42) == 180

    def test_missing_quota_defaults_to_free_tier(self):
        # 無 quota → tier 視為 free → free 的 max_concurrent_tasks = 1
        assert _get_tier_default({}, "max_concurrent_tasks", 0) == 1


class TestCheckTranscriptionQuota:
    async def test_within_quota_passes(self):
        user = {"quota": {"tier": "free", "max_duration_minutes": 60},
                "usage": {"duration_minutes": 0.0}, "extra_quota": {}}
        assert await QuotaManager.check_transcription_quota(user, 600, db=None) is True

    async def test_over_quota_raises_429(self):
        user = {"quota": {"tier": "free", "max_duration_minutes": 5},
                "usage": {"duration_minutes": 0.0}, "extra_quota": {}}
        with pytest.raises(HTTPException) as exc:
            await QuotaManager.check_transcription_quota(user, 600, db=None)  # 10 分鐘 > 5
        assert exc.value.status_code == 429

    async def test_extra_quota_covers_overflow(self):
        # 方案剩 2 分鐘、extra 有 10 分鐘 → 8 分鐘音檔仍 OK
        user = {"quota": {"tier": "free", "max_duration_minutes": 2},
                "usage": {"duration_minutes": 0.0},
                "extra_quota": {"duration_minutes": 10}}
        assert await QuotaManager.check_transcription_quota(user, 480, db=None) is True


class TestCheckConcurrentTasks:
    async def test_under_limit_passes(self):
        user = {"quota": {"tier": "basic", "max_concurrent_tasks": 2}}
        assert await QuotaManager.check_concurrent_tasks(user, 1) is None

    async def test_at_limit_raises_429(self):
        user = {"quota": {"tier": "basic", "max_concurrent_tasks": 2}}
        with pytest.raises(HTTPException) as exc:
            await QuotaManager.check_concurrent_tasks(user, 2)
        assert exc.value.status_code == 429


class TestAiSummaryPlanLimit:
    def test_explicit_quota_wins(self):
        assert QuotaManager._ai_summary_plan_limit({"quota": {"tier": "basic", "max_ai_summaries": 50}}) == 50

    def test_falls_back_to_tier_default(self):
        assert QuotaManager._ai_summary_plan_limit({"quota": {"tier": "pro"}}) == 100


class TestMonthlyReset:
    async def test_no_last_reset_is_noop(self):
        usage = {"duration_minutes": 5}
        result = await QuotaManager._reset_monthly_quota_if_needed({}, usage, db=None)
        assert result is usage  # 沒 last_reset → 原樣返回

    async def test_free_user_previous_month_resets(self):
        usage = {
            "duration_minutes": 50, "ai_summaries": 2,
            "last_reset": datetime.utcnow() - timedelta(days=40),
            "total_duration_minutes": 999,
        }
        user = {"_id": "u1", "subscription": {}, "usage": usage}
        result = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=None)
        assert result["duration_minutes"] == 0
        assert result["ai_summaries"] == 0
        assert result["total_duration_minutes"] == 999  # 累計值保留

    async def test_free_user_same_month_no_reset(self):
        usage = {"duration_minutes": 50, "last_reset": datetime.utcnow()}
        user = {"_id": "u1", "subscription": {}, "usage": usage}
        result = await QuotaManager._reset_monthly_quota_if_needed(user, usage, db=None)
        assert result is usage  # 同月 → 不重置

    async def test_reset_reapplies_latest_tier_quota(self):
        # 換月時依 tier 重新套用最新方案：stale 快照會被刷新成 QUOTA_TIERS 現值
        from src.models.quota import QUOTA_TIERS, QuotaTier
        user = {
            "_id": "u1", "subscription": {},
            "quota": {"tier": "free", "max_duration_minutes": 9999},  # 舊快照
            "usage": {"duration_minutes": 50, "last_reset": datetime.utcnow() - timedelta(days=40)},
        }
        await QuotaManager._reset_monthly_quota_if_needed(user, user["usage"], db=None)
        assert user["quota"]["max_duration_minutes"] == QUOTA_TIERS[QuotaTier.FREE]["max_duration_minutes"]
        assert user["quota"]["tier"] == "free"
        assert user["quota"]["features"]["speaker_diarization"] is True

    async def test_reset_keeps_unknown_tier_quota_untouched(self):
        # 無法辨識的 tier → 不覆寫 quota，避免破壞資料
        user = {
            "_id": "u1", "subscription": {},
            "quota": {"tier": "bogus", "max_duration_minutes": 9999},
            "usage": {"duration_minutes": 50, "last_reset": datetime.utcnow() - timedelta(days=40)},
        }
        await QuotaManager._reset_monthly_quota_if_needed(user, user["usage"], db=None)
        assert user["quota"]["max_duration_minutes"] == 9999

    async def test_expired_paid_user_does_not_revert_to_paid_quota(self):
        # 回歸：訂閱到期降為 free 後，月配額重套不可讀到 stale 付費 tier 而把 free 覆寫回付費。
        # 到期降級只在 db 可寫時觸發，故用 fake db 走真實路徑（_id 須為合法 ObjectId）。
        from src.models.quota import QUOTA_TIERS, QuotaTier

        class _FakeUsers:
            def __init__(self): self.sets = []
            async def update_one(self, flt, update): self.sets.append(update.get("$set", {}))

        class _FakeDB:
            def __init__(self): self.users = _FakeUsers()

        db = _FakeDB()
        user = {
            "_id": "507f1f77bcf86cd799439011",
            "subscription": {
                "status": "active",
                "current_period_end": datetime.utcnow() - timedelta(days=2),  # 已到期
            },
            "quota": {"tier": "basic", "max_duration_minutes": 600},
            "usage": {"duration_minutes": 100, "last_reset": datetime.utcnow() - timedelta(days=40)},
        }
        await QuotaManager._reset_monthly_quota_if_needed(user, user["usage"], db=db)
        assert user["quota"]["tier"] == "free"
        assert user["quota"]["max_duration_minutes"] == QUOTA_TIERS[QuotaTier.FREE]["max_duration_minutes"]
        # 寫回 DB 的 quota 也必須是 free，而非 basic
        quota_writes = [s["quota"]["tier"] for s in db.users.sets if "quota" in s]
        assert quota_writes and all(t == "free" for t in quota_writes)


class TestMonthlyRefillHelpers:
    """週月運算純函數——年繳週期內每月 refill 的判斷基礎。"""

    def test_months_elapsed_anniversary(self):
        from src.auth.quota import _months_elapsed
        assert _months_elapsed(datetime(2026, 1, 15), datetime(2026, 1, 20)) == 0
        assert _months_elapsed(datetime(2026, 1, 15), datetime(2026, 2, 14)) == 0  # 未滿週月
        assert _months_elapsed(datetime(2026, 1, 15), datetime(2026, 2, 15)) == 1
        assert _months_elapsed(datetime(2026, 1, 15), datetime(2027, 3, 15)) == 14

    def test_months_elapsed_month_end_overflow(self):
        from src.auth.quota import _months_elapsed
        # 1/31 起算、2 月僅 28 天 → 2/28 視為滿一個週月
        assert _months_elapsed(datetime(2026, 1, 31), datetime(2026, 2, 28)) == 1

    def test_due_monthly_refill(self):
        from src.auth.quota import _due_monthly_refill
        ps = datetime(2026, 1, 15)
        assert _due_monthly_refill(ps, datetime(2026, 1, 20), datetime(2026, 2, 16)) is True   # 跨入第 1 週月
        assert _due_monthly_refill(ps, datetime(2026, 2, 16), datetime(2026, 2, 28)) is False  # 同一週月格內


class TestYearlyIntraPeriodRefill:
    """D1+D2+D4：年繳訂閱在年度週期內每月 refill，但不重套方案（凍結繳費當下額度）。"""

    def _yearly_user(self, last_reset_dt, quota_minutes=9999):
        # period_start = 2026-01-10，period_end 一年後（未到期）
        ps = datetime(2026, 1, 10)
        return {
            "_id": "u1",
            "subscription": {
                "status": "active", "billing_cycle": "yearly",
                "current_period_start": ps.timestamp(),
                "current_period_end": datetime(2027, 1, 10).timestamp(),
            },
            "quota": {"tier": "pro", "max_duration_minutes": quota_minutes},
            "usage": {"duration_minutes": 500, "last_reset": last_reset_dt},
        }

    async def test_yearly_crosses_month_refills_without_reapply(self):
        # last_reset 在第 0 週月（1/20），now 進到第 2 週月（3/15）→ 應 refill
        user = self._yearly_user(datetime(2026, 1, 20), quota_minutes=9999)
        now = datetime(2026, 3, 15)
        result = await QuotaManager._reset_monthly_quota_if_needed(user, user["usage"], db=None, now=now)
        assert result["duration_minutes"] == 0                      # 有 refill（歸零用量）
        assert user["quota"]["max_duration_minutes"] == 9999        # 年繳週期內：不重套，凍結繳費當下額度
        assert user["quota"]["tier"] == "pro"

    async def test_yearly_same_month_no_reset(self):
        # last_reset 已在第 1 週月（2/20），now 仍在第 1 週月（2/28）→ 不重置
        user = self._yearly_user(datetime(2026, 2, 20))
        now = datetime(2026, 2, 28)
        result = await QuotaManager._reset_monthly_quota_if_needed(user, user["usage"], db=None, now=now)
        assert result is user["usage"]

    async def test_monthly_active_reapplies_latest(self):
        # 月繳訂閱若走到 lazy refill（跨週期）→ 重套最新方案
        from src.models.quota import QUOTA_TIERS, QuotaTier
        ps = datetime(2026, 1, 10)
        user = {
            "_id": "u1",
            "subscription": {
                "status": "active", "billing_cycle": "monthly",
                "current_period_start": ps.timestamp(),
                "current_period_end": datetime(2026, 2, 9).timestamp(),
            },
            "quota": {"tier": "basic", "max_duration_minutes": 9999},  # stale
            "usage": {"duration_minutes": 300, "last_reset": datetime(2026, 1, 5)},
        }
        # now 跨過 period_start（1/10 > 1/5 last_reset 即觸發），重套 basic 最新值
        result = await QuotaManager._reset_monthly_quota_if_needed(user, user["usage"], db=None, now=datetime(2026, 2, 12))
        assert result["duration_minutes"] == 0
        assert user["quota"]["max_duration_minutes"] == QUOTA_TIERS[QuotaTier.BASIC]["max_duration_minutes"]


class TestConsumptionPipelines:
    def test_transcription_pipeline_structure(self):
        pipeline = build_transcription_consumption_pipeline(10.0, 12345)
        assert isinstance(pipeline, list) and len(pipeline) == 5
        # 末段清掉暫存欄位
        assert pipeline[-1] == {"$unset": ["_plan_remaining", "_from_plan", "_from_extra"]}
        # 套用扣款的 stage 帶 updated_at
        assert pipeline[3]["$set"]["updated_at"] == 12345

    def test_ai_summary_pipeline_structure(self):
        pipeline = build_ai_summary_consumption_pipeline(30, 999)
        assert isinstance(pipeline, list) and len(pipeline) == 4
        assert pipeline[-1] == {"$unset": ["_plan_remaining", "_from_plan"]}
        apply_stage = pipeline[2]["$set"]
        assert apply_stage["updated_at"] == 999
        assert "reserved_ai_summaries" in apply_stage  # 消耗時順帶釋放預扣
