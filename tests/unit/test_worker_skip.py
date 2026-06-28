"""worker_core.transcription_job._should_skip 純函數測試。

驗證 worker 收到 SQS 訊息後「該不該處理」的守衛——無副作用、不碰 SQS / DB。
重點:軟刪除(deleted=True)的任務不分 status 一律跳過,避免去 S3 抓已被刪除的音檔。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.worker_core.transcription_job import _should_skip  # noqa: E402


class TestShouldSkip:
    def test_no_doc_does_not_skip(self):
        # 找不到 task(None):不跳過,交由後續流程處理/報錯
        assert _should_skip(None) is False

    @pytest.mark.parametrize("status", ["completed", "canceling", "cancelled"])
    def test_terminal_status_skips(self, status):
        assert _should_skip({"status": status}) is True

    @pytest.mark.parametrize("status", ["pending", "processing", "failed"])
    def test_active_or_failed_status_not_skipped(self, status):
        assert _should_skip({"status": status}) is False

    @pytest.mark.parametrize("status", ["pending", "processing", "failed", "completed"])
    def test_deleted_always_skips_regardless_of_status(self, status):
        # 缺口 #1 回歸:軟刪除任務即使 status 不在終態清單,也必須跳過——
        # 否則 worker 會把已刪任務復活成 processing、去抓已物理刪除的音檔。
        assert _should_skip({"status": status, "deleted": True}) is True

    def test_deleted_false_falls_back_to_status(self):
        assert _should_skip({"status": "pending", "deleted": False}) is False
