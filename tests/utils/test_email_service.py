"""send_subscription_email 測試（訂閱生命週期通知：首購開通 / 續扣成功 / 退款撤訂閱 /
加購完成 / 訂閱到期轉免費 / 已排定取消，共六種 kind）。

比照既有 send_dunning_email 的形狀：kind → lang → (heading, body_template, cta_label)。
用 monkeypatch 把 `_send_email` 換成 AsyncMock 攔截，不真的寄信。
"""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("EMAIL_PROVIDER", "console")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.email_service import EmailService  # noqa: E402


def _make_service():
    svc = EmailService()
    svc._send_email = AsyncMock(return_value=True)
    return svc


class TestSendSubscriptionEmail:
    @pytest.mark.parametrize("kind,lang,heading", [
        ("purchase_confirmed", "zh-TW", "訂閱已開通"),
        ("purchase_confirmed", "en", "Your subscription is active"),
        ("renewal_succeeded", "zh-TW", "訂閱已自動續扣"),
        ("renewal_succeeded", "en", "Your subscription renewed"),
        ("refund_revoked", "zh-TW", "訂閱已因退款取消"),
        ("refund_revoked", "en", "Your subscription was cancelled (refund)"),
        ("addon_confirmed", "zh-TW", "加購已完成"),
        ("addon_confirmed", "en", "Your add-on is active"),
        ("subscription_ended", "zh-TW", "訂閱已到期，已轉為免費版"),
        ("subscription_ended", "en", "Your subscription has ended"),
        ("cancel_scheduled", "zh-TW", "已排定取消訂閱"),
        ("cancel_scheduled", "en", "Cancellation scheduled"),
    ])
    async def test_renders_and_sends(self, kind, lang, heading):
        svc = _make_service()
        ok = await svc.send_subscription_email(
            to_email="user@example.com", kind=kind, lang=lang,
            plan="專業版", amount=299, next_charge="2026-09-08", period_end="2026-09-08",
        )
        assert ok is True
        svc._send_email.assert_awaited_once()
        call = svc._send_email.await_args.kwargs
        assert call["subject"] == f"{heading} - SoundLite"
        assert heading in call["html_content"]

    async def test_body_placeholders_substituted_in_text_content(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="purchase_confirmed", lang="zh-TW",
            plan="基礎版", amount=99, next_charge="2026-10-01",
        )
        call = svc._send_email.await_args.kwargs
        assert "基礎版" in call["text_content"]
        assert "2026-10-01" in call["text_content"]

    async def test_unknown_kind_returns_false(self):
        svc = _make_service()
        ok = await svc.send_subscription_email(
            to_email="user@example.com", kind="not_a_real_kind", lang="zh-TW",
        )
        assert ok is False
        svc._send_email.assert_not_awaited()

    async def test_unknown_lang_falls_back_to_zh_tw(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="purchase_confirmed", lang="ja",
            plan="專業版", amount=0, next_charge="2026-09-08",
        )
        call = svc._send_email.await_args.kwargs
        assert "訂閱已開通" in call["html_content"]

    async def test_cta_url_by_kind(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="purchase_confirmed", lang="zh-TW",
        )
        purchase_html = svc._send_email.await_args.kwargs["html_content"]
        assert "/tasks" in purchase_html

        svc2 = _make_service()
        await svc2.send_subscription_email(
            to_email="user@example.com", kind="renewal_succeeded", lang="zh-TW",
        )
        renewal_html = svc2._send_email.await_args.kwargs["html_content"]
        assert "/settings?panel=plan" in renewal_html

        svc3 = _make_service()
        await svc3.send_subscription_email(
            to_email="user@example.com", kind="addon_confirmed", lang="zh-TW",
        )
        addon_html = svc3._send_email.await_args.kwargs["html_content"]
        assert "/tasks" in addon_html

        for kind in ("refund_revoked", "subscription_ended", "cancel_scheduled"):
            svc_n = _make_service()
            await svc_n.send_subscription_email(
                to_email="user@example.com", kind=kind, lang="zh-TW",
            )
            html = svc_n._send_email.await_args.kwargs["html_content"]
            assert "/settings?panel=plan" in html

    async def test_body_html_escaped_exactly_once(self):
        """body 走 html.escape 一次：注入字元被跳脫，且不會因重複 escape 出現 &amp;lt;。"""
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="purchase_confirmed", lang="zh-TW",
            plan='<script>alert(1)</script>', amount=0, next_charge="",
        )
        html_content = svc._send_email.await_args.kwargs["html_content"]
        assert "<script>alert(1)</script>" not in html_content
        assert "&lt;script&gt;" in html_content
        assert "&amp;lt;" not in html_content

    # ── 各 kind 動態值代入驗證（規格 A 測試要求）───────────────────────────

    async def test_refund_revoked_substitutes_plan(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="refund_revoked", lang="zh-TW",
            plan="專業版",
        )
        html_content = svc._send_email.await_args.kwargs["html_content"]
        assert "專業版" in html_content

    async def test_subscription_ended_substitutes_plan(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="subscription_ended", lang="en",
            plan="Pro",
        )
        html_content = svc._send_email.await_args.kwargs["html_content"]
        assert "Pro" in html_content

    async def test_addon_confirmed_substitutes_amount(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="addon_confirmed", lang="zh-TW",
            amount=499,
        )
        html_content = svc._send_email.await_args.kwargs["html_content"]
        assert "499" in html_content

    async def test_cancel_scheduled_substitutes_plan_and_period_end(self):
        svc = _make_service()
        await svc.send_subscription_email(
            to_email="user@example.com", kind="cancel_scheduled", lang="zh-TW",
            plan="基礎版", period_end="2026-12-31",
        )
        html_content = svc._send_email.await_args.kwargs["html_content"]
        assert "基礎版" in html_content
        assert "2026-12-31" in html_content
