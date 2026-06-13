"""config_loader.get_parameter 的 APP_ENV prefix 路由測試。

staging 環境（APP_ENV=staging）必須把 `/transcriber/*` 讀取改寫成
`/transcriber-staging/*`，與 prod 完全隔離；prod（預設）不改寫。
路由集中在 get_parameter 單點，所有 SSM 讀取都經過它。
"""
import pytest

from src.utils import config_loader


@pytest.fixture
def fake_ssm(monkeypatch):
    """攔截 SSM 呼叫：記錄被讀取的參數名，回傳固定值。強制走 aws 分支、清空 cache。"""
    calls = []

    class _FakeSSM:
        def get_parameter(self, Name, WithDecryption=False):
            calls.append(Name)
            return {"Parameter": {"Value": f"value-for-{Name}"}}

    monkeypatch.setattr(config_loader, "DEPLOY_ENV", "aws")
    monkeypatch.setattr(config_loader, "_get_ssm", lambda: _FakeSSM())
    config_loader._param_cache.clear()
    yield calls
    config_loader._param_cache.clear()


def test_staging_rewrites_prefix(fake_ssm, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    val = config_loader.get_parameter("/transcriber/jwt-secret", fallback_env="JWT_SECRET_KEY")
    assert fake_ssm == ["/transcriber-staging/jwt-secret"]
    assert val == "value-for-/transcriber-staging/jwt-secret"


def test_prod_does_not_rewrite(fake_ssm, monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    config_loader.get_parameter("/transcriber/jwt-secret", fallback_env="JWT_SECRET_KEY")
    assert fake_ssm == ["/transcriber/jwt-secret"]


def test_default_env_is_prod(fake_ssm, monkeypatch):
    # 未設 APP_ENV → 視為 prod，不改寫
    monkeypatch.delenv("APP_ENV", raising=False)
    config_loader.get_parameter("/transcriber/mongodb-url", fallback_env="MONGODB_URL")
    assert fake_ssm == ["/transcriber/mongodb-url"]


def test_staging_only_rewrites_transcriber_prefix(fake_ssm, monkeypatch):
    # 非 /transcriber/ 開頭的名稱不被改寫（防誤傷）
    monkeypatch.setenv("APP_ENV", "staging")
    config_loader.get_parameter("/other/thing", fallback_env="X")
    assert fake_ssm == ["/other/thing"]


def test_staging_and_prod_cache_separately(fake_ssm, monkeypatch):
    # 同一邏輯名在兩環境下不該共用 cache（key 用改寫後的 name）
    monkeypatch.setenv("APP_ENV", "staging")
    config_loader.get_parameter("/transcriber/worker-secret", fallback_env="WORKER_SECRET")
    monkeypatch.setenv("APP_ENV", "prod")
    config_loader.get_parameter("/transcriber/worker-secret", fallback_env="WORKER_SECRET")
    assert fake_ssm == [
        "/transcriber-staging/worker-secret",
        "/transcriber/worker-secret",
    ]
