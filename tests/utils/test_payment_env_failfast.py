"""金流體檢 P1-6：prod 環境變數 fallback 防護測試。

涵蓋：
1. is_prod_aws() 判定（DEPLOY_ENV=aws 且 APP_ENV 非 staging）
2. get_parameter(required=True) fail-closed（不 fallback env）
3. Payments91APPService / SmilePayService __init__ 硬擋
4. main.py 啟動用的 validate_payment_env() 三態分級告警

不打真 AWS：SSM 一律用假 client（monkeypatch config_loader._get_ssm）。
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# service __init__ 在 local 模式下走 env 讀憑證，先設好再 import 建物件
# （比照 tests/services/test_invoice_service.py:19-26 的既有慣例，用公開測試值）
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
for _k in ("PAYMENTS91_API_KEY", "PAYMENTS91_SHARED_SECRET", "PAYMENTS91_PUBLISHABLE_KEY", "PAYMENTS91_STORE_CODE"):
    os.environ.setdefault(_k, "test-value")
os.environ.setdefault("SMILEPAY_GRVC", "SEI1004730")
os.environ.setdefault("SMILEPAY_VERIFY_KEY", "7C623AEFC6C2AEB7F11047CD29B50F4E")

from src.utils import config_loader  # noqa: E402
from src.utils.config_loader import get_parameter, is_prod_aws, validate_payment_env  # noqa: E402
from src.utils.payments91_service import Payments91APPService  # noqa: E402
from src.utils.smilepay_service import SmilePayService  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_param_cache():
    """每個測試前後清空 SSM 參數 cache，避免不同 required/情境互相汙染。"""
    config_loader._param_cache.clear()
    yield
    config_loader._param_cache.clear()


@pytest.fixture
def fake_ssm_ok(monkeypatch):
    """成功回傳固定值（依參數名生成）的假 SSM client。"""
    class _FakeSSM:
        def get_parameter(self, Name, WithDecryption=False):
            return {"Parameter": {"Value": f"value-for-{Name}"}}

    monkeypatch.setattr(config_loader, "_get_ssm", lambda: _FakeSSM())


@pytest.fixture
def fake_ssm_fail(monkeypatch):
    """SSM 讀取拋例外的假 client。"""
    class _FakeSSM:
        def get_parameter(self, Name, WithDecryption=False):
            raise RuntimeError("boom: ssm unreachable")

    monkeypatch.setattr(config_loader, "_get_ssm", lambda: _FakeSSM())


@pytest.fixture
def fake_ssm_empty(monkeypatch):
    """SSM 讀取成功但回空值的假 client。"""
    class _FakeSSM:
        def get_parameter(self, Name, WithDecryption=False):
            return {"Parameter": {"Value": ""}}

    monkeypatch.setattr(config_loader, "_get_ssm", lambda: _FakeSSM())


# ── is_prod_aws ──────────────────────────────────────────────────────────

class TestIsProdAws:
    def test_aws_without_app_env_is_prod(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        assert is_prod_aws() is True

    def test_aws_staging_is_not_prod(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("APP_ENV", "staging")
        assert is_prod_aws() is False

    def test_local_is_not_prod(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "local")
        assert is_prod_aws() is False


# ── get_parameter(required=True) ────────────────────────────────────────

class TestGetParameterRequired:
    def test_aws_ssm_exception_raises_and_does_not_fallback_env(self, monkeypatch, fake_ssm_fail):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        # 故意留一個 env fallback 值：required=True 若誤用 fallback 會回這個值，
        # 測試要證明它「沒有」被讀到。
        monkeypatch.setenv("SOME_FALLBACK_LEAK_CHECK", "leaked-should-not-be-used")
        with pytest.raises(RuntimeError):
            get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK_LEAK_CHECK", required=True)
        # raise 前不寫 cache
        assert config_loader._param_cache == {}

    def test_aws_ssm_empty_value_raises(self, monkeypatch, fake_ssm_empty):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        with pytest.raises(RuntimeError):
            get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)

    def test_aws_ssm_success_returns_value(self, monkeypatch, fake_ssm_ok):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        val = get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)
        assert val == "value-for-/transcriber/x"

    def test_local_env_has_value_returns_it(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "local")
        monkeypatch.setenv("SOME_FALLBACK", "local-value")
        val = get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)
        assert val == "local-value"

    def test_local_env_empty_raises(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "local")
        monkeypatch.delenv("SOME_FALLBACK", raising=False)
        with pytest.raises(RuntimeError):
            get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)

    def test_required_false_behavior_unchanged_on_ssm_failure(self, monkeypatch, fake_ssm_fail):
        """既有呼叫端（required 預設 False）行為不受影響：SSM 失敗照樣 fallback env。"""
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("SOME_FALLBACK", "fallback-value")
        val = get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK")
        assert val == "fallback-value"

    def test_required_false_empty_ssm_does_not_raise(self, monkeypatch, fake_ssm_empty):
        """既有行為：SSM 成功但回空值時不 raise、不 fallback env（維持原樣，只有
        required=True 才會把「SSM 成功但空值」升級成 RuntimeError）。"""
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        val = get_parameter("/transcriber/x", fallback_env=None, default="d")
        assert val == ""


# ── Payments91APPService.__init__ ───────────────────────────────────────

class TestPayments91InitFailFast:
    def test_prod_aws_sandbox_raises(self, monkeypatch, fake_ssm_ok):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("PAYMENTS91_ENV", "sandbox")
        with pytest.raises(RuntimeError, match="PAYMENTS91_ENV"):
            Payments91APPService()

    def test_staging_aws_sandbox_constructs_normally(self, monkeypatch, fake_ssm_ok):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv("PAYMENTS91_ENV", "sandbox")
        svc = Payments91APPService()
        assert svc.env == "sandbox"

    def test_local_sandbox_constructs_normally(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "local")
        monkeypatch.setenv("DEPLOY_ENV", "local")
        monkeypatch.setenv("PAYMENTS91_ENV", "sandbox")
        svc = Payments91APPService()
        assert svc.env == "sandbox"


# ── SmilePayService.__init__ ────────────────────────────────────────────

class TestSmilePayInitFailFast:
    def test_prod_aws_test_env_raises(self, monkeypatch, fake_ssm_ok):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("SMILEPAY_ENV", "test")
        with pytest.raises(RuntimeError, match="SMILEPAY_ENV"):
            SmilePayService()

    def test_staging_aws_test_env_constructs_normally(self, monkeypatch, fake_ssm_ok):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv("SMILEPAY_ENV", "test")
        svc = SmilePayService()
        assert svc.env == "test"

    def test_local_test_env_constructs_normally(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "local")
        monkeypatch.setenv("DEPLOY_ENV", "local")
        monkeypatch.setenv("SMILEPAY_ENV", "test")
        svc = SmilePayService()
        assert svc.env == "test"


# ── validate_payment_env（main.py startup 分級告警）──────────────────────

class TestValidatePaymentEnv:
    def test_both_production_no_raise_no_warn(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("PAYMENTS91_ENV", "production")
        monkeypatch.setenv("SMILEPAY_ENV", "production")
        fake_log = MagicMock()
        monkeypatch.setattr(config_loader, "log", fake_log)

        validate_payment_env()  # 不應拋例外

        fake_log.warning.assert_not_called()

    def test_unset_logs_warning_and_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("PAYMENTS91_ENV", raising=False)
        monkeypatch.delenv("SMILEPAY_ENV", raising=False)
        fake_log = MagicMock()
        monkeypatch.setattr(config_loader, "log", fake_log)

        validate_payment_env()  # 未設是預期狀態，不拋

        warned_vars = {call.kwargs.get("var") for call in fake_log.warning.call_args_list}
        assert warned_vars == {"PAYMENTS91_ENV", "SMILEPAY_ENV"}

    def test_explicit_wrong_value_raises(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("PAYMENTS91_ENV", "sandbox")
        monkeypatch.setenv("SMILEPAY_ENV", "production")
        with pytest.raises(RuntimeError, match="PAYMENTS91_ENV"):
            validate_payment_env()

    def test_staging_returns_without_checking(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("APP_ENV", "staging")
        # 顯式設錯也不該被擋——staging 本來就該打 sandbox/test
        monkeypatch.setenv("PAYMENTS91_ENV", "sandbox")
        monkeypatch.setenv("SMILEPAY_ENV", "test")
        fake_log = MagicMock()
        monkeypatch.setattr(config_loader, "log", fake_log)

        validate_payment_env()  # 不拋

        fake_log.warning.assert_not_called()


# ── 第二意見審查 F4/F5/F6 補強 ─────────────────────────────────────────────

class TestValidatePaymentEnvSmilePayBranch:
    def test_smilepay_explicit_wrong_value_raises(self, monkeypatch):
        """F4：原 wrong-value 測試只走到迴圈第一個（PAYMENTS91_ENV）就 raise，
        SMILEPAY_ENV 分支的 raise 從未被執行——這裡讓 91APP 過、SmilePay 錯。"""
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("PAYMENTS91_ENV", "production")
        monkeypatch.setenv("SMILEPAY_ENV", "test")
        with pytest.raises(RuntimeError, match="SMILEPAY_ENV"):
            validate_payment_env()


class TestLazySingletonFailClosed:
    """F5：驗收條件 1 的 singleton 語意——第一次建構失敗不得留下半套實例，
    重試必須重跑 guard；環境修正後才建得起來。"""

    def test_payments91_singleton_not_cached_on_raise(self, monkeypatch, fake_ssm_ok):
        from src.utils import payments91_service as p91
        monkeypatch.setattr(p91, "_payments91_service", None)
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("PAYMENTS91_ENV", "sandbox")
        with pytest.raises(RuntimeError):
            p91.get_payments91_service()
        assert p91._payments91_service is None  # 不留半套實例
        with pytest.raises(RuntimeError):
            p91.get_payments91_service()  # 第二次重跑 guard，照樣 raise
        monkeypatch.setenv("PAYMENTS91_ENV", "production")
        svc = p91.get_payments91_service()  # 修正後可建
        assert svc.env == "production"

    def test_smilepay_singleton_not_cached_on_raise(self, monkeypatch, fake_ssm_ok):
        from src.utils import smilepay_service as sp
        monkeypatch.setattr(sp, "_smilepay_service", None)
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("SMILEPAY_ENV", "test")
        with pytest.raises(RuntimeError):
            sp.get_smilepay_service()
        assert sp._smilepay_service is None
        monkeypatch.setenv("SMILEPAY_ENV", "production")
        svc = sp.get_smilepay_service()
        assert svc.env == "production"


class TestGetParameterCacheSemantics:
    """F6 + F2：required 成功值照 cache；required 與非 required 的 cache 互相隔離。"""

    def test_required_success_value_is_cached(self, monkeypatch, fake_ssm_ok):
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        val = get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)
        assert val == "value-for-/transcriber/x"
        assert config_loader._param_cache.get(
            ("/transcriber/x", "SOME_FALLBACK", "", True)
        ) == "value-for-/transcriber/x"

    def test_required_true_does_not_hit_fallback_polluted_cache(self, monkeypatch, fake_ssm_fail):
        """F2：同名參數先被 required=False 以 env fallback 填了 cache，required=True
        的讀取不得命中它——cache key 含 required，兩種讀法各自成條目。"""
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("SOME_FALLBACK", "public-test-credential")
        assert get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK") == "public-test-credential"
        with pytest.raises(RuntimeError):
            get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)

    def test_error_message_does_not_leak_credential_value(self, monkeypatch, fake_ssm_fail):
        """F6/驗收 5：raise 訊息只帶參數名，不帶（env 裡存在的）憑證值。"""
        monkeypatch.setenv("DEPLOY_ENV", "aws")
        monkeypatch.setenv("SOME_FALLBACK", "super-secret-value")
        with pytest.raises(RuntimeError) as ei:
            get_parameter("/transcriber/x", fallback_env="SOME_FALLBACK", required=True)
        assert "super-secret-value" not in str(ei.value)
        assert "/transcriber/x" in str(ei.value)
