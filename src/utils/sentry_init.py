"""Sentry 初始化（FastAPI server 與 SQS worker 共用）。

未設定 SENTRY_DSN 時 no-op，本地開發不會送資料。
"""
import logging
import os

logger = logging.getLogger(__name__)

# before_send 用 substring 比對遞迴遮蔽欄位
# 用 substring 是因為實際 key 常帶後綴（如 GOOGLE_API_KEY_1、Set-Cookie）
_SENSITIVE_SUBSTRINGS = (
    "password", "passwd",
    "secret",
    "token",
    "api_key", "apikey",
    "hash_key", "hash_iv",
    "authorization", "cookie",
    "hf_token",
)


def _is_sensitive(key) -> bool:
    if not isinstance(key, str):
        return False
    k = key.lower()
    return any(s in k for s in _SENSITIVE_SUBSTRINGS)


def _scrub(value):
    if isinstance(value, dict):
        return {
            k: ("[FILTERED]" if _is_sensitive(k) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _before_send(event, hint):
    for key in ("request", "extra", "contexts"):
        if key in event:
            event[key] = _scrub(event[key])
    return event


def init_sentry(component: str = "server") -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning("SENTRY_DSN 已設定但未安裝 sentry-sdk，略過初始化")
        return

    deploy_env = os.getenv("DEPLOY_ENV", "local")
    explicit_env = os.getenv("SENTRY_ENVIRONMENT", "").strip()
    environment = explicit_env or f"{deploy_env}-{component}"

    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    profiles_sample_rate = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.0"))
    release = os.getenv("SENTRY_RELEASE") or None

    integrations = []
    if component == "server":
        integrations = [
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ]

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=integrations,
        # 關閉自動偵測 integration：huggingface_hub 1.8 與 sentry-sdk 2.60 內建
        # integration 不相容會 AttributeError；只用我們明確列出的 integration
        auto_enabling_integrations=False,
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=False,
        before_send=_before_send,
        attach_stacktrace=True,
    )
    sentry_sdk.set_tag("component", component)
    logger.info(
        "Sentry initialized (env=%s, traces=%s)", environment, traces_sample_rate
    )
