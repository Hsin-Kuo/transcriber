"""TranscriptionOrchestrator 單元測試（M1.3 B）。

驗證 seam 的設計目的：用 mock 注入所有依賴，不碰 mongo、不真跑 Whisper，
覆蓋 Phase 機器、取消、終態三條 exit path、PUNCTUATION fallback。
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.progress_store import Phase  # noqa: E402
from src.services.transcription_orchestrator import (  # noqa: E402
    TranscriptionCancelled,
    TranscriptionOrchestrator,
    _resolve_punct_language,
)


def _make_orc(
    *,
    whisper=None,
    punctuation=None,
    diarization=None,
    task_service=None,
    progress_store=None,
    convert_audio_to_mp3=None,
    save_audio_file_sync=None,
    save_transcription_results=None,
):
    """Helper 建一個 Orchestrator，所有 dep 默認 MagicMock。"""
    return TranscriptionOrchestrator(
        whisper=whisper or MagicMock(),
        punctuation=punctuation or MagicMock(),
        diarization=diarization,  # 默認 None
        progress_store=progress_store or MagicMock(),
        task_service=task_service or MagicMock(is_cancelled=MagicMock(return_value=False)),
        convert_audio_to_mp3=convert_audio_to_mp3 or MagicMock(return_value=Path("/tmp/fake.mp3")),
        save_audio_file_sync=save_audio_file_sync or MagicMock(),
        save_transcription_results=save_transcription_results or MagicMock(),
    )


class TestPhaseAPI:
    def test_enter_phase_sets_zero(self):
        ps = MagicMock()
        orc = _make_orc(progress_store=ps)
        orc.enter_phase("task-1", Phase.PREPARATION, "starting...")
        ps.set_phase.assert_called_once_with(
            "task-1", Phase.PREPARATION, 0.0, message="starting...", details=None
        )

    def test_report_progress_sets_fraction(self):
        ps = MagicMock()
        orc = _make_orc(progress_store=ps)
        orc.report_progress(
            "task-1", Phase.TRANSCRIPTION, 0.42, message="half-ish", details={"a": 1}
        )
        ps.set_phase.assert_called_once_with(
            "task-1", Phase.TRANSCRIPTION, 0.42, message="half-ish", details={"a": 1}
        )

    def test_complete_phase_sets_one(self):
        ps = MagicMock()
        orc = _make_orc(progress_store=ps)
        orc.complete_phase("task-1", Phase.PUNCTUATION, "done", details={"x": 9})
        ps.set_phase.assert_called_once_with(
            "task-1", Phase.PUNCTUATION, 1.0, message="done", details={"x": 9}
        )


class TestCheckCancelled:
    def test_not_cancelled_returns_silently(self):
        ts = MagicMock(is_cancelled=MagicMock(return_value=False))
        orc = _make_orc(task_service=ts)
        orc.check_cancelled("task-1")  # 不該拋
        ts.is_cancelled.assert_called_once_with("task-1")

    def test_cancelled_raises(self):
        ts = MagicMock(is_cancelled=MagicMock(return_value=True))
        orc = _make_orc(task_service=ts)
        with pytest.raises(TranscriptionCancelled):
            orc.check_cancelled("task-1")


class TestResolvePunctLanguage:
    """確認搬過來的 _resolve_punct_language 行為跟原版一致。"""

    def test_explicit_zh_tw(self):
        assert _resolve_punct_language("zh-TW", "en", None) == "zh-TW"

    def test_explicit_zh_cn(self):
        assert _resolve_punct_language("zh-CN", "en", None) == "zh-CN"

    def test_detected_zh_with_cn_ui(self):
        assert _resolve_punct_language(None, "zh", "zh-CN") == "zh-CN"

    def test_detected_zh_defaults_tw(self):
        assert _resolve_punct_language(None, "zh", None) == "zh-TW"
        assert _resolve_punct_language(None, "zh", "en") == "zh-TW"

    def test_other_language_passthrough(self):
        assert _resolve_punct_language(None, "en", None) == "en"
        assert _resolve_punct_language("ja", None, None) == "ja"

    def test_default_zh_when_all_none(self):
        assert _resolve_punct_language(None, None, None) == "zh"


class TestRunHappyPath:
    """完整 run() 走完，processors 被依序呼叫，mark_completed 觸發。"""

    def test_happy_path_calls_in_order(self, monkeypatch):
        # 設定 mock processors
        whisper = MagicMock()
        whisper.transcribe.return_value = ("hello world", [{"text": "hello"}, {"text": "world"}], "en")

        punctuation = MagicMock()
        punctuation.process.return_value = ("hello, world.", "gemini-2.5", {"total": 50})

        convert_mp3 = MagicMock(return_value=Path("/tmp/fake.mp3"))
        save_results = MagicMock()
        save_audio = MagicMock()
        ts = MagicMock(is_cancelled=MagicMock(return_value=False))
        ts.get_temp_dir = MagicMock(return_value=None)  # 沒 temp dir, 跳過 cleanup 細節

        orc = _make_orc(
            whisper=whisper,
            punctuation=punctuation,
            task_service=ts,
            convert_audio_to_mp3=convert_mp3,
            save_transcription_results=save_results,
            save_audio_file_sync=save_audio,
        )

        # 攔截 _mark_completed/_mark_failed 不打 DB
        monkeypatch.setattr(orc, "_mark_completed", MagicMock())
        monkeypatch.setattr(orc, "_mark_failed", MagicMock())

        orc.run(
            task_id="task-1",
            audio_file_path=Path("/tmp/audio.wav"),
            language="en",
            use_chunking=False,
            use_punctuation=True,
            punctuation_provider="gemini",
            use_diarization=False,
            max_speakers=None,
        )

        # 流程驗證
        convert_mp3.assert_called_once_with(Path("/tmp/audio.wav"))
        whisper.transcribe.assert_called_once()
        punctuation.process.assert_called_once()
        save_results.assert_called_once()
        # 最終標記 completed
        orc._mark_completed.assert_called_once()
        orc._mark_failed.assert_not_called()


class TestRunCancelledPath:
    """check_cancelled 拋 exception → cleanup 走但 mark_completed/mark_failed 都不呼叫。"""

    def test_cancelled_skips_completion_and_failure(self, monkeypatch):
        # task_service.is_cancelled 一開始就回 True → PREPARATION 後第一個 check 就拋
        ts = MagicMock(is_cancelled=MagicMock(return_value=True))
        ts.get_temp_dir = MagicMock(return_value=None)

        orc = _make_orc(task_service=ts)
        monkeypatch.setattr(orc, "_mark_completed", MagicMock())
        monkeypatch.setattr(orc, "_mark_failed", MagicMock())

        orc.run(
            task_id="task-cancel",
            audio_file_path=Path("/tmp/x.wav"),
            language=None,
            use_chunking=False,
            use_punctuation=False,
            punctuation_provider="none",
            use_diarization=False,
            max_speakers=None,
        )

        # 兩個終態都不該被呼叫
        orc._mark_completed.assert_not_called()
        orc._mark_failed.assert_not_called()


class TestRunFailurePath:
    """processor 拋 exception → 走 _mark_failed，不該走 _mark_completed。"""

    def test_whisper_failure_marks_failed(self, monkeypatch):
        whisper = MagicMock()
        whisper.transcribe.side_effect = RuntimeError("CUDA OOM")
        ts = MagicMock(is_cancelled=MagicMock(return_value=False))
        ts.get_temp_dir = MagicMock(return_value=None)

        orc = _make_orc(whisper=whisper, task_service=ts)
        monkeypatch.setattr(orc, "_mark_completed", MagicMock())
        monkeypatch.setattr(orc, "_mark_failed", MagicMock())

        orc.run(
            task_id="task-fail",
            audio_file_path=Path("/tmp/y.wav"),
            language=None,
            use_chunking=False,
            use_punctuation=False,
            punctuation_provider="none",
            use_diarization=False,
            max_speakers=None,
        )

        orc._mark_failed.assert_called_once()
        # 第一個 positional arg 是 task_id
        assert orc._mark_failed.call_args.args[0] == "task-fail"
        # 第二個是 error message
        assert "CUDA OOM" in orc._mark_failed.call_args.args[1]
        orc._mark_completed.assert_not_called()

    def test_empty_transcription_raises_value_error(self, monkeypatch):
        """Whisper 回 None 且 task 沒被取消 → raise ValueError → mark_failed"""
        whisper = MagicMock()
        whisper.transcribe.return_value = (None, [], None)
        ts = MagicMock(is_cancelled=MagicMock(return_value=False))
        ts.get_temp_dir = MagicMock(return_value=None)

        orc = _make_orc(whisper=whisper, task_service=ts)
        monkeypatch.setattr(orc, "_mark_failed", MagicMock())

        orc.run(
            task_id="task-empty",
            audio_file_path=Path("/tmp/z.wav"),
            language=None,
            use_chunking=False,
            use_punctuation=False,
            punctuation_provider="none",
            use_diarization=False,
            max_speakers=None,
        )

        orc._mark_failed.assert_called_once()
        assert "轉錄結果為空" in orc._mark_failed.call_args.args[1]


class TestPunctuationFallback:
    """標點失敗 → 用 full_text 繼續完成（不該標 failed）。"""

    def test_punct_exception_falls_back_to_original(self, monkeypatch):
        whisper = MagicMock()
        whisper.transcribe.return_value = ("raw text", [{"text": "raw"}, {"text": "text"}], "en")

        punctuation = MagicMock()
        punctuation.process.side_effect = RuntimeError("Gemini quota exceeded")

        save_results = MagicMock()
        ts = MagicMock(is_cancelled=MagicMock(return_value=False))
        ts.get_temp_dir = MagicMock(return_value=None)

        orc = _make_orc(
            whisper=whisper,
            punctuation=punctuation,
            task_service=ts,
            save_transcription_results=save_results,
        )
        monkeypatch.setattr(orc, "_mark_completed", MagicMock())
        monkeypatch.setattr(orc, "_mark_failed", MagicMock())

        orc.run(
            task_id="task-punct-fail",
            audio_file_path=Path("/tmp/q.wav"),
            language="en",
            use_chunking=False,
            use_punctuation=True,
            punctuation_provider="gemini",
            use_diarization=False,
            max_speakers=None,
        )

        # 用原文存（標點失敗不該讓整體失敗）
        save_results.assert_called_once()
        saved_text = save_results.call_args.args[1]
        assert saved_text == "raw text"
        # 仍標 completed，不是 failed
        orc._mark_completed.assert_called_once()
        orc._mark_failed.assert_not_called()
