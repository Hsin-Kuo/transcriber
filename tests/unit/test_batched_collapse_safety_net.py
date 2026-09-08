"""issue #374 緩解：batched 崩壞的輸出保險網（非根治）。

根因在 faster-whisper 1.2.1 的 batched pipeline（我們用的版本，已是最新）：
  - `temperature[:1]`（transcribe.py:528）→ 溫度回退失效
  - `compression_ratio_threshold` 有算（:151）卻只在 sequential 的 fallback
    路徑比對（:1481）→ repetition runaway 毫無攔截
  - segment 時間取自 chunk 內 timestamp token（:1054-1059）→ token 退化就得到
    零長度與塌陷視窗
症狀（staging 0ad21a82 / 06576e12 兩次）：同段音訊輸出兩次，一份時間戳正常、
一份 220~309 段塌在 <0.5 秒（112 段零長度），57 條逐字重複。

本檔測資直接照那兩份 dump 的實際型態構造。
"""
from src.services.utils.whisper_processor import WhisperProcessor


def _proc():
    return WhisperProcessor.__new__(WhisperProcessor)


def _healthy(n=60, start=0.0, step=3.0):
    return [
        {"start": start + i * step, "end": start + i * step + 2.4,
         "text": f"這是第{i}句正常的話。"}
        for i in range(n)
    ]


def _collapsed_copy(texts, at=3565.387):
    """複刻 dump 型態：逐字相同的副本、時長 0~0.001、全塌在同一個視窗。"""
    out = []
    t = at
    for i, text in enumerate(texts):
        end = t if i % 3 == 0 else t + 0.001   # 三分之一是零長度
        out.append({"start": t, "end": end, "text": text})
        t += 0.0015
    return out


# ── 塌陷叢集清理 ────────────────────────────────────────────────────────

def test_collapsed_duplicate_block_is_removed():
    """dump 實際型態：塌陷副本（逐字重複 + 零長度 + 時間被涵蓋）要被清掉。"""
    healthy = _healthy(60)
    collapsed = _collapsed_copy([s["text"] for s in healthy])
    segments = healthy[:30] + collapsed + healthy[30:]

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert len(out) == 60, f"應只剩 60 段正常內容，實際 {len(out)}"
    assert all(s["end"] > s["start"] for s in out), "不得留下零長度段"
    # 內容一條不少
    assert {s["text"] for s in out} == {s["text"] for s in healthy}


def test_zero_duration_segments_are_dropped_even_without_collapse():
    segments = _healthy(10) + [{"start": 100.0, "end": 100.0, "text": "壞段"}]

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert len(out) == 10
    assert "壞段" not in {s["text"] for s in out}


# ── 誤刪防護（最重要）──────────────────────────────────────────────────

def test_normal_task_is_untouched():
    """正常任務必須零改動 passthrough。"""
    segments = _healthy(120)

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert out == segments


def test_legitimate_non_consecutive_short_repeats_are_kept():
    """真實對話裡「對。」「嗯。」本來就會非連續重複——絕不能誤刪。"""
    segments = []
    for i in range(40):
        segments.append({"start": i * 6.0, "end": i * 6.0 + 3.0,
                         "text": f"我覺得這件事情是這樣的第{i}點。"})
        segments.append({"start": i * 6.0 + 3.2, "end": i * 6.0 + 3.9,
                         "text": "對。"})

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert out == segments, "時間正常的重複短句一律保留"
    assert sum(1 for s in out if s["text"] == "對。") == 40


def test_short_repeats_kept_even_when_a_collapse_exists_elsewhere():
    """就算同一份輸出別處有塌陷叢集，正常的「對。」重複仍不得被牽連刪除。"""
    healthy = []
    for i in range(60):
        healthy.append({"start": i * 6.0, "end": i * 6.0 + 3.0,
                        "text": f"正常內容第{i}句。"})
        healthy.append({"start": i * 6.0 + 3.2, "end": i * 6.0 + 3.9,
                        "text": "對。"})
    collapsed = _collapsed_copy([f"正常內容第{i}句。" for i in range(60)])
    segments = healthy + collapsed

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert sum(1 for s in out if s["text"] == "對。") == 60, "正常短句重複被誤刪"
    assert len(out) == len(healthy)


def test_duplicate_with_normal_timestamps_is_kept():
    """時長正常的重複段不算候選——即使落在塌陷視窗附近。"""
    healthy = _healthy(60)
    # 與正常段逐字相同、但時長正常（1.5 秒）→ 必須保留
    legit = {"start": 3565.5, "end": 3567.0, "text": healthy[0]["text"]}
    collapsed = _collapsed_copy([s["text"] for s in healthy[:20]])
    segments = healthy + [legit] + collapsed

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert legit in out, "時長正常的段不得被當成塌陷副本刪掉"


def test_collapsed_segment_without_healthy_twin_is_kept_if_nonzero():
    """塌陷視窗內但沒有正常版本可對應的內容 → 不刪（寧可漏刪不可誤刪）。"""
    healthy = _healthy(60)
    unique = {"start": 3565.4, "end": 3565.5, "text": "這句話只出現在這裡。"}
    collapsed = _collapsed_copy([s["text"] for s in healthy[:20]])
    segments = healthy + [unique] + collapsed

    out = _proc()._sanitize_segments(segments, path="gpu_batched")

    assert unique in out, "沒有正常孿生段的內容不得被刪"


# ── Sentry 接線（patch 自家 wrapper，不 patch sentry_sdk 內部）─────────

def test_collapse_is_reported_to_sentry(monkeypatch):
    calls = []
    import src.services.utils.whisper_processor as wp

    monkeypatch.setattr(
        wp, "capture_message",
        lambda event, level="warning", **ctx: calls.append((event, level, ctx)),
    )

    healthy = _healthy(60)
    segments = healthy + _collapsed_copy([s["text"] for s in healthy])
    _proc()._sanitize_segments(segments, path="gpu_batched")

    assert len(calls) == 1, f"塌陷應送一次 Sentry，實際 {len(calls)}"
    event, level, ctx = calls[0]
    assert event == "whisper.segments.timestamp_collapse"
    assert level == "warning"
    assert ctx["transcribe_path"] == "gpu_batched"
    assert ctx["zero_duration_segments"] > 0
    assert "segments_in_window" in ctx


def test_normal_task_reports_nothing_to_sentry(monkeypatch):
    calls = []
    import src.services.utils.whisper_processor as wp

    monkeypatch.setattr(
        wp, "capture_message",
        lambda event, level="warning", **ctx: calls.append(event),
    )

    _proc()._sanitize_segments(_healthy(120), path="gpu_batched")

    assert calls == [], "正常任務不該送 Sentry"


def test_sentry_failure_does_not_break_transcription(monkeypatch):
    import src.services.utils.whisper_processor as wp

    def boom(*a, **k):
        raise RuntimeError("sentry down")

    monkeypatch.setattr(wp, "capture_message", boom)

    healthy = _healthy(60)
    segments = healthy + _collapsed_copy([s["text"] for s in healthy])

    # 不得拋；Sentry 掛掉時回退成原樣資料也可接受，但絕不能中斷
    out = _proc()._sanitize_segments(segments, path="gpu_batched")
    assert out, "保險網不得回傳空資料"


# ── 純函數行為 ─────────────────────────────────────────────────────────

def test_drop_zero_duration_counts_correctly():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 1.0, "end": 1.0, "text": "b"},
        {"start": 2.0, "end": 1.5, "text": "c"},  # end < start 也要丟
    ]

    kept, dropped = WhisperProcessor._drop_zero_duration_segments(segs)

    assert dropped == 2
    assert [s["text"] for s in kept] == ["a"]


def test_dedupe_is_noop_without_collapse_detection():
    """沒有塌陷叢集時，去重函數根本不該被呼叫——由 _sanitize_segments 保證。"""
    healthy = _healthy(30)
    # 直接呼叫 _sanitize_segments：沒塌陷 → 原樣
    assert _proc()._sanitize_segments(healthy, path="cpu_parallel") == healthy


def test_sanitize_handles_empty_input():
    assert _proc()._sanitize_segments([], path="gpu_batched") == []
