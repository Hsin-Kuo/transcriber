"""Worker 重複處理防護（PR #381 review Blocker 1）。

問題：`SQS_VISIBILITY_TIMEOUT_SECONDS` 是 600 秒，但單顆任務可以跑更久
（89.9 分鐘音檔 sequential 實測轉錄 1275 秒）。visibility 一到期 SQS 就把同一則
訊息重投給另一個 worker，同一顆任務被處理兩次——GPU/Gemini 雙重花費、進度交錯、
結果 last-writer-wins，最多重複 maxReceiveCount 次。

**這個風險本來就存在**（90 分鐘音檔一直都會踩到）；「長音檔自動走 sequential」
把觸發點從 ~90 分鐘拉低到 ~40 分鐘的常見尺寸，所以必須一起修。

兩道防線：
  1. visibility 續命背景執行緒 → 讓重投不要發生
  2. processing 的原子 claim → 重投真的發生時擋住第二個 worker
"""
from src.worker_core import state, visibility_extender
from src.worker_core.config import (
    PROCESSING_CLAIM_STALE_SECONDS,
    SQS_VISIBILITY_TIMEOUT_SECONDS,
)
from src.worker_core.transcription_job import _claim_task
from src.utils.time_utils import get_utc_timestamp


class FakeTasks:
    """只實作 find_one_and_update 的 conditional 語意（$or / $ne / $lt / $exists）。"""

    def __init__(self, doc):
        self.doc = doc

    def _matches(self, query):
        if query.get("_id") != self.doc.get("_id"):
            return False
        for clause in query.get("$or", []):
            if self._clause_matches(clause):
                return True
        return "$or" not in query

    def _clause_matches(self, clause):
        for field, cond in clause.items():
            value = self._get(field)
            if isinstance(cond, dict):
                if "$ne" in cond and value != cond["$ne"]:
                    return True
                if "$lt" in cond and value is not None and value < cond["$lt"]:
                    return True
                if "$exists" in cond and (value is not None) == cond["$exists"]:
                    return True
            elif value == cond:
                return True
        return False

    def _get(self, dotted):
        cur = self.doc
        for part in dotted.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def find_one_and_update(self, query, update, return_document=None):
        if not self._matches(query):
            return None
        self.doc.update(update["$set"])
        return dict(self.doc)


class FakeDb:
    def __init__(self, doc):
        self.tasks = FakeTasks(doc)


# ── 原子 claim ──────────────────────────────────────────────────────────

def test_pending_task_can_be_claimed():
    db = FakeDb({"_id": "t1", "status": "pending"})

    assert _claim_task(db, "t1") is True
    assert db.tasks.doc["status"] == "processing"
    assert db.tasks.doc["processing_claim"]["worker_id"]


def test_second_delivery_of_active_task_is_rejected():
    """核心情境：visibility 到期重投，第二個 worker 必須搶不到。"""
    db = FakeDb({"_id": "t1", "status": "pending"})
    assert _claim_task(db, "t1") is True          # worker A 搶到

    assert _claim_task(db, "t1") is False, "重投時第二個 worker 不得搶到同一顆任務"


def test_stale_claim_can_be_taken_over():
    """前一個 worker 掉了 → claim 過期 → 必須能被接手，否則永久卡 processing。"""
    old = get_utc_timestamp() - PROCESSING_CLAIM_STALE_SECONDS - 60
    db = FakeDb({
        "_id": "t1",
        "status": "processing",
        "processing_claim": {"worker_id": "dead-worker", "claimed_at": old},
    })

    assert _claim_task(db, "t1") is True
    assert db.tasks.doc["processing_claim"]["worker_id"] != "dead-worker"


def test_processing_without_claim_record_can_be_claimed():
    """舊資料（上一版寫的 processing，沒有 claim 欄位）不得被永久鎖死。"""
    db = FakeDb({"_id": "t1", "status": "processing"})

    assert _claim_task(db, "t1") is True


def test_fresh_claim_blocks_takeover():
    fresh = get_utc_timestamp()
    db = FakeDb({
        "_id": "t1",
        "status": "processing",
        "processing_claim": {"worker_id": "worker-a", "claimed_at": fresh},
    })

    assert _claim_task(db, "t1") is False
    assert db.tasks.doc["processing_claim"]["worker_id"] == "worker-a"


# ── visibility 續命 ────────────────────────────────────────────────────

class FakeSqs:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def change_message_visibility(self, **kwargs):
        if self.fail:
            raise RuntimeError("sqs down")
        self.calls.append(kwargs)


def _set_state(task_id="t1", receipt="rh-1", queue="https://q", spot=False):
    state.current_task_id = task_id
    state.current_receipt_handle = receipt
    state.current_queue_url = queue
    state.spot_interruption_detected = spot


def _clear_state():
    state.current_task_id = None
    state.current_receipt_handle = None
    state.current_queue_url = None
    state.spot_interruption_detected = False


def test_visibility_is_extended_for_inflight_message():
    _set_state()
    sqs = FakeSqs()
    try:
        assert visibility_extender.extend_once(sqs) is True
    finally:
        _clear_state()

    assert len(sqs.calls) == 1
    call = sqs.calls[0]
    assert call["ReceiptHandle"] == "rh-1"
    assert call["QueueUrl"] == "https://q"
    assert call["VisibilityTimeout"] == SQS_VISIBILITY_TIMEOUT_SECONDS


def test_no_extension_without_inflight_message():
    _clear_state()
    sqs = FakeSqs()

    assert visibility_extender.extend_once(sqs) is False
    assert sqs.calls == []


def test_no_extension_during_spot_interruption():
    """Spot 中斷時 SpotMonitor 剛把 visibility 縮短，不能又推回去。"""
    _set_state(spot=True)
    sqs = FakeSqs()
    try:
        assert visibility_extender.extend_once(sqs) is False
    finally:
        _clear_state()

    assert sqs.calls == []


def test_extension_failure_does_not_raise():
    """續命失敗最壞只是訊息被重投，而重投有原子 claim 接住——絕不能中斷轉錄。"""
    _set_state()
    sqs = FakeSqs(fail=True)
    try:
        assert visibility_extender.extend_once(sqs) is False
    finally:
        _clear_state()


def test_heartbeat_interval_is_shorter_than_timeout():
    """續命間隔必須明顯短於 timeout，否則來不及續就到期了。"""
    from src.worker_core.config import SQS_VISIBILITY_HEARTBEAT_SECONDS

    assert SQS_VISIBILITY_HEARTBEAT_SECONDS < SQS_VISIBILITY_TIMEOUT_SECONDS / 2
