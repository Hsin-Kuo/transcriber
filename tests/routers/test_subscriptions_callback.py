"""subscriptions._process_payment_result 單元測試：claim 去重 + settle + 失敗 release。

這是 /pay 立即成交與 /callback 共用的收斂路徑（91APP webhook 冪等核心）。
用 monkeypatch 換掉 ProcessedWebhookRepository / build_order_settlement，免 FastAPI TestClient / Mongo。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "a" * 64)
os.environ.setdefault("PAYMENTS91_API_KEY", "k")
os.environ.setdefault("PAYMENTS91_SHARED_SECRET", "s")
os.environ.setdefault("PAYMENTS91_PUBLISHABLE_KEY", "p")
os.environ.setdefault("PAYMENTS91_STORE_CODE", "c")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import subscriptions as subs  # noqa: E402
from src.services.order_settlement import SettleResult, SettleOutcome  # noqa: E402


def _patch(monkeypatch, *, claim_ok=True, settle_outcome=SettleOutcome.ACTIVATED, settle_raises=False):
    webhook_repo = MagicMock()
    webhook_repo.claim = AsyncMock(return_value=claim_ok)
    webhook_repo.release = AsyncMock(return_value=True)
    monkeypatch.setattr(subs, "ProcessedWebhookRepository", lambda db: webhook_repo)

    settlement = MagicMock()
    if settle_raises:
        settlement.settle = AsyncMock(side_effect=RuntimeError("boom"))
    else:
        settlement.settle = AsyncMock(return_value=SettleResult(settle_outcome, "SLSUB1"))
    monkeypatch.setattr(subs, "build_order_settlement", lambda db: settlement)
    return webhook_repo, settlement


class TestProcessPaymentResult:
    async def test_claim_success_settles(self, monkeypatch):
        webhook_repo, settlement = _patch(monkeypatch)
        out = await subs._process_payment_result(
            MagicMock(), trade_id="PT1", record_status="Success", order_no="SLSUB1", success=True,
        )
        assert out == "activated"
        webhook_repo.claim.assert_awaited_once()
        # natural_id = "<trade_id>:<record_status>"
        assert webhook_repo.claim.await_args.kwargs["natural_id"] == "PT1:Success"
        assert webhook_repo.claim.await_args.kwargs["provider"] == "91app"
        n = settlement.settle.await_args.args[0]
        assert n.order_no == "SLSUB1" and n.success is True and n.trade_id == "PT1"

    async def test_duplicate_claim_skips_settle(self, monkeypatch):
        webhook_repo, settlement = _patch(monkeypatch, claim_ok=False)
        out = await subs._process_payment_result(
            MagicMock(), trade_id="PT1", record_status="Success", order_no="SLSUB1", success=True,
        )
        assert out == "duplicate"
        settlement.settle.assert_not_awaited()

    async def test_settle_failure_releases_claim_and_raises(self, monkeypatch):
        webhook_repo, settlement = _patch(monkeypatch, settle_raises=True)
        with pytest.raises(RuntimeError):
            await subs._process_payment_result(
                MagicMock(), trade_id="PT1", record_status="Success", order_no="SLSUB1", success=True,
            )
        webhook_repo.release.assert_awaited_once()  # 釋放讓 91APP 重送能重做

    async def test_natural_id_falls_back_to_order_no_when_no_trade_id(self, monkeypatch):
        webhook_repo, _ = _patch(monkeypatch)
        await subs._process_payment_result(
            MagicMock(), trade_id="", record_status="failed", order_no="SLSUB1", success=False,
        )
        assert webhook_repo.claim.await_args.kwargs["natural_id"] == "SLSUB1:failed"
