"""Email 發送服務"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import os
from jinja2 import Template

class EmailService:
    """Email 發送服務類"""

    def __init__(self):
        """初始化 Email 服務配置"""
        self.email_provider = os.getenv("EMAIL_PROVIDER", "console")
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", self.smtp_user)
        self.from_name = os.getenv("FROM_NAME", "Whisper 轉錄服務")
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

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
                <h1 style="margin: 0; color: white;">歡迎使用 Whisper 轉錄服務</h1>
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
                <p>© 2024 Whisper 轉錄服務. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        template = Template(html_template)
        html_content = template.render(verification_url=verification_url)

        # 純文字版本（備用）
        text_content = f"""
        歡迎使用 Whisper 轉錄服務！

        請點擊以下連結驗證您的 email：
        {verification_url}

        此驗證連結將在 24 小時後過期。

        如果您沒有註冊此帳號，請忽略此郵件。
        """

        return await self._send_email(
            to_email=to_email,
            subject="驗證您的 Email - Whisper 轉錄服務",
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
                <p>© 2024 Whisper 轉錄服務. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        template = Template(html_template)
        html_content = template.render(reset_url=reset_url)

        # 純文字版本（備用）
        text_content = f"""
        密碼重設請求 - Whisper 轉錄服務

        我們收到了您的密碼重設請求。請點擊以下連結重設您的密碼：
        {reset_url}

        此連結將在 1 小時後過期。

        如果您沒有請求重設密碼，請忽略此郵件，您的帳號仍然安全。
        """

        return await self._send_email(
            to_email=to_email,
            subject="重設您的密碼 - Whisper 轉錄服務",
            html_content=html_content,
            text_content=text_content
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
            elif self.email_provider == "smtp" or (self.smtp_user and self.smtp_password):
                return self._send_via_smtp(to_email, subject, html_content, text_content)
            else:
                # console 模式：印到終端（開發環境）
                print(f"\n{'='*60}")
                print(f"📧 Email 發送（開發模式）")
                print(f"{'='*60}")
                print(f"收件人: {to_email}")
                print(f"主題: {subject}")
                print(f"\n{text_content if text_content else '(HTML only)'}")
                print(f"{'='*60}\n")
                return True

        except Exception as e:
            print(f"❌ Email 發送失敗: {str(e)}")
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

        print(f"✅ Email 已發送到 {to_email} (SMTP)")
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

        print(f"✅ Email 已發送到 {to_email} (SES)")
        return True


# 單例
_email_service: Optional[EmailService] = None

def get_email_service() -> EmailService:
    """獲取 Email 服務實例"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
