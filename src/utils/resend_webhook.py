"""Resend webhook 簽名驗證（svix 規格）。

Resend 使用 svix 託管 webhook 發送，headers 形如：
    svix-id:        <unique event id>
    svix-timestamp: <unix timestamp seconds>
    svix-signature: v1,<base64-sig1> v1,<base64-sig2>...   # 可能多個

驗簽算法：
    signed = f"{svix_id}.{svix_timestamp}.{raw_body}"
    expected = base64( HMAC-SHA256( secret_bytes, signed ) )

secret 由 Resend dashboard 提供，預設前綴 "whsec_"，要 strip 後 base64-decode。

參考：https://docs.svix.com/receiving/verifying-payloads/how-manual
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional

from src.utils.logger import get_logger

log = get_logger(__name__)


# 容忍時間差：拒絕超過 5 分鐘前 / 後的事件以擋 replay
SIGNATURE_TOLERANCE_SECONDS = 5 * 60


class InvalidWebhookSignature(Exception):
    """簽名驗證失敗。caller 應回 401。"""


def _decode_secret(secret: str) -> bytes:
    """把 Resend 給的 'whsec_xxxxx' 轉成真正的 HMAC key bytes。

    secret 必須非空且為合法 base64。caller 須事先確認 secret 已設定
    （見 router 中的 if not secret 檢查）；若仍為空、或 base64 損壞，
    一律拋 InvalidWebhookSignature 讓 router catch 後回 401 而非 500。
    """
    if not secret:
        raise InvalidWebhookSignature("RESEND_WEBHOOK_SECRET 未設定或為空")
    # 容忍前綴大小寫變體
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    # 「whsec_」純前綴 / 任何 strip 後是空字串都拒絕，避免 zero-length HMAC key
    # 讓攻擊者能輕易產出合法簽名
    if not secret:
        raise InvalidWebhookSignature("RESEND_WEBHOOK_SECRET strip 前綴後為空")
    try:
        decoded = base64.b64decode(secret)
    except Exception as e:
        raise InvalidWebhookSignature(f"webhook secret 不是有效的 base64: {e}") from e
    if not decoded:
        raise InvalidWebhookSignature("RESEND_WEBHOOK_SECRET base64 decode 後為空")
    return decoded


def verify_signature(
    *,
    secret: str,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    raw_body: bytes,
    now_ts: Optional[int] = None,
) -> None:
    """驗證 svix 規格的 webhook 簽名。

    失敗時拋 InvalidWebhookSignature；成功 return None。

    Args:
        secret: Resend 控制台給的 webhook secret（含或不含 whsec_ 前綴皆可）
        svix_id: svix-id header 原值
        svix_timestamp: svix-timestamp header 原值（unix seconds 字串）
        svix_signature: svix-signature header 原值（"v1,<sig> v1,<sig>" 形式）
        raw_body: HTTP body 原始 bytes（不能用 reserialized JSON，會破壞簽名）
        now_ts: 注入用，預設取系統時間

    Raises:
        InvalidWebhookSignature: 任何驗證失敗
    """
    if not (svix_id and svix_timestamp and svix_signature):
        raise InvalidWebhookSignature("缺少 svix-* headers")

    # 1. timestamp 防 replay
    try:
        ts = int(svix_timestamp)
    except ValueError as e:
        raise InvalidWebhookSignature(f"svix-timestamp 非整數: {e}") from e

    now = now_ts if now_ts is not None else int(time.time())
    if abs(now - ts) > SIGNATURE_TOLERANCE_SECONDS:
        raise InvalidWebhookSignature(
            f"svix-timestamp 偏離 {abs(now - ts)}s 超過容忍範圍"
        )

    # 2. 計算期望簽名
    key = _decode_secret(secret)
    signed_payload = f"{svix_id}.{svix_timestamp}.".encode("utf-8") + raw_body
    expected = base64.b64encode(
        hmac.new(key, signed_payload, hashlib.sha256).digest()
    ).decode("utf-8")

    # 3. svix-signature 可能含多個版本 / 多個簽名，逐個比對
    # 形如: "v1,abcdef v1,zzz v2,unsupported"
    matched = False
    for token in svix_signature.split():
        if "," not in token:
            continue
        version, sig = token.split(",", 1)
        if version != "v1":
            continue  # 暫不支援其他版本
        if hmac.compare_digest(sig, expected):
            matched = True
            break

    if not matched:
        raise InvalidWebhookSignature("簽名不匹配")
