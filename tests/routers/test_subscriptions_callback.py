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


def _patch(monkeypatch, *, claim_ok=True, settle_outcome=SettleOutcome.ACTIVATED, settle_raises=False, order=None):
    # _process_payment_result 會 fetch order 推導 is_first_payment（type=renewal → 續扣）
    order_repo = MagicMock()
    order_repo.get_by_order_no = AsyncMock(return_value=order or {"type": "subscription"})
    monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

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
        # natural_id = trade_id（不併入 record_status，P0-1：見 _process_payment_result docstring）
        assert webhook_repo.claim.await_args.kwargs["natural_id"] == "PT1"
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
        # F10：失敗通知額外帶 ":fail" 後綴（見 _process_payment_result docstring）
        webhook_repo, _ = _patch(monkeypatch)
        await subs._process_payment_result(
            MagicMock(), trade_id="", record_status="failed", order_no="SLSUB1", success=False,
        )
        assert webhook_repo.claim.await_args.kwargs["natural_id"] == "SLSUB1:fail"

    async def test_failure_key_is_namespaced_so_later_success_is_not_deduped(self, monkeypatch):
        """F10：同一筆 trade 先收到失敗通知（佔走 ":fail" 鍵），之後的成功 callback 用
        不帶後綴的鍵，兩者互不 dedup——避免『扣款其實成功但因鍵衝突被判 duplicate、
        訂閱從未啟用』。
        """
        webhook_repo, settlement = _patch(monkeypatch, claim_ok=True)
        await subs._process_payment_result(
            MagicMock(), trade_id="PT9", record_status="RefuseTrade", order_no="SLSUB1", success=False,
        )
        fail_key = webhook_repo.claim.await_args.kwargs["natural_id"]

        webhook_repo2, settlement2 = _patch(monkeypatch, claim_ok=True)
        out = await subs._process_payment_result(
            MagicMock(), trade_id="PT9", record_status="Success", order_no="SLSUB1", success=True,
        )
        success_key = webhook_repo2.claim.await_args.kwargs["natural_id"]

        assert fail_key == "PT9:fail"
        assert success_key == "PT9"
        assert fail_key != success_key
        assert out == "activated"
        settlement2.settle.assert_awaited_once()

    async def test_same_trade_two_callbacks_dedup_on_same_key(self, monkeypatch):
        """同一筆 trade 的兩封 callback（91APP recordStatus 4→5 演進）必須落在同一個
        claim 鍵上，第二封才會被 claim 擋成 duplicate（P0-1 的直接驗證：natural_id
        不再併入 record_status，同 trade_id 不論 record_status 是什麼都收斂成同一鍵）。
        """
        webhook_repo, settlement = _patch(monkeypatch)
        await subs._process_payment_result(
            MagicMock(), trade_id="PT1", record_status="4", order_no="SLSUB1", success=True,
        )
        first_key = webhook_repo.claim.await_args.kwargs["natural_id"]

        webhook_repo, settlement = _patch(monkeypatch, claim_ok=False)
        out = await subs._process_payment_result(
            MagicMock(), trade_id="PT1", record_status="5", order_no="SLSUB1", success=True,
        )
        second_key = webhook_repo.claim.await_args.kwargs["natural_id"]

        assert first_key == second_key == "PT1"
        assert out == "duplicate"
        settlement.settle.assert_not_awaited()

    async def test_first_payment_derived_from_order_type(self, monkeypatch):
        # type=subscription → 首期；type=renewal（換卡挽回）→ 續扣分支
        _, settlement = _patch(monkeypatch, order={"type": "subscription"})
        await subs._process_payment_result(MagicMock(), trade_id="T", record_status="Success", order_no="o", success=True)
        assert settlement.settle.await_args.args[0].is_first_payment is True

        _, settlement2 = _patch(monkeypatch, order={"type": "renewal"})
        await subs._process_payment_result(MagicMock(), trade_id="T2", record_status="Success", order_no="o2", success=True)
        assert settlement2.settle.await_args.args[0].is_first_payment is False


class _FakeRequest:
    """最小 Request 替身：/callback 只用到 body()（JSON）。"""
    def __init__(self, payload: dict):
        import json
        self._raw = json.dumps(payload).encode()

    async def body(self):
        return self._raw

    async def form(self):  # pragma: no cover - JSON 路徑不會走到
        return {}


def _patch_callback(monkeypatch, *, trade: dict, order=None):
    """換掉 query_trade / _process_payment_result / OrderRepository。

    回傳 (captured, order_repo)：captured 是被捕捉的 settle 參數；order_repo 供斷言
    update_by_order_no（F1 補救寫回 card_token）等呼叫細節。
    """
    svc = MagicMock()
    svc.query_trade = AsyncMock(return_value=trade)
    monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)

    order_repo = MagicMock()
    # 預設帶 card_token：多數測試聚焦 recordStatus 判讀而非綁卡 gate（P1-8），
    # 沒指定 order 時視為已在 /pay 當下捕捉到可續扣的卡，避免被 gate 誤擋。
    order_repo.get_by_order_no = AsyncMock(return_value=order or {"type": "subscription", "card_token": "CT1"})
    order_repo.update_by_order_no = AsyncMock(return_value=True)
    monkeypatch.setattr(subs, "OrderRepository", lambda db: order_repo)

    captured = {}

    async def fake_process(db, *, trade_id, record_status, order_no, success):
        captured.update(trade_id=trade_id, record_status=record_status, order_no=order_no, success=success)
        return "activated" if success else "failed"

    monkeypatch.setattr(subs, "_process_payment_result", fake_process)
    return captured, order_repo


class TestCallbackSuccessDerivation:
    """🔴 /callback 以回查的 recordStatus（付款結果）判定成敗，而非查詢層的 statusCode。"""

    async def test_record_status_paid_settles_success(self, monkeypatch):
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 4, "statusCode": "Success",
        })
        out = await subs.payment_callback(_FakeRequest({"tradeId": "PT1", "recordStatus": 4}), db=MagicMock())
        assert out == {"status": "ok"}
        assert cap["success"] is True
        assert cap["record_status"] == "4"  # 用整數 recordStatus 當冪等鍵，非 statusCode

    async def test_record_status_failed_settles_failure(self, monkeypatch):
        # 關鍵回歸：statusCode=Success（查詢成功）但 recordStatus=2（付款失敗）→ 必須判失敗
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 2, "statusCode": "Success",
        })
        await subs.payment_callback(_FakeRequest({"tradeId": "PT1", "recordStatus": 2}), db=MagicMock())
        assert cap["success"] is False

    async def test_pending_does_not_settle(self, monkeypatch):
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 8, "statusCode": "Success",
        })
        out = await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert out == {"status": "pending"}
        assert cap == {}  # 未定案 → 不進 settle

    async def test_binding_failed_via_query_response_blocks_activation(self, monkeypatch):
        # (a) 付款成功（recordStatus=4）但回查回應（可信通道）帶 bindingStatus=Failed → 判失敗。
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLUPG1", "recordStatus": 4, "bindingStatus": "Failed",
        }, order={"type": "upgrade_subscription", "card_token": "CT1"})
        await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert cap["success"] is False

    async def test_missing_binding_field_and_no_card_token_fail_open(self, monkeypatch):
        # (b) 回查回應無 bindingStatus 欄位（fail-open，不擋）；order 也沒有 card_token
        # （cardToken 可能在 3D 完成之後才產生，/pay 同步 response 拿不到不代表沒綁卡成功）→
        # 仍判成功，且缺 token 的告警/Sentry 路徑不能讓 callback 炸掉。
        cap, order_repo = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 4,
        }, order={"type": "subscription"})  # 無 card_token、無 bindingStatus
        out = await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert out == {"status": "ok"}
        assert cap["success"] is True
        order_repo.update_by_order_no.assert_not_awaited()  # 回查也沒給 cardToken，補不了

    async def test_forged_payload_binding_status_ignored_when_query_lacks_field(self, monkeypatch):
        # (c) 偽造 payload 帶 bindingStatus=Failed，但回查回應沒有這個欄位 → 不影響判定
        # （payload 未認證，僅記 log；判定只看回查回應）。
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 4,
        }, order={"type": "subscription", "card_token": "CT1"})
        await subs.payment_callback(
            _FakeRequest({"tradeId": "PT1", "bindingStatus": "Failed"}), db=MagicMock())
        assert cap["success"] is True

    async def test_query_response_card_token_gets_persisted(self, monkeypatch):
        # (d) order 缺 card_token，但回查回應（可信）帶出 cardToken → 補救寫回 order。
        cap, order_repo = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 4, "cardToken": "CT-RECOVERED",
        }, order={"type": "subscription"})  # 無 card_token
        await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert cap["success"] is True
        order_repo.update_by_order_no.assert_awaited_once_with("SLSUB1", {"card_token": "CT-RECOVERED"})

    async def test_extra_quota_ignores_binding(self, monkeypatch):
        # 加購為一次性，不綁卡；即使回查回應帶出非成功 bindingStatus（形狀未實測，防禦性假設）
        # 也不得誤殺——gate 僅限綁卡型訂單（subscription/upgrade_subscription）。
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLEXT1", "recordStatus": 4, "bindingStatus": "NotBinding",
        }, order={"type": "extra_quota"})
        await subs.payment_callback(
            _FakeRequest({"tradeId": "PT1", "bindingStatus": "Failed"}), db=MagicMock())
        assert cap["success"] is True

    async def test_renewal_ignores_binding_gate(self, monkeypatch):
        # 排程續扣（MIT）不綁卡；回查回應帶非成功 bindingStatus 不得把成功的續扣判失敗
        # （否則錢已扣卻被推進 dunning）。
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "REN1", "recordStatus": 4, "bindingStatus": "NotBinding",
        }, order={"type": "renewal", "card_token": "CT1"})
        await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert cap["success"] is True

    async def test_recovery_renewal_card_token_gets_persisted(self, monkeypatch):
        # /update-card 換卡挽回單（type=renewal）建單時 card_token 為空；回查回應帶出新卡
        # cardToken 必須補救寫回，否則 settle 會沿用訂閱上的舊死卡。
        cap, order_repo = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "REN2", "recordStatus": 4, "cardToken": "CT-NEWCARD",
        }, order={"type": "renewal"})  # 無 card_token
        await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert cap["success"] is True
        order_repo.update_by_order_no.assert_awaited_once_with("REN2", {"card_token": "CT-NEWCARD"})

    async def test_no_order_no_ignored(self, monkeypatch):
        cap, _ = _patch_callback(monkeypatch, trade={"recordStatus": 4})
        out = await subs.payment_callback(_FakeRequest({"tradeId": "PT1"}), db=MagicMock())
        assert out == {"status": "ignored"}
        assert cap == {}


class TestTradeIdValidation:
    """🔴 P1-8：tradeId 來自未認證 payload，直接嵌入回查 path 前需格式驗證，否則可注入。"""

    @pytest.mark.parametrize("bad_trade_id", [
        "X?merchantOrderId=victim",
        "../../etc",
        "A" * 65,        # 超過 64 字
        "PT01 26 07",    # 帶空白字元
        "PT<script>",
    ])
    async def test_malformed_trade_id_ignored_without_querying(self, monkeypatch, bad_trade_id):
        svc = MagicMock()
        svc.query_trade = AsyncMock(return_value={"merchantOrderId": "SLSUB1", "recordStatus": 4})
        monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)

        out = await subs.payment_callback(_FakeRequest({"tradeId": bad_trade_id}), db=MagicMock())
        assert out == {"status": "ignored"}
        svc.query_trade.assert_not_awaited()

    @pytest.mark.parametrize("non_string_trade_id", [12345, True, ["PT1"], {"x": "PT1"}])
    async def test_non_string_trade_id_ignored_without_500(self, monkeypatch, non_string_trade_id):
        # F2 回歸：非字串 tradeId（int/bool/list/dict）過了 `if not trade_id` 後直接丟進
        # TRADE_ID_RE.fullmatch 會 TypeError → 500；isinstance 守門後應正常回 ignored。
        svc = MagicMock()
        svc.query_trade = AsyncMock(return_value={"merchantOrderId": "SLSUB1", "recordStatus": 4})
        monkeypatch.setattr(subs, "get_payments91_service", lambda: svc)

        out = await subs.payment_callback(_FakeRequest({"tradeId": non_string_trade_id}), db=MagicMock())
        assert out == {"status": "ignored"}
        svc.query_trade.assert_not_awaited()

    async def test_legit_trade_id_proceeds_normally(self, monkeypatch):
        cap, _ = _patch_callback(monkeypatch, trade={
            "merchantOrderId": "SLSUB1", "recordStatus": 4,
        }, order={"type": "subscription", "card_token": "CT1"})
        out = await subs.payment_callback(
            _FakeRequest({"tradeId": "PT0260724700004T"}), db=MagicMock())
        assert out == {"status": "ok"}
        assert cap["success"] is True
