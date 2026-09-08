"""長音檔自動走 sequential 的路由（issue #374 止血）。

A/B 實證（staging 同一支 89.9 分鐘 zh 音檔）：
  batched    塌陷 310/221 段、零長度 112/53、逐字重複 57/25，處理 482s/486s
  sequential 塌陷 3 段、零長度 0、重複 0，處理 1275s（2.64 倍）
根因：batched 的 repetition 安全網失效（`temperature[:1]` +
`compression_ratio_threshold` 只在 sequential 的 fallback 路徑比對）。
"""
import src.services.utils.whisper_processor as wp
from src.services.utils.whisper_processor import WhisperProcessor


def _proc():
    return WhisperProcessor.__new__(WhisperProcessor)


# 刻意不用 importlib.reload：reload 會把改過的 module 層常數留在整個 pytest
# process 裡污染其他測試（而且被 reload 的 class 與已 import 的不是同一個物件）。
# 直接 monkeypatch 常數，pytest 會自動還原。


# ── 門檻上下的路由 ──────────────────────────────────────────────────────

def test_short_audio_uses_batched():
    proc = _proc()
    # 預設門檻 30 分鐘；10 分鐘 → batched
    assert proc._should_use_batched(10 * 60) is True


def test_long_audio_uses_sequential():
    proc = _proc()
    # 89.9 分鐘（實測會觸發崩壞的長度）→ sequential
    assert proc._should_use_batched(5396.5) is False


def test_exactly_at_threshold_uses_sequential():
    """門檻是 `>=`，剛好等於門檻走安全側。"""
    proc = _proc()
    assert proc._should_use_batched(30 * 60) is False


def test_just_below_threshold_uses_batched():
    proc = _proc()
    assert proc._should_use_batched(30 * 60 - 1) is True


# ── 缺資料時維持現狀 ────────────────────────────────────────────────────

def test_unknown_duration_keeps_batched():
    """拿不到時長不該讓所有任務都變慢 2.64 倍。"""
    proc = _proc()
    assert proc._should_use_batched(None) is True
    assert proc._should_use_batched(0) is True
    assert proc._should_use_batched(-1) is True


# ── env 覆寫 ────────────────────────────────────────────────────────────

def test_threshold_override_lowers_bar(monkeypatch):
    monkeypatch.setattr(wp, "_SEQUENTIAL_MIN_MINUTES", 5.0)
    proc = _proc()

    assert proc._should_use_batched(10 * 60) is False  # 10 分鐘 >= 5
    assert proc._should_use_batched(2 * 60) is True


def test_threshold_zero_forces_sequential(monkeypatch):
    monkeypatch.setattr(wp, "_SEQUENTIAL_MIN_MINUTES", 0.0)
    proc = _proc()

    assert proc._should_use_batched(60) is False
    assert proc._should_use_batched(None) is False


def test_huge_threshold_preserves_current_behaviour(monkeypatch):
    """極大值＝維持現狀（全走 batched）。"""
    monkeypatch.setattr(wp, "_SEQUENTIAL_MIN_MINUTES", 999999.0)

    assert _proc()._should_use_batched(5396.5) is True


def test_global_switch_off_beats_threshold(monkeypatch):
    """`WHISPER_BATCHED=false` 是總開關，優先於門檻。"""
    monkeypatch.setattr(wp, "_USE_BATCHED", False)
    monkeypatch.setattr(wp, "_SEQUENTIAL_MIN_MINUTES", 999999.0)
    proc = _proc()

    assert proc._should_use_batched(60) is False
    assert proc._should_use_batched(None) is False


def test_default_threshold_is_thirty_minutes():
    """預設值有證據依據：89.9 分實測會觸發、7 分不會，中間無資料 → 取安全側。"""
    assert wp._SEQUENTIAL_MIN_MINUTES == 30


# ── 路由決策要留下 log ─────────────────────────────────────────────────

def test_route_decision_is_logged(monkeypatch):
    events = []
    monkeypatch.setattr(
        wp.log, "info",
        lambda event, **kw: events.append((event, kw)),
    )

    _proc()._should_use_batched(5396.5)

    assert events, "路由決策必須記 log"
    event, kw = events[-1]
    assert event == "whisper.route"
    assert kw["path"] == "sequential"
    assert kw["reason"] == "long_audio"
    assert kw["audio_duration_seconds"] == 5396.5
    assert kw["threshold_minutes"] == 30


def test_route_log_records_short_audio_reason(monkeypatch):
    events = []
    monkeypatch.setattr(wp.log, "info", lambda event, **kw: events.append((event, kw)))

    _proc()._should_use_batched(120)

    assert events[-1][1]["path"] == "batched"
    assert events[-1][1]["reason"] == "short_audio"


# ── 端到端：duration 有被傳到路由 ──────────────────────────────────────

def test_transcribe_in_chunks_passes_duration_to_router():
    proc = _proc()
    seen = {}

    proc._has_gpu = lambda: True
    proc._ensure_valid_audio = lambda p: p

    def fake_twt(audio_path, language=None, progress_callback=None,
                 audio_duration_seconds=None):
        seen["duration"] = audio_duration_seconds
        return [{"start": 0.0, "end": 1.0, "text": "x"}], "zh"

    proc._transcribe_with_timestamps = fake_twt

    proc.transcribe_in_chunks("dummy.mp3", audio_duration_seconds=5396.5)

    assert seen["duration"] == 5396.5, "時長沒被傳到路由決策"


def test_transcribe_single_entry_passes_duration_to_router():
    proc = _proc()
    seen = {}

    proc._ensure_valid_audio = lambda p: p

    def fake_twt(audio_path, language=None, progress_callback=None,
                 audio_duration_seconds=None):
        seen["duration"] = audio_duration_seconds
        return [{"start": 0.0, "end": 1.0, "text": "x"}], "zh"

    proc._transcribe_with_timestamps = fake_twt

    proc.transcribe("dummy.mp3", audio_duration_seconds=1234.0)

    assert seen["duration"] == 1234.0


# ── env 解析防護（review #3）─────────────────────────────────────────────

def test_invalid_threshold_env_falls_back_to_default(monkeypatch):
    """壞值不能讓 import 期 float() 爆掉——這個模組被 web app import，
    import 期例外會造成 crash-loop。"""
    monkeypatch.setenv("WHISPER_SEQUENTIAL_MIN_MINUTES", "abc")
    assert wp._parse_sequential_min_minutes() == 30.0

    monkeypatch.setenv("WHISPER_SEQUENTIAL_MIN_MINUTES", "")
    assert wp._parse_sequential_min_minutes() == 30.0

    monkeypatch.delenv("WHISPER_SEQUENTIAL_MIN_MINUTES", raising=False)
    assert wp._parse_sequential_min_minutes() == 30.0


def test_nan_and_inf_threshold_rejected(monkeypatch):
    """`float('nan')` 合法但會讓所有比較變 False → 門檻靜默失效且記錯 reason。"""
    for bad in ("nan", "NaN", "inf", "-inf"):
        monkeypatch.setenv("WHISPER_SEQUENTIAL_MIN_MINUTES", bad)
        assert wp._parse_sequential_min_minutes() == 30.0, bad


def test_valid_threshold_env_is_parsed(monkeypatch):
    monkeypatch.setenv("WHISPER_SEQUENTIAL_MIN_MINUTES", "12.5")
    assert wp._parse_sequential_min_minutes() == 12.5


# ── GPU 偵測不得吃掉遙測（review #5）───────────────────────────────────

def test_no_gpu_still_emits_route_log(monkeypatch):
    """GPU 掛掉時也要有 route log，否則 on-call 分不出
    「GPU 死了」還是「門檻路由」。"""
    events = []
    monkeypatch.setattr(wp.log, "info", lambda event, **kw: events.append((event, kw)))
    monkeypatch.setattr(wp.log, "debug", lambda *a, **k: None)

    proc = _proc()
    proc._has_gpu = lambda: False
    proc._sanitize_segments = lambda segments, path: segments

    class FakeInfo:
        language = "zh"
        duration = 60.0

    class FakeModel:
        def transcribe(self, *a, **k):
            return [], FakeInfo()

    proc.model = FakeModel()
    proc._transcribe_with_timestamps("dummy.mp3", "zh", audio_duration_seconds=60.0)

    routes = [kw for ev, kw in events if ev == "whisper.route"]
    assert routes, "無 GPU 時仍必須記 route log"
    assert routes[-1]["reason"] == "no_gpu"
    assert routes[-1]["path"] == "sequential"


def test_gpu_detect_failure_is_logged(monkeypatch):
    """`_has_gpu` 靜默回 False 會讓「偵測壞了」看起來像「這台沒 GPU」。"""
    warnings = []
    monkeypatch.setattr(wp.log, "warning", lambda event, **kw: warnings.append(event))

    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "torch":
            raise RuntimeError("torch broken")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)

    assert _proc()._has_gpu() is False
    assert "whisper.gpu_detect_failed" in warnings
