"""Resend webhook 端點 — 接收 bounce / complaint 事件並標記 user。

Resend 在 email 投遞失敗或被收件人標 spam 時會 POST 事件到設定的 URL。
冪等性由 ProcessedWebhookRepository（_id unique 約束）保證。

Ops 設定：
1. Resend dashboard → Webhooks → Add Endpoint:
       URL: https://soundlite.app/webhooks/resend
       Events: email.bounced, email.complained
2. 把 Resend 給的 webhook secret（whsec_...）放到：
       - SSM: /transcriber/resend-webhook-secret
       - 或 env: RESEND_WEBHOOK_SECRET
"""
import json
import time

from fastapi import APIRouter, Depends, Request, status

from ..database.mongodb import get_database
from ..database.repositories.processed_webhook_repo import ProcessedWebhookRepository
from ..database.repositories.user_repo import UserRepository
from ..utils.api_errors import api_error
from ..utils.audit_logger import get_audit_logger
from ..utils.config_loader import get_parameter
from ..utils.logger import get_logger
from ..utils.privacy import mask_email
from ..utils.resend_webhook import (
    InvalidWebhookSignature,
    verify_signature,
)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
log = get_logger(__name__)


# 單一 webhook event 可處理的 recipient 上限 — 防 secret 外洩後 attacker 用
# 巨大 to_field 一次 mark 大量 user。Resend 實際單封 send 通常 to=1 名收件人。
MAX_RECIPIENTS_PER_EVENT = 50

# email_bounce_reason 寫 DB 的長度上限 — 防 attacker-controlled 1MB 字串
MAX_REASON_LENGTH = 500


# 認定為「永久失敗」的事件 → 標 email_bounced
# - email.bounced:    收件方 server 永久拒絕（hard bounce）
# - email.complained: 用戶按 mark as spam
# - email.suppressed: Resend 自己 suppression list 攔下（通常源於先前 bounce）
#
# 故意不放 email.failed：該事件涵蓋「無效收件人」與「我們的 API key /
# domain / 配額問題」，後者不該歸咎於使用者的 email。要做的話需要解析
# data.failed.reason，目前先 log 不自動處理。
HARD_FAIL_EVENTS = {"email.bounced", "email.complained", "email.suppressed"}


@router.post("/resend")
async def resend_webhook(
    request: Request,
    db=Depends(get_database),
):
    """接收 Resend 推送的 email 事件。"""
    audit_logger = get_audit_logger()

    # 1. 取 secret（SSM 優先，env fallback）
    secret = get_parameter(
        "/transcriber/resend-webhook-secret",
        fallback_env="RESEND_WEBHOOK_SECRET",
    )
    if not secret:
        log.error("resend_webhook.no_secret_configured")
        # 不暴露細節；只回 500 讓 ops 看 log
        raise api_error("WEBHOOK_MISCONFIGURED", "webhook misconfigured", status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 2. 驗簽
    raw_body = await request.body()
    try:
        verify_signature(
            secret=secret,
            svix_id=request.headers.get("svix-id", ""),
            svix_timestamp=request.headers.get("svix-timestamp", ""),
            svix_signature=request.headers.get("svix-signature", ""),
            raw_body=raw_body,
        )
    except InvalidWebhookSignature as e:
        # 簽名驗證失敗一律 log.warning（廉價），但 audit_log 為避免被
        # 大量假請求灌爆，只在能成功 claim 「signature_failed:<IP>:<minute>」
        # bucket 時寫入 — 每 IP 每分鐘最多 1 筆 audit。
        log.warning(
            "resend_webhook.signature_failed",
            reason=str(e),
            remote=request.client.host if request.client else None,
        )
        client_ip = request.client.host if request.client else "unknown"
        minute_bucket = int(time.time()) // 60
        bucket_repo = ProcessedWebhookRepository(db)
        if await bucket_repo.claim(
            provider="resend-sigfail",
            natural_id=f"{client_ip}:{minute_bucket}",
            metadata={"reason": str(e)[:200]},
        ):
            await audit_logger.log_auth(
                request=request,
                action="resend_webhook_invalid_signature",
                user_id=None,
                status_code=401,
                message=f"webhook 簽名驗證失敗: {e}",
            )
        raise api_error("WEBHOOK_INVALID_SIGNATURE", "invalid signature", status.HTTP_401_UNAUTHORIZED)

    # 3. 解析 body
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise api_error("WEBHOOK_INVALID_JSON", "invalid json body", status.HTTP_400_BAD_REQUEST)

    event_type = payload.get("type", "")
    data = payload.get("data") or {}
    # Resend event data 中 to 官方文件是 array of string；歷史上偶見字串；
    # 未來可能改為 list of dict (Recipient object) — 已加 dict 抽取 fallback。
    # 過濾出真正有 @ 的字串，擋掉空字串、純空白、其他怪資料。
    to_field = data.get("to")
    recipients: list[str] = []
    if isinstance(to_field, list):
        for x in to_field:
            if len(recipients) >= MAX_RECIPIENTS_PER_EVENT:
                break  # 截斷，避免 secret 外洩後 DoS
            if isinstance(x, str) and "@" in x and x.strip():
                recipients.append(x.strip())
            elif isinstance(x, dict):
                # 防禦：Resend 若改 schema 用 {"email": "..."} 或 {"address": "..."}
                addr = x.get("email") or x.get("address")
                if isinstance(addr, str) and "@" in addr and addr.strip():
                    recipients.append(addr.strip())
    elif isinstance(to_field, str) and "@" in to_field and to_field.strip():
        recipients = [to_field.strip()]

    # 若被截斷則明確 warning（正常 Resend send 1 名收件人，超過 50 必異常）
    if isinstance(to_field, list) and len(to_field) > MAX_RECIPIENTS_PER_EVENT:
        log.warning(
            "resend_webhook.recipients_truncated",
            event=event_type,
            received=len(to_field),
            kept=len(recipients),
        )

    svix_id = request.headers.get("svix-id", "")

    log.info(
        "resend_webhook.received",
        event=event_type,
        svix_id=svix_id,
        recipients=[mask_email(r) for r in recipients],
    )

    # 4. 先過濾事件類型 — 只對 hard-fail 才寫 processed_webhooks
    # （否則 email.delivered / opened / clicked 等高頻事件會塞爆 collection）
    if event_type not in HARD_FAIL_EVENTS:
        return {"status": "ignored", "event": event_type}

    # hard-fail 但收件人空（payload schema 異常）→ 仍 ack 200 但不佔 claim
    if not recipients:
        log.warning(
            "resend_webhook.hard_fail_no_recipients",
            event=event_type,
            svix_id=svix_id,
            payload_keys=list(data.keys()),
        )
        return {"status": "ignored", "event": event_type, "reason": "no_recipients"}

    # 5. 冪等性：用 svix-id 當 natural_id
    webhook_repo = ProcessedWebhookRepository(db)
    natural_id = svix_id or f"no-id-{event_type}-{data.get('email_id', '')}"
    if not await webhook_repo.claim(
        provider="resend",
        natural_id=natural_id,
        metadata={"event": event_type},
    ):
        log.info("resend_webhook.duplicate_skipped", svix_id=svix_id)
        return {"status": "duplicate"}

    # 6. 標記受影響 user（失敗時 release claim 讓 Resend 重試能重新處理）
    try:
        user_repo = UserRepository(db)
        short_event = event_type.split(".", 1)[-1]  # "bounced" / "complained" / "suppressed"

        # 從不同 event schema 抽 reason：
        #   bounced:    data.bounce.message + data.bounce.subType
        #   complained: 通常無 reason 欄位
        #   suppressed: 推測 data.suppressed.reason（schema 未官方確認）
        bounce_info = data.get("bounce") or {}
        suppressed_info = data.get("suppressed") or {}
        reason = (
            bounce_info.get("message")
            or bounce_info.get("subType")
            or suppressed_info.get("reason")
            or None
        )
        # 截斷防 attacker-controlled 巨大字串塞 DB / 拖慢 query
        if isinstance(reason, str) and len(reason) > MAX_REASON_LENGTH:
            reason = reason[:MAX_REASON_LENGTH] + "…(truncated)"

        marked = 0
        for to_email in recipients:
            ok = await user_repo.mark_email_bounced(
                email=to_email,
                event_type=short_event,
                reason=reason,
            )
            if ok:
                marked += 1
                await audit_logger.log_auth(
                    request=request,
                    action=f"email_{short_event}",
                    user_id=None,
                    status_code=200,
                    message=f"email {short_event}: {to_email} ({reason or 'no reason'})",
                )
            else:
                # 沒有對應 user — 可能 admin 通知信、test send、或 email
                # 大小寫與 DB 存的不一致（codebase-wide localpart case 議題）
                log.warning(
                    "resend_webhook.no_user_for_recipient",
                    event=event_type,
                    recipient=mask_email(to_email),
                )

        log.info(
            "resend_webhook.processed",
            event=event_type,
            recipients=[mask_email(r) for r in recipients],
            marked=marked,
        )
        return {"status": "ok", "event": event_type, "marked": marked}
    except Exception:
        # DB 抖動 / mark_email_bounced 失敗 → release claim 讓 Resend 重試能再進來
        await webhook_repo.release(provider="resend", natural_id=natural_id)
        log.error("resend_webhook.processing_failed", svix_id=svix_id, exc_info=True)
        # 同時寫 audit log 方便監控 release loop（Resend 最多重試 16 次，
        # 若同 svix_id 看到多筆 audit 代表 DB 持續異常）
        await audit_logger.log_auth(
            request=request,
            action="resend_webhook_release",
            user_id=None,
            status_code=500,
            message=f"webhook processing failed, claim released: svix_id={svix_id}",
        )
        raise
