"""Resend webhook 簽名驗證測試（P1-15）。"""
import base64
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.utils.resend_webhook import (  # noqa: E402
    InvalidWebhookSignature,
    verify_signature,
)


# Helper：產生一組合法簽名供測試用
def _make_signature(secret: str, svix_id: str, svix_ts: str, body: bytes) -> str:
    key = base64.b64decode(secret[len("whsec_"):] if secret.startswith("whsec_") else secret)
    signed = f"{svix_id}.{svix_ts}.".encode("utf-8") + body
    digest = hmac.new(key, signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("utf-8")


@pytest.fixture
def secret():
    """模擬 Resend 給的 webhook secret（whsec_ 前綴 + base64 32B key）"""
    return "whsec_" + base64.b64encode(b"\x01" * 32).decode("utf-8")


@pytest.fixture
def now():
    return int(time.time())


def test_valid_signature_passes(secret, now):
    body = b'{"type":"email.bounced","data":{"to":"a@b.com"}}'
    svix_id = "msg_abc123"
    sig = _make_signature(secret, svix_id, str(now), body)

    verify_signature(
        secret=secret,
        svix_id=svix_id,
        svix_timestamp=str(now),
        svix_signature=sig,
        raw_body=body,
        now_ts=now,
    )  # 不拋即為通過


def test_secret_without_prefix_also_works(now):
    raw_secret = base64.b64encode(b"\x02" * 32).decode("utf-8")
    body = b"{}"
    sig = _make_signature(raw_secret, "x", str(now), body)
    verify_signature(
        secret=raw_secret,  # 無 whsec_ 前綴
        svix_id="x",
        svix_timestamp=str(now),
        svix_signature=sig,
        raw_body=body,
        now_ts=now,
    )


def test_missing_headers_raises(secret, now):
    with pytest.raises(InvalidWebhookSignature, match="缺少 svix"):
        verify_signature(
            secret=secret,
            svix_id="",
            svix_timestamp=str(now),
            svix_signature="v1,xxx",
            raw_body=b"{}",
            now_ts=now,
        )


def test_wrong_signature_raises(secret, now):
    with pytest.raises(InvalidWebhookSignature, match="不匹配"):
        verify_signature(
            secret=secret,
            svix_id="msg",
            svix_timestamp=str(now),
            svix_signature="v1,wrongsig",
            raw_body=b"{}",
            now_ts=now,
        )


def test_expired_timestamp_raises(secret, now):
    """超過 5 分鐘容忍 → 拒絕（replay 防護）。"""
    old_ts = now - 600  # 10 分鐘前
    body = b"{}"
    sig = _make_signature(secret, "msg", str(old_ts), body)

    with pytest.raises(InvalidWebhookSignature, match="超過容忍範圍"):
        verify_signature(
            secret=secret,
            svix_id="msg",
            svix_timestamp=str(old_ts),
            svix_signature=sig,
            raw_body=body,
            now_ts=now,
        )


def test_future_timestamp_also_raises(secret, now):
    """未來時間也超出容忍 → 拒絕。"""
    future_ts = now + 600
    body = b"{}"
    sig = _make_signature(secret, "msg", str(future_ts), body)
    with pytest.raises(InvalidWebhookSignature, match="超過容忍範圍"):
        verify_signature(
            secret=secret,
            svix_id="msg",
            svix_timestamp=str(future_ts),
            svix_signature=sig,
            raw_body=body,
            now_ts=now,
        )


def test_non_integer_timestamp_raises(secret, now):
    with pytest.raises(InvalidWebhookSignature, match="非整數"):
        verify_signature(
            secret=secret,
            svix_id="msg",
            svix_timestamp="not-a-number",
            svix_signature="v1,xxx",
            raw_body=b"{}",
            now_ts=now,
        )


def test_body_mismatch_fails_signature(secret, now):
    """改動 body 後簽名不再有效。"""
    body = b'{"to":"a@b.com"}'
    sig = _make_signature(secret, "msg", str(now), body)

    tampered = b'{"to":"attacker@bad.com"}'  # 攻擊者改了 body
    with pytest.raises(InvalidWebhookSignature, match="不匹配"):
        verify_signature(
            secret=secret,
            svix_id="msg",
            svix_timestamp=str(now),
            svix_signature=sig,
            raw_body=tampered,
            now_ts=now,
        )


def test_multiple_signatures_one_valid_passes(secret, now):
    """svix-signature 可帶多個版本/簽名；只要有一個對就通過。"""
    body = b"{}"
    valid_sig = _make_signature(secret, "msg", str(now), body)
    multi = f"v1,fake1 {valid_sig} v2,unsupported"

    verify_signature(
        secret=secret,
        svix_id="msg",
        svix_timestamp=str(now),
        svix_signature=multi,
        raw_body=body,
        now_ts=now,
    )


def test_only_unsupported_version_rejected(secret, now):
    """全部都不是 v1 → 拒絕。"""
    with pytest.raises(InvalidWebhookSignature, match="不匹配"):
        verify_signature(
            secret=secret,
            svix_id="msg",
            svix_timestamp=str(now),
            svix_signature="v2,xxxx v9,yyyy",
            raw_body=b"{}",
            now_ts=now,
        )


def test_empty_secret_raises_invalid_signature(now):
    """secret 沒設應 fail（避免靜默通過）。_decode_secret 已收斂為
    InvalidWebhookSignature 讓 router 統一 catch 後回 401。"""
    with pytest.raises(InvalidWebhookSignature, match="未設定"):
        verify_signature(
            secret="",
            svix_id="msg",
            svix_timestamp=str(now),
            svix_signature="v1,xxx",
            raw_body=b"{}",
            now_ts=now,
        )


def test_malformed_base64_secret_raises_invalid_signature(now):
    """secret 不是合法 base64 也要拋 InvalidWebhookSignature 而非 ValueError，
    避免 router 沒 catch 漏到 500。"""
    with pytest.raises(InvalidWebhookSignature, match="base64"):
        verify_signature(
            secret="whsec_!!!not_valid_base64!!!",
            svix_id="msg",
            svix_timestamp=str(now),
            svix_signature="v1,xxx",
            raw_body=b"{}",
            now_ts=now,
        )


def test_secret_only_prefix_no_value_raises(now):
    """secret 只有 "whsec_" 前綴沒實際內容（ops paste 殘缺）→ decode 後是
    空 bytes，HMAC 仍能算出（用 zero-length key），但攻擊者也可猜出來。
    應該明確拒絕避免靜默接受所有簽名。"""
    with pytest.raises(InvalidWebhookSignature):
        verify_signature(
            secret="whsec_",
            svix_id="msg",
            svix_timestamp=str(now),
            svix_signature="v1,xxx",
            raw_body=b"{}",
            now_ts=now,
        )
