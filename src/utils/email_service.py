"""Email 發送服務"""
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import os
from jinja2 import Template

from src.utils.logger import get_logger
from src.utils.privacy import mask_email

log = get_logger(__name__)


# 寬鬆的 email 格式檢查：localpart@domain.tld，擋掉空字串、缺 @、缺 TLD
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class EmailConfigError(RuntimeError):
    """Email 服務設定不完整時拋出，讓 startup 直接 fail-fast。"""


class EmailService:
    """Email 發送服務類"""

    def __init__(self):
        """初始化 Email 服務配置，並依 provider 驗證必要環境變數。

        - console: 不驗證（本地開發預設）
        - resend / ses: FROM_EMAIL 必填且為合法 email 格式
        - smtp: SMTP_HOST、SMTP_USER、SMTP_PASSWORD、FROM_EMAIL 都需齊
        """
        self.email_provider = os.getenv("EMAIL_PROVIDER", "console")
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        # 不再對沒有 verified domain 的 SMTP_USER fallback，避免發出 invalid From header
        self.from_email = os.getenv("FROM_EMAIL", "").strip()
        self.from_name = os.getenv("FROM_NAME", "Sound Lite 服務")
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

        self._validate_config()

    def _validate_config(self) -> None:
        """依 provider 驗證設定；不通過直接拋 EmailConfigError。"""
        provider = self.email_provider

        if provider == "console":
            return

        if provider not in ("resend", "ses", "smtp"):
            raise EmailConfigError(
                f"EMAIL_PROVIDER={provider!r} 不支援；可選 console / resend / ses / smtp"
            )

        # resend / ses / smtp 都要 from_email
        if not self.from_email:
            raise EmailConfigError(
                f"EMAIL_PROVIDER={provider} 需要設定 FROM_EMAIL 環境變數"
            )
        if not _EMAIL_RE.match(self.from_email):
            raise EmailConfigError(
                f"FROM_EMAIL={self.from_email!r} 非合法 email 格式"
            )

        # resend / ses 額外要求 from_email 必須是 provider 已驗證的 domain。
        # 這裡無法做遠端驗證，只能提示 ops 注意 — 在 logger 留下明確 warning。
        if provider in ("resend", "ses"):
            # resend 還需要 API key — 啟動就確認，不要等第一個用戶註冊才爆
            if provider == "resend":
                from src.utils.config_loader import get_parameter
                api_key = get_parameter(
                    "/transcriber/resend-api-key",
                    fallback_env="RESEND_API_KEY",
                )
                if not api_key:
                    raise EmailConfigError(
                        "EMAIL_PROVIDER=resend 但 RESEND_API_KEY 未設定 "
                        "(SSM: /transcriber/resend-api-key 或 env: RESEND_API_KEY)"
                    )
            log.info(
                "email.config.validated",
                provider=provider,
                from_email=self.from_email,
                note="ensure_from_email_domain_is_verified_on_provider",
            )
            return

        # SMTP：需要完整的連線設定
        if provider == "smtp":
            missing = []
            if not self.smtp_host:
                missing.append("SMTP_HOST")
            if not self.smtp_user:
                missing.append("SMTP_USER")
            if not self.smtp_password:
                missing.append("SMTP_PASSWORD")
            if missing:
                raise EmailConfigError(
                    f"EMAIL_PROVIDER=smtp 缺少必要環境變數: {', '.join(missing)}"
                )
            log.info(
                "email.config.validated",
                provider="smtp",
                from_email=self.from_email,
                smtp_host=self.smtp_host,
            )

    async def send_verification_email(
        self,
        to_email: str,
        verification_token: str
    ) -> bool:
        """發送驗證郵件

        Args:
            to_email: 收件人 email
            verification_token: 驗證 token

        Returns:
            是否發送成功
        """
        verification_url = f"{self.frontend_url}/verify-email?token={verification_token}"

        # Email 模板 - 使用內聯樣式以確保郵件客戶端相容性
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; color: white;">歡迎使用 Sound Lite 服務</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <h2 style="margin-top: 0;">請驗證您的電子郵件地址</h2>
                <p>感謝您註冊！請點擊下方按鈕驗證您的 email：</p>

                <div style="text-align: center; margin: 30px 0;">
                    <!--[if mso]>
                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{ verification_url }}" style="height:50px;v-text-anchor:middle;width:200px;" arcsize="10%" stroke="f" fillcolor="#667eea">
                        <w:anchorlock/>
                        <center style="color:#ffffff;font-family:sans-serif;font-size:16px;font-weight:bold;">驗證 Email</center>
                    </v:roundrect>
                    <![endif]-->
                    <!--[if !mso]><!-->
                    <a href="{{ verification_url }}" style="display: inline-block; padding: 15px 30px; background-color: #667eea; color: #ffffff !important; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">驗證 Email</a>
                    <!--<![endif]-->
                </div>

                <p>或者複製以下連結到瀏覽器：</p>
                <div style="background: #fff; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0; word-break: break-all;">
                    <a href="{{ verification_url }}" style="color: #667eea; text-decoration: none;">{{ verification_url }}</a>
                </div>

                <p><strong>注意：</strong>此驗證連結將在 24 小時後過期。</p>

                <p>如果您沒有註冊此帳號，請忽略此郵件。</p>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #666; font-size: 12px;">
                <p style="margin: 0 0 4px 0;">此為系統自動寄送，請勿直接回覆。</p>
                <p style="margin: 0;">© 2026 Sound Lite. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        template = Template(html_template)
        html_content = template.render(verification_url=verification_url)

        # 純文字版本（備用）
        text_content = f"""
        歡迎使用 Sound Lite 轉錄服務！

        請點擊以下連結驗證您的 email：
        {verification_url}

        此驗證連結將在 24 小時後過期。

        如果您沒有註冊此帳號，請忽略此郵件。

        ─────────────────────────────
        此為系統自動寄送，請勿直接回覆。
        """

        return await self._send_email(
            to_email=to_email,
            subject="驗證您的 Email - Sound Lite",
            html_content=html_content,
            text_content=text_content
        )

    async def send_password_reset_email(
        self,
        to_email: str,
        reset_token: str
    ) -> bool:
        """發送密碼重設郵件

        Args:
            to_email: 收件人 email
            reset_token: 密碼重設 token

        Returns:
            是否發送成功
        """
        reset_url = f"{self.frontend_url}/reset-password?token={reset_token}"

        # Email 模板 - 使用內聯樣式以確保郵件客戶端相容性
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; color: white;">密碼重設請求</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <h2 style="margin-top: 0;">重設您的密碼</h2>
                <p>我們收到了您的密碼重設請求。請點擊下方按鈕重設您的密碼：</p>

                <div style="text-align: center; margin: 30px 0;">
                    <!--[if mso]>
                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{ reset_url }}" style="height:50px;v-text-anchor:middle;width:200px;" arcsize="10%" stroke="f" fillcolor="#667eea">
                        <w:anchorlock/>
                        <center style="color:#ffffff;font-family:sans-serif;font-size:16px;font-weight:bold;">重設密碼</center>
                    </v:roundrect>
                    <![endif]-->
                    <!--[if !mso]><!-->
                    <a href="{{ reset_url }}" style="display: inline-block; padding: 15px 30px; background-color: #667eea; color: #ffffff !important; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">重設密碼</a>
                    <!--<![endif]-->
                </div>

                <p>或者複製以下連結到瀏覽器：</p>
                <div style="background: #fff; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0; word-break: break-all;">
                    <a href="{{ reset_url }}" style="color: #667eea; text-decoration: none;">{{ reset_url }}</a>
                </div>

                <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; color: #856404;">
                    <strong>注意：</strong>此連結將在 1 小時後過期。如果您沒有請求重設密碼，請忽略此郵件，您的帳號仍然安全。
                </div>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #666; font-size: 12px;">
                <p style="margin: 0 0 4px 0;">此為系統自動寄送，請勿直接回覆。</p>
                <p style="margin: 0;">© 2026 Sound Lite. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        template = Template(html_template)
        html_content = template.render(reset_url=reset_url)

        # 純文字版本（備用）
        text_content = f"""
        密碼重設請求 - Sound Lite

        我們收到了您的密碼重設請求。請點擊以下連結重設您的密碼：
        {reset_url}

        此連結將在 1 小時後過期。

        如果您沒有請求重設密碼，請忽略此郵件，您的帳號仍然安全。

        ─────────────────────────────
        此為系統自動寄送，請勿直接回覆。
        """

        return await self._send_email(
            to_email=to_email,
            subject="重設您的密碼 - Sound Lite",
            html_content=html_content,
            text_content=text_content
        )

    async def send_admin_action_notification(
        self,
        to_email: str,
        action_label: str,
        admin_email: str,
        details_lines: Optional[list] = None,
    ) -> bool:
        """通知使用者 admin 對其帳號執行了高權限操作。

        Args:
            to_email: 收件使用者
            action_label: 可讀文字，例如「密碼被重設」「帳號已停用」「方案變更」
            admin_email: 執行的 admin email（出現在內文供使用者確認）
            details_lines: 額外條列說明（每行一個 bullet）
        """
        details_lines = details_lines or []
        details_html = "".join(
            f"<li style='margin: 4px 0;'>{line}</li>" for line in details_lines
        )
        details_block = (
            f"<ul style='background: #fff; padding: 15px 30px; border-left: 4px solid #ffc107; margin: 20px 0;'>{details_html}</ul>"
            if details_lines else ""
        )

        html_content = f"""
        <!DOCTYPE html>
        <html><head><meta charset="UTF-8"></head>
        <body style="font-family: 'Segoe UI', sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #d9534f 0%, #c9302c 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0; color: white;">⚠️ 帳號異動通知</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p>您好，</p>
                <p>您在 Sound Lite 的帳號剛剛由管理員 <strong>{admin_email}</strong> 執行了以下操作：</p>
                <p style="font-size: 18px; font-weight: bold; color: #c9302c;">{action_label}</p>
                {details_block}
                <p>如果這是您預期或要求的操作（例如協助重設密碼），可忽略此信。</p>
                <p>若您<strong>不認識此 admin</strong>或<strong>未授權此操作</strong>，請立即回信此地址，並考慮：</p>
                <ul>
                    <li>立即登入更改密碼</li>
                    <li>檢查近期登入紀錄是否異常</li>
                </ul>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #666; font-size: 12px;">
                <p>© 2026 Sound Lite. All rights reserved.</p>
            </div>
        </body></html>
        """

        text_content = (
            f"帳號異動通知\n\n"
            f"您的 Sound Lite 帳號由管理員 {admin_email} 執行了：\n  {action_label}\n\n"
            + ("\n".join(f"  - {line}" for line in details_lines) + "\n\n" if details_lines else "")
            + "若您未授權此操作，請立即回信本地址。"
        )

        return await self._send_email(
            to_email=to_email,
            subject=f"[Sound Lite] 帳號異動通知：{action_label}",
            html_content=html_content,
            text_content=text_content,
        )

    async def _send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """發送 Email

        Args:
            to_email: 收件人
            subject: 主題
            html_content: HTML 內容
            text_content: 純文字內容（可選）

        Returns:
            是否發送成功
        """
        try:
            # 根據 EMAIL_PROVIDER 選擇發送方式
            if self.email_provider == "ses":
                return self._send_via_ses(to_email, subject, html_content, text_content)
            elif self.email_provider == "resend":
                return self._send_via_resend(to_email, subject, html_content, text_content)
            elif self.email_provider == "smtp" or (self.smtp_user and self.smtp_password):
                return self._send_via_smtp(to_email, subject, html_content, text_content)
            else:
                # console 模式：印到終端（開發環境）
                log.info(
                    "email.console_mode",
                    to_email=to_email,
                    subject=subject,
                    body=text_content if text_content else "(HTML only)",
                )
                return True

        except Exception as e:
            log.error("email.send_failed", error=str(e))
            return False

    def _send_via_smtp(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """透過 SMTP 發送"""
        # 創建郵件
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{self.from_name} <{self.from_email}>"
        msg['To'] = to_email

        # 添加內容
        if text_content:
            msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        # 發送郵件
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

        log.info("email.sent", to_email=mask_email(to_email), provider="smtp")
        return True

    def _send_via_ses(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """透過 AWS SES 發送"""
        import boto3

        ses = boto3.client("ses", region_name=os.getenv("S3_REGION", "ap-northeast-1"))

        body = {"Html": {"Data": html_content, "Charset": "UTF-8"}}
        if text_content:
            body["Text"] = {"Data": text_content, "Charset": "UTF-8"}

        ses.send_email(
            Source=f"{self.from_name} <{self.from_email}>",
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": body,
            },
        )

        log.info("email.sent", to_email=mask_email(to_email), provider="ses")
        return True

    def _send_via_resend(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """透過 Resend 發送"""
        import resend
        from .config_loader import get_parameter

        resend.api_key = get_parameter(
            "/transcriber/resend-api-key",
            fallback_env="RESEND_API_KEY"
        )

        if not resend.api_key:
            raise ValueError("RESEND_API_KEY environment variable is not set")

        params = {
            "from": f"{self.from_name} <{self.from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }

        if text_content:
            params["text"] = text_content

        resend.Emails.send(params)

        log.info("email.sent", to_email=mask_email(to_email), provider="resend")
        return True


# 單例
_email_service: Optional[EmailService] = None

def get_email_service() -> EmailService:
    """獲取 Email 服務實例"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
