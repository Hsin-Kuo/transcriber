"""ASR 覆蓋哨兵（_check_asr_coverage）：diar 有語音但 whisper 零輸出 → 落檔+告警。

背景（2026-09-20 staging）：whisper decoder 參數組合造成 seek 跳洞，48 分鐘音檔
固定丟 23 秒語音、任務照樣 completed 無痕——diar 是獨立語音訊號，可稽核覆蓋率。
"""
from unittest.mock import MagicMock

from src.transcription.orchestrator import TranscriptionOrchestrator


def _orc():
    orc = TranscriptionOrchestrator(
        db=MagicMock(), progress_store=MagicMock(),
        whisper=MagicMock(), punctuation=MagicMock(),
    )
    orc._update_task = MagicMock()
    return orc


def _seg(words):
    return {"start": words[0][0], "end": words[-1][1],
            "words": [{"start": a, "end": b, "word": w} for a, b, w in words]}


def test_gap_detected_and_persisted():
    orc = _orc()
    diar = [
        {"start": 0.0, "end": 10.0, "speaker": "A"},     # 有字
        {"start": 20.0, "end": 43.0, "speaker": "B"},    # 23 秒洞：完全無字
        {"start": 50.0, "end": 51.0, "speaker": "A"},    # <2s，不計
    ]
    segs = [_seg([(1.0, 2.0, "一"), (3.0, 4.0, "二")])]

    orc._check_asr_coverage("t1", diar, segs)

    ((_, update),) = [c.args for c in orc._update_task.call_args_list]
    cov = update["stats.asr_coverage"]
    assert cov == {
        "speech_turns": 2,
        "uncovered_turns": 1,
        "max_uncovered_seconds": 23.0,
    }


def test_full_coverage_writes_zero():
    orc = _orc()
    diar = [{"start": 0.0, "end": 5.0, "speaker": "A"}]
    segs = [_seg([(0.5, 1.5, "一"), (2.0, 4.8, "二")])]

    orc._check_asr_coverage("t1", diar, segs)

    cov = orc._update_task.call_args.args[1]["stats.asr_coverage"]
    assert cov["uncovered_turns"] == 0 and cov["speech_turns"] == 1


def test_no_words_at_all_is_silent_noop():
    """整份無字（純音樂等）→ 無基準可比，不落檔不告警。"""
    orc = _orc()
    orc._check_asr_coverage("t1", [{"start": 0, "end": 9, "speaker": "A"}], [])
    orc._update_task.assert_not_called()


def test_sentinel_never_raises():
    orc = _orc()
    orc._update_task = MagicMock(side_effect=RuntimeError("db down"))
    diar = [{"start": 0.0, "end": 5.0, "speaker": "A"}]
    segs = [_seg([(0.5, 1.5, "一")])]
    orc._check_asr_coverage("t1", diar, segs)  # 不得拋出
