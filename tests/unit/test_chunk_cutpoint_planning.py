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


def test_input_seeking_times_are_relative_and_offset_is_added_back():
    """`-ss` 在 `-i` **之前**（input seeking）→ silencedetect 報相對時間，須加回
    search_start。這是原 bug 的鏡像，用實測值鎖住換算式。

    實測（ffmpeg 7；檔案 164s、靜音 100~104s、target=100s、窗口起點 70s）：
      `-ss 70 -t 60 -i f` → silence_start: 29.999（相對）← 現在用這個
      `-i f -ss 70 -t 60` → silence_start: 99.999（絕對）← 舊版用這個
    """
    proc = WhisperProcessor.__new__(WhisperProcessor)
    # target=600s → 窗口起點 570s；真實靜音 600~601s → 相對值 30~31
    class R:
        stderr = _ffmpeg_stderr(30.0, 31.0)

    with patch("subprocess.run", return_value=R()):
        got = proc._find_silence_near("dummy.mp3", 600_000)

    assert abs(got - 600_500) < 50, f"應為 ~600500ms（30.5+570），實際 {got}"


def test_input_seeking_command_puts_ss_before_input():
    """順序錯了就會回到 output seeking（絕對時間），換算式隨之失效。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)

    class R:
        stderr = ""

    with patch("subprocess.run", return_value=R()) as run:
        proc._find_silence_near("dummy.mp3", 600_000)

    argv = run.call_args[0][0]
    assert argv.index("-ss") < argv.index("-i"), f"-ss 必須在 -i 之前: {argv}"
    assert argv.index("-t") < argv.index("-i"), f"-t 必須在 -i 之前: {argv}"


def test_candidate_entirely_outside_window_is_discarded():
    """解析值完全落在窗口外（舊 bug 的形態）→ 丟掉候選、退回目標切點。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)
    # 相對值 600 → 絕對 1170s，遠在 570~630s 窗口之外
    class R:
        stderr = _ffmpeg_stderr(600.0, 601.0)

    with patch("subprocess.run", return_value=R()):
        got = proc._find_silence_near("dummy.mp3", 600_000)

    assert got == 600_000


def test_long_silence_extending_past_window_is_clipped_not_rejected():
    """65 秒中場休息只被窗口截到一半 → 夾回窗口取中點，不得誤拒。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)
    # 窗口 570~630s；靜音相對 20~85（絕對 590~655）延伸出窗口右界
    class R:
        stderr = _ffmpeg_stderr(20.0, 85.0)

    with patch("subprocess.run", return_value=R()):
        got = proc._find_silence_near("dummy.mp3", 600_000)

    assert got != 600_000, "不該退回目標切點（那代表被誤拒）"
    assert 590_000 <= got <= 630_000, f"應夾在窗口內，實際 {got}"


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
    assert got["segments_in_window"] == 309
    assert got["zero_duration_segments"] == 309
    assert got["total_segments"] == 409


def test_healthy_segments_report_no_collapse():
    healthy = [{"start": float(i * 3), "end": float(i * 3 + 2)} for i in range(500)]

    assert WhisperProcessor._detect_timestamp_collapse(healthy) is None


def test_collapse_detection_handles_empty_input():
    assert WhisperProcessor._detect_timestamp_collapse([]) is None


# ── code review 回歸測試 ─────────────────────────────────────────────────

PROD_CHUNK_MS = 1_500_000  # 生產預設 25 分鐘（whisper_processor.py 的 default）


def test_short_tail_merge_cannot_exceed_max_gap_production_size():
    """review #1：短尾合併不得繞過 1.5x 上限。

    生產 chunk=25 分鐘、音檔 54.9 分鐘：切點在 ~25 與 ~50 分鐘，尾巴僅 4.9 分鐘
    （< 20% = 5 分鐘）會觸發合併，併完最終 chunk 變 ~29.9 分鐘——正落在 #374
    記載的崩壞區間（30~39 分）。合併後必須重新驗證上限。
    """
    total = int(54.9 * 60 * 1000)
    cuts = _plan(lambda target: target, total=total, chunk=PROD_CHUNK_MS)

    gaps = _gaps([0] + cuts + [total])
    assert max(gaps) <= PROD_CHUNK_MS * 1.5 + 1, (
        f"合併後 chunk 長度失控: {max(gaps)/60000:.1f} 分鐘, cuts={cuts}"
    )


def test_short_tail_merge_still_happens_when_within_limit():
    """上限沒被突破時，短尾合併照常運作（不要因為防護而失去原本的行為）。"""
    total = int(28 * 60 * 1000)  # 28 分鐘，一個切點在 25 分，尾巴 3 分鐘
    cuts = _plan(lambda target: target, total=total, chunk=PROD_CHUNK_MS)

    assert cuts == [], f"3 分鐘的尾巴應被併入前段（併後 28 分 < 37.5 分上限）: {cuts}"


def test_production_chunk_size_normal_case():
    """生產設定下 90 分鐘音檔的切點：不得有超長 chunk。"""
    cuts = _plan(lambda target: target + 3000, total=TOTAL_MS, chunk=PROD_CHUNK_MS)

    gaps = _gaps([0] + cuts + [TOTAL_MS])
    assert all(g > 0 for g in gaps)
    assert max(gaps) <= PROD_CHUNK_MS * 1.5 + 1, f"{max(gaps)/60000:.1f} 分鐘"


def test_collapse_detected_across_second_boundary():
    """review #4：塌陷群跨整數秒邊界時，整數秒分桶會把計數對半 → 滑動窗才抓得到。"""
    # 60 段在 3565.9，60 段在 3566.0：任一整數秒桶都只有 60（<門檻 80），
    # 但 1 秒滑動窗內有 120
    segs = [{"start": 3565.9, "end": 3565.95} for _ in range(60)]
    segs += [{"start": 3566.0, "end": 3566.05} for _ in range(60)]

    got = WhisperProcessor._detect_timestamp_collapse(
        segs, max_per_second=80, max_zero_duration=10_000
    )

    assert got is not None, "跨秒邊界的塌陷群不得漏報"
    assert got["segments_in_window"] == 120


def test_zero_duration_signal_alone_triggers_detection():
    """review #4：零長度 segment 是獨立的伴隨訊號（#374 實例有 112 個）。"""
    # 刻意把時間戳分散，讓滑動窗口訊號不觸發
    segs = [{"start": float(i * 5), "end": float(i * 5)} for i in range(112)]

    got = WhisperProcessor._detect_timestamp_collapse(
        segs, max_per_second=10_000, max_zero_duration=40
    )

    assert got is not None
    assert got["zero_duration_segments"] == 112


def test_chunk_index_parsed_from_end_of_filename():
    """review #3：使用者檔名含 `chunk_N` 時不得解析錯 index。"""
    from src.services.utils.whisper_processor import _parse_chunk_index

    assert _parse_chunk_index("/tmp/_temp_audio_chunk_7.mp3") == 7
    # 使用者原始檔名自己就含 chunk_3 → 必須取尾端的 7，不是 3
    assert _parse_chunk_index("/tmp/_temp_my_chunk_3_recording_chunk_7.mp3") == 7
    assert _parse_chunk_index("/tmp/run_12345/_temp_x_chunk_12.mp3") == 12


def test_chunk_index_parse_rejects_unexpected_name():
    from src.services.utils.whisper_processor import _parse_chunk_index

    try:
        _parse_chunk_index("/tmp/no_index_here.mp3")
    except ValueError:
        pass
    else:
        raise AssertionError("無法解析時應該要拋 ValueError，不能靜默回錯的 index")


def test_collapse_check_covers_gpu_path():
    """review #2：GPU batched 路徑（prod/staging 實際走的）必須經過觀測點。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)
    collapsed = [{"start": 3565.6, "end": 3565.6, "text": "x"} for _ in range(300)]
    seen = {}

    def fake_log(segments, path):
        seen["path"] = path
        seen["n"] = len(segments)
        return segments

    proc._has_gpu = lambda: True
    proc._ensure_valid_audio = lambda p: p
    proc._transcribe_with_timestamps = lambda *a, **k: (collapsed, "zh")
    proc._sanitize_segments = fake_log

    proc.transcribe_in_chunks("dummy.mp3")

    assert seen.get("path") == "gpu_batched", f"GPU 路徑未經過觀測點: {seen}"
    assert seen["n"] == 300


def test_collapse_check_covers_cpu_parallel_path():
    proc = WhisperProcessor.__new__(WhisperProcessor)
    segs = [{"start": 1.0, "end": 2.0, "text": "x"}]
    seen = {}

    proc._has_gpu = lambda: False
    proc.transcribe_in_chunks_parallel = lambda *a, **k: ("t", segs, "zh")
    def fake_sanitize(segments, path):
        seen.update(path=path, n=len(segments))
        return segments

    proc._sanitize_segments = fake_sanitize

    text, out, lang = proc.transcribe_in_chunks("dummy.mp3")

    assert seen.get("path") == "cpu_parallel", f"CPU 路徑未經過觀測點: {seen}"
    assert (text, out, lang) == ("t", segs, "zh"), "回傳值不得被觀測點改動"


def test_collapse_check_never_breaks_transcription():
    """觀測失敗絕不能影響轉錄（sanity check 不擋任務完成）。"""
    proc = WhisperProcessor.__new__(WhisperProcessor)

    def boom(segments, **kwargs):
        raise RuntimeError("detector exploded")

    proc._detect_timestamp_collapse = boom
    segs = [{"start": 0.0, "end": 1.0}]
    # 保險網自己壞掉時必須原樣回傳，不得拋、不得吃掉資料
    assert proc._sanitize_segments(segs, path="test") == segs
