"""訂閱生命週期端點（/cancel /reactivate /change /cancel-plan-change）的樂觀併發
guard 單元測試（P0-2(b) 金流體檢 F2，第二意見審查補測）。

直接呼叫 router 底下的 async function（不經 FastAPI TestClient/依賴注入），
`current_user`/`db` 用純 dict/MagicMock 直傳，monkeypatch `UserRepository` 驗證
guard 命中/不命中兩種結果：guard 不命中要回 409（訂閱剛被併發改動，前端該重新整理），
guard 命中則正常回傳原本的成功訊息。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "a" * 64)
for k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(k, "x")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException  # noqa: E402

from src.routers import subscriptions as subs  # noqa: E402


def _patch_user_repo(monkeypatch, sub: dict, *, guard_ok: bool):
    user_repo = MagicMock()
    user_repo.get_by_id = AsyncMock(return_value={"subscription": sub})
    user_repo.update_subscription_fields = AsyncMock(return_value=guard_ok)
    user_repo.update_subscription = AsyncMock(return_value=True)
    monkeypatch.setattr(subs, "UserRepository", lambda db: user_repo)
    return user_repo


class TestCancelSubscriptionGuard:
    async def test_guard_miss_returns_409(self, monkeypatch):
        sub = {"status": "active", "cancel_at_period_end": False, "next_charge_at": 1000}
        user_repo = _patch_user_repo(monkeypatch, sub, guard_ok=False)

        with pytest.raises(HTTPException) as ei:
            await subs.cancel_subscription(current_user={"_id": "u1"}, db=MagicMock())

        assert ei.value.status_code == 409
        call = user_repo.update_subscription_fields.await_args
        assert call.args[0] == "u1"
        assert call.args[1]["cancel_at_period_end"] is True
        assert call.kwargs["guard"] == {"subscription.next_charge_at": 1000}
        user_repo.update_subscription.assert_not_awaited()  # 不再整包覆寫

    async def test_guard_hit_succeeds(self, monkeypatch):
        sub = {"status": "active", "cancel_at_period_end": False, "next_charge_at": 1000}
        _patch_user_repo(monkeypatch, sub, guard_ok=True)

        result = await subs.cancel_subscription(current_user={"_id": "u1"}, db=MagicMock())
        assert "message" in result


class TestReactivateSubscriptionGuard:
    async def test_guard_miss_returns_409(self, monkeypatch):
        sub = {"status": "active", "cancel_at_period_end": True, "next_charge_at": 2000}
        user_repo = _patch_user_repo(monkeypatch, sub, guard_ok=False)

        with pytest.raises(HTTPException) as ei:
            await subs.reactivate_subscription(current_user={"_id": "u1"}, db=MagicMock())

        assert ei.value.status_code == 409
        call = user_repo.update_subscription_fields.await_args
        assert call.args[1]["cancel_at_period_end"] is False
        assert call.kwargs["guard"] == {"subscription.next_charge_at": 2000}

    async def test_guard_hit_succeeds(self, monkeypatch):
        sub = {"status": "active", "cancel_at_period_end": True, "next_charge_at": 2000}
        _patch_user_repo(monkeypatch, sub, guard_ok=True)

        result = await subs.reactivate_subscription(current_user={"_id": "u1"}, db=MagicMock())
        assert "message" in result


class TestChangePlanDowngradeGuard:
    async def test_guard_miss_returns_409(self, monkeypatch):
        # pro→basic 是降級（is_upgrade 為 False），走 pending_plan_change 分支
        sub = {"status": "active", "tier": "pro", "billing_cycle": "monthly", "next_charge_at": 3000}
        user_repo = _patch_user_repo(monkeypatch, sub, guard_ok=False)

        svc = MagicMock()
        svc.get_subscription_price = MagicMock(return_value=299)
        monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)

        request = subs.ChangePlanRequest(tier="basic", billing="monthly")
        with pytest.raises(HTTPException) as ei:
            await subs.change_plan(request, current_user={"_id": "u1"}, db=MagicMock())

        assert ei.value.status_code == 409
        call = user_repo.update_subscription_fields.await_args
        assert call.args[1]["pending_plan_change"]["tier"] == "basic"
        assert call.kwargs["guard"] == {"subscription.next_charge_at": 3000}

    async def test_guard_hit_succeeds(self, monkeypatch):
        sub = {"status": "active", "tier": "pro", "billing_cycle": "monthly", "next_charge_at": 3000}
        _patch_user_repo(monkeypatch, sub, guard_ok=True)

        svc = MagicMock()
        svc.get_subscription_price = MagicMock(return_value=299)
        monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)

        request = subs.ChangePlanRequest(tier="basic", billing="monthly")
        result = await subs.change_plan(request, current_user={"_id": "u1"}, db=MagicMock())
        assert result["action"] == "downgrade"


class TestCancelPlanChangeGuard:
    async def test_guard_miss_returns_409(self, monkeypatch):
        sub = {"pending_plan_change": {"tier": "basic"}, "next_charge_at": 4000}
        user_repo = _patch_user_repo(monkeypatch, sub, guard_ok=False)

        with pytest.raises(HTTPException) as ei:
            await subs.cancel_plan_change(current_user={"_id": "u1"}, db=MagicMock())

        assert ei.value.status_code == 409
        call = user_repo.update_subscription_fields.await_args
        assert call.args[1]["pending_plan_change"] is None
        assert call.kwargs["guard"] == {"subscription.next_charge_at": 4000}

    async def test_guard_hit_succeeds(self, monkeypatch):
        sub = {"pending_plan_change": {"tier": "basic"}, "next_charge_at": 4000}
        _patch_user_repo(monkeypatch, sub, guard_ok=True)

        result = await subs.cancel_plan_change(current_user={"_id": "u1"}, db=MagicMock())
        assert "message" in result
