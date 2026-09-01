"""Sentry 初始化（FastAPI server 與 SQS worker 共用）。

未設定 SENTRY_DSN 時 no-op，本地開發不會送資料。
"""
import os

from src.utils.logger import get_logger

logger = get_logger(__name__)

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
    "verify_key",  # SmilePay 電子發票商家憑證（Grvc 搭配的驗證碼）
)


def _is_sensitive(key) -> bool:
    if not isinstance(key, str):
        return False
    # 正規化連字號 → 底線：header 式命名（如 91APP 的 N1-API-KEY）不會漏掉。
    # 否則 "n1-api-key" 不含子字串 "api_key"，API 金鑰會隨例外堆疊 frame vars 進 Sentry（金流體檢 P2-11）。
    k = key.lower().replace("-", "_")
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


def _scrub_stacktrace_vars(section) -> None:
    """遮蔽例外/thread 堆疊裡的 frame local variables。

    include_local_variables 預設開啟，frame 的區域變數（含持有憑證的 dict，
    如 smilepay_service._post 的 body）會整包進 event["exception"]，
    而 SDK 內建 EventScrubber 只比對頂層變數名、不遞迴，擋不住巢狀的敏感 key。
    """
    for entry in (section or {}).get("values") or []:
        for frame in (entry.get("stacktrace") or {}).get("frames") or []:
            if "vars" in frame:
                frame["vars"] = _scrub(frame["vars"])


def _before_send(event, hint):
    for key in ("request", "extra", "contexts"):
        if key in event:
            event[key] = _scrub(event[key])
    for key in ("exception", "threads"):
        if key in event:
            _scrub_stacktrace_vars(event[key])
    return event


def _before_breadcrumb(crumb, hint):
    # httpx/logging 等 auto-instrumentation 可能把 request body/params 塞進 breadcrumb data；
    # before_send 只掃 event 本身掃不到 breadcrumb，故另掛一個 hook（見 SmilePay Verify_key 需求）。
    if "data" in crumb:
        crumb["data"] = _scrub(crumb["data"])
    return crumb


def init_sentry(component: str = "server") -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning("sentry.sdk_not_installed")
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
        before_breadcrumb=_before_breadcrumb,
        attach_stacktrace=True,
    )
    sentry_sdk.set_tag("component", component)
    logger.info(
        "sentry.initialized",
        environment=environment,
        traces_sample_rate=traces_sample_rate,
    )
