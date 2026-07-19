"""email_service.py HTML escape 護欄測試（XSS audit TODO-7）。

目前所有呼叫端都只傳伺服器常數/token/角色列舉值，無活漏洞——這裡驗證的是
defense-in-depth：一旦未來有人不慎把使用者資料（任務名、自訂 details 等）
塞進這些插值點，escape 要能擋下 HTML injection，而正常內容（含 URL 裡的
`?`/`=`）版型不能跑掉。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("EMAIL_PROVIDER", "console")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.email_service import EmailService  # noqa: E402


class TestRenderBrandedEmailEscaping:
    def setup_method(self):
        self.svc = EmailService()

    def test_normal_url_unchanged(self):
        """正常 URL（含 ? 和 =）escape 後版型不變。"""
        url = "http://localhost:5173/verify-email?token=abc123"
        html_out = self.svc._render_branded_email(
            heading="歡迎加入", intro_html="<p>hi</p>", cta_label="驗證 Email",
            cta_url=url, extra_html="", preheader="",
        )
        assert f'href="{url}"' in html_out
        assert f">{url}<" in html_out

    def test_heading_html_injection_is_escaped(self):
        malicious = "<script>alert(1)</script>"
        html_out = self.svc._render_branded_email(
            heading=malicious, intro_html="<p>hi</p>", cta_label="OK",
            cta_url="http://x/y", extra_html="", preheader="",
        )
        assert "<script>" not in html_out
        assert "&lt;script&gt;" in html_out

    def test_cta_label_html_injection_is_escaped(self):
        malicious = '"><img src=x onerror=alert(1)>'
        html_out = self.svc._render_branded_email(
            heading="ok", intro_html="<p>hi</p>", cta_label=malicious,
            cta_url="http://x/y", extra_html="", preheader="",
        )
        assert "<img src=x onerror=alert(1)>" not in html_out

    def test_cta_url_quote_breakout_is_escaped(self):
        # 嘗試用雙引號跳出 href="..." 屬性
        malicious_url = 'http://evil.com" onmouseover="alert(1)'
        html_out = self.svc._render_branded_email(
            heading="ok", intro_html="<p>hi</p>", cta_label="OK",
            cta_url=malicious_url, extra_html="", preheader="",
        )
        assert 'onmouseover="alert(1)"' not in html_out
        assert "&quot;" in html_out

    def test_preheader_html_injection_is_escaped(self):
        malicious = "<b>fake</b>"
        html_out = self.svc._render_branded_email(
            heading="ok", intro_html="<p>hi</p>", cta_label="OK",
            cta_url="http://x/y", extra_html="", preheader=malicious,
        )
        assert "<b>fake</b>" not in html_out
        assert "&lt;b&gt;fake&lt;/b&gt;" in html_out

    def test_intro_html_and_extra_html_pass_through_unescaped(self):
        # 這兩個參數刻意是 raw HTML，呼叫端負責只傳固定字串
        html_out = self.svc._render_branded_email(
            heading="ok", intro_html="<h2>intro</h2>", cta_label="OK",
            cta_url="http://x/y", extra_html="<p>extra</p>", preheader="",
        )
        assert "<h2>intro</h2>" in html_out
        assert "<p>extra</p>" in html_out


class TestAdminActionNotificationEscaping:
    def setup_method(self):
        self.svc = EmailService()

    def _render(self, **kwargs):
        # send_admin_action_notification 是 async，且會經過 _send_email(console
        # 模式直接印 log 不拋錯)；為了拿到 html_content 直接組裝，這裡改用同一
        # 套邏輯手動呼叫內部組字串的部分不現實——改成 monkeypatch _send_email
        # 攔截傳入的 html_content 更乾淨。
        captured = {}

        async def _fake_send_email(self_, to_email, subject, html_content, text_content=None):
            captured["html_content"] = html_content
            captured["subject"] = subject
            captured["text_content"] = text_content
            return True

        import types
        self.svc._send_email = types.MethodType(_fake_send_email, self.svc)

        import asyncio
        asyncio.run(self.svc.send_admin_action_notification(**kwargs))
        return captured

    def test_details_lines_html_injection_is_escaped(self):
        captured = self._render(
            to_email="user@example.com",
            action_label="方案變更",
            admin_email="admin@example.com",
            details_lines=["<img src=x onerror=alert(1)>", "正常說明"],
        )
        assert "<img src=x onerror=alert(1)>" not in captured["html_content"]
        assert "&lt;img src=x onerror=alert(1)&gt;" in captured["html_content"]
        assert "正常說明" in captured["html_content"]

    def test_admin_email_html_injection_is_escaped(self):
        captured = self._render(
            to_email="user@example.com",
            action_label="帳號已被停用",
            admin_email='"><script>alert(1)</script>',
            details_lines=[],
        )
        assert "<script>alert(1)</script>" not in captured["html_content"]

    def test_action_label_html_injection_is_escaped(self):
        captured = self._render(
            to_email="user@example.com",
            action_label="<script>alert(1)</script>",
            admin_email="admin@example.com",
            details_lines=[],
        )
        assert "<script>alert(1)</script>" not in captured["html_content"]

    def test_normal_payload_renders_unchanged(self):
        captured = self._render(
            to_email="user@example.com",
            action_label="角色已變更：user → admin",
            admin_email="admin@example.com",
            details_lines=["原本角色：user", "新角色：admin"],
        )
        assert "角色已變更：user → admin" in captured["html_content"]
        assert "admin@example.com" in captured["html_content"]
        assert "原本角色：user" in captured["html_content"]
