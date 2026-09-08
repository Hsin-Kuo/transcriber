"""issue #374：chunk 切點規劃與時間戳塌陷防護。

根因：`_find_silence_near` 把 ffmpeg silencedetect 的**絕對**時間當成相對於 `-ss`
的值又加了一次 search_start，切點被加倍（≈ 2×target − 30s）。實測 ffmpeg 7：
檔案 43s、靜音 20~23s，
  `-i f -ss 15 -t 30` → silence_start: 19.999（絕對）
  `-ss 15 -t 30 -i f` → silence_start:  4.999（相對）
程式用的是前者。

後果：90 分鐘音檔設定 10 分鐘一段，實際只切出 3 段（19.5/39/30.5 分鐘）。
超長 chunk 讓 faster-whisper 時間戳對齊崩壞——staging 任務 0ad21a82 出現
309 個 segment 全塌在 0.25 秒內（112 個長度為 0），文字是整份逐字稿的重複。
"""
from unittest.mock import patch

from src.services.utils.whisper_processor import WhisperProcessor, _apply_time_offset

TOTAL_MS = 5_396_544   # staging 任務的實際音檔長度（89.9 分鐘）
CHUNK_MS = 600_000     # chunk_minutes=10


def _plan(find_silence, total=TOTAL_MS, chunk=CHUNK_MS):
    return WhisperProcessor._plan_cut_points(total, chunk, find_silence)


def _gaps(boundaries):
    """相鄰邊界的長度（不用 zip：repo 慣例避開 zip(strict=)，dev venv 是 3.9）。"""
    return [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]


# ── 切點規劃不變式 ──────────────────────────────────────────────────────

def test_normal_silence_detection_gives_evenly_spaced_cuts():
    # 靜音剛好落在目標切點附近（±2 秒）
    cuts = _plan(lambda target: target + 2000)

    assert cuts, "應該要有切點"
    assert cuts == sorted(cuts), "必須遞增"
    assert all(c < TOTAL_MS for c in cuts), "不得超過音檔長度"
    # 90 分鐘 / 10 分鐘 → 8 個內部切點（9 段）
    assert len(cuts) == 8, f"預期 8 個切點，實際 {len(cuts)}"


def test_doubling_bug_pattern_is_rejected():
    """回歸測試：即使靜音偵測回傳「加倍」的壞值，切點也不能失控。"""
    def buggy(target):
        # 複製舊 bug 的行為：把絕對時間又加了 search_start（target-30s）
        search_start = max(0, target - 30_000)
        return target + search_start

    cuts = _plan(buggy)

    assert cuts == sorted(set(cuts)), "必須嚴格遞增且不重複"
    assert all(0 < c < TOTAL_MS for c in cuts), f"切點必須在音檔範圍內: {cuts}"
    # 壞值被拒絕後退回目標切點 → 仍應切出接近 8 段
    assert len(cuts) == 8, f"預期退回目標切點得到 8 個，實際 {len(cuts)}"
    gaps = _gaps([0] + cuts + [TOTAL_MS])
    assert all(g > 0 for g in gaps), f"不得有零/負長度的 chunk: {gaps}"
    assert max(gaps) <= CHUNK_MS * 2, (
        f"沒有 chunk 該長到失控（超長 chunk 會觸發時間戳崩壞）: {max(gaps)}"
    )


def test_cut_points_beyond_audio_are_rejected():
    cuts = _plan(lambda target: TOTAL_MS + 1_000_000)

    assert all(c < TOTAL_MS for c in cuts)
    assert cuts == sorted(set(cuts))


def test_backwards_silence_result_cannot_break_monotonicity():
    """靜音偵測回傳比前一個切點更早的位置 → 不得產生非遞增或負長度 chunk。"""
    cuts = _plan(lambda target: 1000)

    assert cuts == sorted(set(cuts))
    assert all(0 < c < TOTAL_MS for c in cuts)
    gaps = _gaps([0] + cuts + [TOTAL_MS])
    assert all(g > 0 for g in gaps), f"不得有零/負長度 chunk: {gaps}"


def test_oversized_chunk_is_rejected():
    """關鍵防護：切點不得讓 chunk 長度失控——超長 chunk 正是崩壞的觸發條件。"""
    # 靜音一直回報「比目標再遠 20 分鐘」
    cuts = _plan(lambda target: target + CHUNK_MS * 2)

    boundaries = [0] + cuts + [TOTAL_MS]
    gaps = _gaps(boundaries)
    assert max(gaps) <= CHUNK_MS * 1.5 + 1, f"chunk 長度失控: {max(gaps)}"


def test_minimum_gap_between_cuts_is_enforced():
    # 靜音一直回報「就在前一個切點旁邊」
    cuts = _plan(lambda target: target - CHUNK_MS + 500)

    min_gap = int(CHUNK_MS * 0.2)
    boundaries = [0] + cuts + [TOTAL_MS]
    for gap in _gaps(boundaries):
        assert gap >= min(min_gap, TOTAL_MS), f"chunk 過短: {gap}"


def test_short_audio_produces_no_cuts():
    assert _plan(lambda t: t, total=300_000) == []


# ── _find_silence_near：絕對時間不得再加 search_start ──────────────────

def _ffmpeg_stderr(silence_start_s, silence_end_s):
    return (
        f"[silencedetect @ 0x1] silence_start: {silence_start_s}\n"
        f"[silencedetect @ 0x1] silence_end: {silence_end_s} | "
        f"silence_duration: {silence_end_s - silence_start_s}\n"
    )


def test_silence_times_are_treated_as_absolute():
    """`-ss` 在 `-i` 之後 → silencedetect 報絕對時間，不可再加 search_start。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)

    class R:
        stderr = _ffmpeg_stderr(600.0, 601.0)

    with patch("subprocess.run", return_value=R()):
        got = proc._find_silence_near("dummy.mp3", 600_000)

    # 靜音中點 600.5s；舊 bug 會回 600.5 + 570 = 1170.5s
    assert abs(got - 600_500) < 50, f"應為 ~600500ms（絕對），實際 {got}"


def test_out_of_window_silence_result_falls_back_to_target():
    """解析結果落在搜尋窗口外 → 退回目標切點（就是舊 bug 的形態）。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)

    class R:
        stderr = _ffmpeg_stderr(1170.0, 1171.0)  # 遠在 ±30s 窗口之外

    with patch("subprocess.run", return_value=R()):
        got = proc._find_silence_near("dummy.mp3", 600_000)

    assert got == 600_000


def test_no_silence_found_returns_target():
    proc = WhisperProcessor.__new__(WhisperProcessor)

    class R:
        stderr = "no silence here"

    with patch("subprocess.run", return_value=R()):
        assert proc._find_silence_near("dummy.mp3", 600_000) == 600_000


# ── offset 套用與順序 ───────────────────────────────────────────────────

def test_apply_time_offset_preserves_relative_spacing_and_words():
    seg = {
        "start": 1.0, "end": 3.5, "text": "hi",
        "words": [{"start": 1.0, "end": 2.0, "word": "hi"}],
    }

    out = _apply_time_offset(seg, 600.0)

    assert out["start"] == 601.0
    assert out["end"] == 603.5
    assert out["end"] - out["start"] == seg["end"] - seg["start"]
    assert out["words"][0]["start"] == 601.0
    assert out["words"][0]["end"] == 602.0
    assert out["text"] == "hi"
    # 原 segment 不被就地修改
    assert seg["start"] == 1.0


def test_offsets_map_to_chunk_order():
    """chunk 順序 → offset 對應：第 n 段套第 n 個切點起始秒數。"""
    boundaries = [0, 600, 1200, 1800]
    per_chunk = [[{"start": 0.5, "end": 1.0, "text": f"c{i}"}] for i in range(3)]

    merged = []
    for idx, segs in enumerate(per_chunk):
        for s in segs:
            merged.append(_apply_time_offset(s, boundaries[idx]))

    assert [m["start"] for m in merged] == [0.5, 600.5, 1200.5]
    assert [m["start"] for m in merged] == sorted(m["start"] for m in merged)


# ── 時間戳塌陷偵測 ─────────────────────────────────────────────────────

def test_detects_timestamp_collapse():
    """重建 issue #374 的病徵：309 個 segment 塌在同一秒。"""
    healthy = [{"start": float(i * 3), "end": float(i * 3 + 2)} for i in range(100)]
    collapsed = [{"start": 3565.6, "end": 3565.6} for _ in range(309)]

    got = WhisperProcessor._detect_timestamp_collapse(healthy + collapsed)

    assert got is not None
    second, count = got
    assert second == 3565
    assert count == 309


def test_healthy_segments_report_no_collapse():
    healthy = [{"start": float(i * 3), "end": float(i * 3 + 2)} for i in range(500)]

    assert WhisperProcessor._detect_timestamp_collapse(healthy) is None


def test_collapse_detection_handles_empty_input():
    assert WhisperProcessor._detect_timestamp_collapse([]) is None
