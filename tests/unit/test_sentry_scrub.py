"""Sentry 遮蔽測試：before_send 必須擋住 request/extra/contexts 之外，
也要擋住例外堆疊 frame locals 裡的巢狀憑證（如 SmilePay Verify_key）。"""
from src.utils.sentry_init import _before_send, _before_breadcrumb


def _event_with_frame_vars(local_vars):
    return {
        "exception": {
            "values": [
                {
                    "type": "ConnectError",
                    "stacktrace": {
                        "frames": [
                            {"function": "_post", "vars": local_vars},
                        ]
                    },
                }
            ]
        }
    }


class TestBeforeSendFrameVars:
    def test_nested_verify_key_in_frame_vars_is_filtered(self):
        event = _event_with_frame_vars(
            {"body": {"Grvc": "SEI1004730", "Verify_key": "SUPERSECRET"}, "url": "https://x"}
        )
        out = _before_send(event, {})
        frame_vars = out["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["body"]["Verify_key"] == "[FILTERED]"
        assert frame_vars["body"]["Grvc"] == "SEI1004730"  # 非敏感欄位不動
        assert frame_vars["url"] == "https://x"

    def test_threads_section_also_scrubbed(self):
        event = {"threads": _event_with_frame_vars({"api_key_1": "zzz"})["exception"]}
        out = _before_send(event, {})
        frame_vars = out["threads"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["api_key_1"] == "[FILTERED]"

    def test_frames_without_vars_and_missing_stacktrace_survive(self):
        event = {
            "exception": {
                "values": [
                    {"type": "X"},  # 無 stacktrace
                    {"type": "Y", "stacktrace": {"frames": [{"function": "f"}]}},  # 無 vars
                ]
            }
        }
        out = _before_send(event, {})  # 不得 raise
        assert out["exception"]["values"][1]["stacktrace"]["frames"][0] == {"function": "f"}

    def test_request_extra_contexts_still_scrubbed(self):
        event = {"extra": {"smilepay_verify_key": "zzz"}, "request": {"headers": {"Cookie": "a=b"}}}
        out = _before_send(event, {})
        assert out["extra"]["smilepay_verify_key"] == "[FILTERED]"
        assert out["request"]["headers"]["Cookie"] == "[FILTERED]"


class TestBeforeBreadcrumb:
    def test_breadcrumb_data_scrubbed(self):
        crumb = {"data": {"body": {"Verify_key": "zzz"}}}
        out = _before_breadcrumb(crumb, {})
        assert out["data"]["body"]["Verify_key"] == "[FILTERED]"
