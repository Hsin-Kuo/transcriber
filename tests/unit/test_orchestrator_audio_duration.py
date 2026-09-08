"""音檔時長解析不得 fail-open（PR #381 review Blocker 2）。

路由靠 `stats.audio_duration_seconds` 決定 batched/sequential。但有兩條實際會
發生的路徑會讓它變成 0/None：
  1. intake 的 probe 失敗回 0（例如 MediaRecorder 產生的 webm 沒有
     format.duration），intake 端沒有 <=0 守門
  2. `_get_task` 把 Mongo 例外吞掉回 None
任一發生時若直接傳 None，90 分鐘的檔就會靜默走回會塌的 batched，路由等於白做。
所以要退一步用本地 ffprobe（mp3 就在本機磁碟，很便宜），且回退原因要可觀測。
"""
from pathlib import Path

from src.transcription.orchestrator import TranscriptionOrchestrator


class FakeWhisper:
    """`_get_audio_duration` 回傳**毫秒**（正式實作如此，換算錯就會差 1000 倍）。"""

    def __init__(self, duration_ms=None, boom=False):
        self.duration_ms = duration_ms
        self.boom = boom
        self.calls = 0

    def _get_audio_duration(self, path):
        self.calls += 1
        if self.boom:
            raise RuntimeError("ffprobe failed")
        return self.duration_ms


def _orch(task_doc, whisper):
    o = TranscriptionOrchestrator.__new__(TranscriptionOrchestrator)
    o.whisper = whisper
    o._get_task = lambda task_id, projection=None: task_doc
    return o


MP3 = Path("/tmp/dummy.mp3")


# ── DB 有值就用 DB ─────────────────────────────────────────────────────

def test_uses_db_duration_when_present():
    w = FakeWhisper(duration_ms=999_000)
    o = _orch({"stats": {"audio_duration_seconds": 5396.5}}, w)

    assert o._resolve_audio_duration("t1", MP3) == 5396.5
    assert w.calls == 0, "DB 有值時不該再 probe 音檔"


# ── DB 缺值 → 本地 ffprobe 回退 ────────────────────────────────────────

def test_falls_back_to_local_probe_when_db_zero():
    """intake probe 失敗寫 0（webm 缺 format.duration）→ 必須回退。"""
    w = FakeWhisper(duration_ms=5_396_544)
    o = _orch({"stats": {"audio_duration_seconds": 0}}, w)

    got = o._resolve_audio_duration("t1", MP3)

    assert w.calls == 1
    assert got == 5396.544, "毫秒要除 1000"


def test_falls_back_when_db_field_missing():
    w = FakeWhisper(duration_ms=600_000)
    o = _orch({"stats": {}}, w)

    assert o._resolve_audio_duration("t1", MP3) == 600.0


def test_falls_back_when_task_fetch_returns_none():
    """`_get_task` 吞掉 Mongo 例外回 None → 必須回退，不能傳 None 讓長檔走 batched。"""
    w = FakeWhisper(duration_ms=5_396_544)
    o = _orch(None, w)

    assert o._resolve_audio_duration("t1", MP3) == 5396.544


def test_falls_back_when_db_value_is_non_numeric():
    w = FakeWhisper(duration_ms=120_000)
    o = _orch({"stats": {"audio_duration_seconds": "not-a-number"}}, w)

    assert o._resolve_audio_duration("t1", MP3) == 120.0


# ── 回退也失敗 → 老實回 None ──────────────────────────────────────────

def test_returns_none_when_probe_raises():
    w = FakeWhisper(boom=True)
    o = _orch(None, w)

    assert o._resolve_audio_duration("t1", MP3) is None


def test_returns_none_when_probe_also_zero():
    w = FakeWhisper(duration_ms=0)
    o = _orch(None, w)

    assert o._resolve_audio_duration("t1", MP3) is None


# ── 回退原因要可觀測 ───────────────────────────────────────────────────

def test_fallback_logs_distinct_reason(monkeypatch):
    import src.transcription.orchestrator as mod

    infos = []
    monkeypatch.setattr(mod.log, "info", lambda event, **kw: infos.append((event, kw)))

    w = FakeWhisper(duration_ms=5_396_544)
    _orch({"stats": {"audio_duration_seconds": 0}}, w)._resolve_audio_duration("t1", MP3)

    events = [e for e, _ in infos]
    assert "transcription.audio_duration.local_probe_fallback" in events
    kw = dict(infos[[e for e, _ in infos].index(
        "transcription.audio_duration.local_probe_fallback")][1])
    assert kw["reason"] == "db_missing_or_nonpositive"
    assert kw["audio_duration_seconds"] == 5396.544


def test_total_failure_logs_distinct_reason(monkeypatch):
    import src.transcription.orchestrator as mod

    warns = []
    monkeypatch.setattr(mod.log, "warning", lambda event, **kw: warns.append((event, kw)))

    _orch(None, FakeWhisper(duration_ms=0))._resolve_audio_duration("t1", MP3)

    events = [e for e, _ in warns]
    assert "transcription.audio_duration.unavailable" in events


def test_probe_exception_logs_distinct_reason(monkeypatch):
    import src.transcription.orchestrator as mod

    warns = []
    monkeypatch.setattr(mod.log, "warning", lambda event, **kw: warns.append((event, kw)))

    _orch(None, FakeWhisper(boom=True))._resolve_audio_duration("t1", MP3)

    assert "transcription.audio_duration.fallback_failed" in [e for e, _ in warns]


# ── _task_audio_duration 純函數 ───────────────────────────────────────

def test_task_audio_duration_normalizes_bad_values():
    o = TranscriptionOrchestrator.__new__(TranscriptionOrchestrator)

    assert o._task_audio_duration({"stats": {"audio_duration_seconds": 12.5}}) == 12.5
    assert o._task_audio_duration({"stats": {"audio_duration_seconds": 0}}) is None
    assert o._task_audio_duration({"stats": {"audio_duration_seconds": -5}}) is None
    assert o._task_audio_duration({"stats": {"audio_duration_seconds": None}}) is None
    assert o._task_audio_duration({"stats": {}}) is None
    assert o._task_audio_duration({}) is None
    assert o._task_audio_duration(None) is None


def test_projection_is_used_to_avoid_full_document_read():
    """review #8：不必為了一個數字把整份任務文件拉回來。"""
    seen = {}
    o = TranscriptionOrchestrator.__new__(TranscriptionOrchestrator)
    o.whisper = FakeWhisper(duration_ms=1000)

    def fake_get(task_id, projection=None):
        seen["projection"] = projection
        return {"stats": {"audio_duration_seconds": 60.0}}

    o._get_task = fake_get
    o._resolve_audio_duration("t1", MP3)

    assert seen["projection"] == {"stats.audio_duration_seconds": 1}
