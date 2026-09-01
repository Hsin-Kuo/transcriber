"""subscriptions.pay 單元測試（P1-9 對帳補償 sweep 前置：trade_id 落庫時機）。

沒有既有的 /pay 專屬測試檔（既有 test_subscriptions_callback.py 只測
_process_payment_result 這段共用收斂路徑）——這裡新開一檔，直接呼叫 router
handler（bypass FastAPI Depends，比照 test_subscriptions_callback.py 的風格），
免 TestClient / Mongo。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "a" * 64)
os.environ.setdefault("PAYMENTS91_API_KEY", "k")
os.environ.setdefault("PAYMENTS91_SHARED_SECRET", "s")
os.environ.setdefault("PAYMENTS91_PUBLISHABLE_KEY", "p")
os.environ.setdefault("PAYMENTS91_STORE_CODE", "c")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import subscriptions as subs  # noqa: E402
from src.services.order_settlement import SettleOutcome, SettleResult  # noqa: E402
from src.utils.card_token_cipher import decrypt  # noqa: E402
from src.utils.time_utils import get_utc_timestamp  # noqa: E402


def _pending_order(**over):
    base = {
        "merchant_order_no": "SLSUB1",
        "user_id": "u1",
        "status": "pending",
        "tier": "basic",
        "amount_twd": 299,
    }
    base.update(over)
    return base


def _patch(monkeypatch, *, resp, order=None):
    order_repo = MagicMock()
    order_repo.get_by_order_no = AsyncMock(return_value=order or _pending_order())
    order_repo.update_by_order_no = AsyncMock(return_value=True)
    monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

    svc = MagicMock()
    svc.create_first_payment = AsyncMock(return_value=resp)
    monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)

    settlement = MagicMock()
    settlement.settle = AsyncMock(return_value=SettleResult(SettleOutcome.ACTIVATED, "SLSUB1"))
    monkeypatch.setattr(subs, "build_order_settlement", lambda db: settlement)

    # 非 3DS 分支會經 _process_payment_result → ProcessedWebhookRepository.claim。
    webhook_repo = MagicMock()
    webhook_repo.claim = AsyncMock(return_value=True)
    webhook_repo.release = AsyncMock(return_value=True)
    monkeypatch.setattr(subs, "ProcessedWebhookRepository", lambda db: webhook_repo)

    return order_repo, svc, settlement


class TestPayTradeIdPersistence:
    """P1-9：/pay 的 3DS 分支（回 paymentUrl 早退）身上正是 callback 遺失的高風險
    族群——trade_id 必須在早退『之前』落庫，對帳 sweep 才找得到這筆單去主動回查。
    """

    async def test_3ds_branch_persists_trade_id_before_returning(self, monkeypatch):
        order_repo, svc, _ = _patch(monkeypatch, resp={
            "statusCode": "Success", "paymentUrl": "https://bank.example/3ds",
            "tradeId": "PT123", "cardToken": None,
        })
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        out = await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())

        assert out["status"] == "pending_3ds"
        order_repo.update_by_order_no.assert_awaited_once()
        order_no, updates = order_repo.update_by_order_no.await_args.args
        assert order_no == "SLSUB1"
        assert updates["trade_id"] == "PT123"

    async def test_encrypt_failure_does_not_block_trade_id_persistence(self, monkeypatch):
        """F2（跨 PR 複檢）：card_token 加密失敗（KEK 未 seed / SSM 抖動）絕不能連帶擋掉
        同一批 trade_id 落庫——否則這張已扣款的單對帳 sweep 看不到（要求有 trade_id），
        T+1h 被標 expired，使用者扣款卻無訂閱無告警。encrypt 失敗 → 略過 card_token，
        trade_id 照常寫入。"""
        order_repo, svc, _ = _patch(monkeypatch, resp={
            "statusCode": "Success", "paymentUrl": "https://bank.example/3ds",
            "tradeId": "PT123", "cardToken": "CT1",
        })
        monkeypatch.setattr(subs, "encrypt",
                            lambda v: (_ for _ in ()).throw(RuntimeError("KEK unavailable")))
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        out = await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())
        assert out["status"] == "pending_3ds"
        order_no, updates = order_repo.update_by_order_no.await_args.args
        assert updates["trade_id"] == "PT123"      # trade_id 仍落庫（對帳看得到）
        assert "card_token" not in updates          # 加密失敗 → 略過，不寫明文也不阻斷

    async def test_non_3ds_branch_also_persists_trade_id(self, monkeypatch):
        """迴歸：非 3DS 立即收斂分支本來就會走到 trade_id 賦值，改動後仍要保留。"""
        order_repo, svc, settlement = _patch(monkeypatch, resp={
            "statusCode": "Success", "tradeId": "PT999", "cardToken": "CT1",
        })
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        out = await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())

        assert out["status"] == "success"
        order_no, updates = order_repo.update_by_order_no.await_args.args
        assert updates["trade_id"] == "PT999"
        # P2-10（金流體檢）：card_token 落庫前已加密，不再是明文。
        assert updates["card_token"].startswith("v1:")
        assert decrypt(updates["card_token"]) == "CT1"
        n = settlement.settle.await_args.args[0]
        assert n.trade_id == "PT999"

    async def test_no_trade_id_in_response_does_not_add_the_field(self, monkeypatch):
        # 帶 cardBrand（非 trade_id/cardToken 欄位）確保 order_updates 非空、真的觸發
        # update_by_order_no 呼叫，藉此驗證「沒有 tradeId 就不生 trade_id 鍵」。
        order_repo, svc, _ = _patch(monkeypatch, resp={
            "statusCode": "Success", "paymentUrl": "https://bank.example/3ds",
            "cardBrand": "VISA",
        })
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())
        order_no, updates = order_repo.update_by_order_no.await_args.args
        assert "trade_id" not in updates
        assert updates["card_brand"] == "VISA"


class TestPayExpiresAtGate:
    """P3-I（第二意見審查）：order_cleanup 讓路後，有 trade_id 的 pending 單重付
    窗口變無限——/pay 自己補查 expires_at，擋掉對著舊單重付。
    """

    async def test_expired_pending_order_returns_400(self, monkeypatch):
        order_repo, svc, _ = _patch(monkeypatch, resp={"statusCode": "Success"}, order=_pending_order(
            expires_at=get_utc_timestamp() - 10,
        ))
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        with pytest.raises(HTTPException) as exc_info:
            await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["code"] == "ORDER_EXPIRED"
        svc.create_first_payment.assert_not_awaited()

    async def test_non_expired_pending_order_proceeds(self, monkeypatch):
        order_repo, svc, _ = _patch(monkeypatch, resp={
            "statusCode": "Success", "paymentUrl": "https://bank.example/3ds",
        }, order=_pending_order(expires_at=get_utc_timestamp() + 3600))
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        out = await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())
        assert out["status"] == "pending_3ds"
        svc.create_first_payment.assert_awaited_once()

    async def test_missing_expires_at_does_not_block(self, monkeypatch):
        """既有（改動前建立的）order 若沒有 expires_at 欄位，不該被這個新 gate 誤擋。"""
        order_repo, svc, _ = _patch(monkeypatch, resp={
            "statusCode": "Success", "paymentUrl": "https://bank.example/3ds",
        }, order=_pending_order())  # 無 expires_at
        request = subs.PayRequest(order_no="SLSUB1", txn_token="tok")
        out = await subs.pay(request, current_user={"_id": "u1"}, db=MagicMock())
        assert out["status"] == "pending_3ds"
        svc.create_first_payment.assert_awaited_once()
