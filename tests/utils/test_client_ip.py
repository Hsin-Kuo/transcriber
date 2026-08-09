"""src.utils.client_ip.get_client_ip 單元測試（金流體檢 P2-15 附帶修復 4b）。

核心回歸：X-Forwarded-For 可被 client 偽造（append 語意、[0] 不可信），
nginx 對所有 API/auth location 都 proxy_set_header X-Real-IP $remote_addr
（會覆寫 client 自送的同名 header），所以權威來源必須是 X-Real-IP，不是 XFF。

用 unittest.mock 造 request 替身（.headers + .client.host），不起 TestClient。
"""
from unittest.mock import MagicMock

from src.utils.client_ip import get_client_ip
from src.utils.audit_logger import AuditLogger


def _make_request(headers=None, client_host=None):
    request = MagicMock()
    request.headers = headers or {}
    if client_host is None:
        request.client = None
    else:
        request.client = MagicMock()
        request.client.host = client_host
    return request


class TestGetClientIp:
    def test_x_real_ip_present_returns_it_stripped(self):
        request = _make_request(headers={"X-Real-IP": "  5.6.7.8  "}, client_host="9.9.9.9")
        assert get_client_ip(request) == "5.6.7.8"

    def test_no_x_real_ip_falls_back_to_client_host(self):
        """本機開發（無 nginx，沒有 X-Real-IP）走這條路徑。"""
        request = _make_request(headers={}, client_host="127.0.0.1")
        assert get_client_ip(request) == "127.0.0.1"

    def test_request_none_returns_unknown(self):
        assert get_client_ip(None) == "unknown"

    def test_no_x_real_ip_and_no_client_returns_unknown(self):
        request = _make_request(headers={}, client_host=None)
        assert get_client_ip(request) == "unknown"

    def test_forged_xff_is_ignored_when_x_real_ip_present(self):
        """核心回歸測試：漏洞的本體。

        攻擊者送 `X-Forwarded-For: 1.2.3.4`（偽造，塞在 append 鏈最前面），
        但 nginx 已經覆寫 X-Real-IP 為真實來源 `5.6.7.8`。get_client_ip 必須
        回傳 5.6.7.8，絕不能回傳 1.2.3.4——回傳後者代表漏洞沒修好。
        """
        request = _make_request(
            headers={
                "X-Forwarded-For": "1.2.3.4",
                "X-Real-IP": "5.6.7.8",
            },
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "5.6.7.8"

    def test_empty_x_real_ip_falls_back_to_client_host(self):
        request = _make_request(headers={"X-Real-IP": "   "}, client_host="3.3.3.3")
        assert get_client_ip(request) == "3.3.3.3"


class TestAuditLoggerGetClientIpDelegate:
    """AuditLogger.get_client_ip 改 delegate 到 client_ip.get_client_ip 後，
    既有 5 個呼叫端（log_auth/log_task_operation/... 5 處）行為不能變——
    這裡直接驗證 delegate 本身的回傳型別與各分支，不用真的起 repo。"""

    def setup_method(self):
        self.audit_logger = AuditLogger(audit_log_repo=None)

    def test_delegate_prefers_x_real_ip(self):
        request = _make_request(
            headers={"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"},
            client_host="10.0.0.1",
        )
        assert self.audit_logger.get_client_ip(request) == "5.6.7.8"

    def test_delegate_falls_back_to_client_host(self):
        request = _make_request(headers={}, client_host="127.0.0.1")
        assert self.audit_logger.get_client_ip(request) == "127.0.0.1"

    def test_delegate_returns_unknown_when_nothing_available(self):
        request = _make_request(headers={}, client_host=None)
        assert self.audit_logger.get_client_ip(request) == "unknown"
