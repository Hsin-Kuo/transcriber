"""統一 TranscriptionOrchestrator 整合測試（Phase B)。

安全網:假 processor + 真 test Mongo + 假 AudioSource。驗證統一 pipeline 的
**編排行為**——phase 序列、取消、終態、diarization 合併/降級、標點 fallback——
不碰真 Whisper（轉錄品質另由各 processor 自己的測試負責）。

每個 test 都編碼一條 grilling 裁決;case 旁的註解標明它 pin 的是哪條決定。

前置:連得到的 MongoDB（MONGODB_URL 或 localhost:27020),連不上整組 skip;
      ffmpeg(PREPARATION 的 convert_to_mp3 / convert_to_wav 真的會跑)。

⚠️ 此檔在 src/transcription/orchestrator.py 建立前會 collection error(全紅)——
   這是 Phase B 的預期狀態,Phase C 把 orchestrator 寫到讓本檔轉綠。
"""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
os.environ.setdefault("DEPLOY_ENV", "local")
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27020/?directConnection=true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None

from bson import ObjectId  # noqa: E402
from src.services.progress_store import Phase  # noqa: E402

# orchestrator 還不存在時,collection 會在這裡 ImportError → 全檔紅(Phase B 預期)
from src.transcription.orchestrator import (  # noqa: E402
    TranscriptionCancelled,
    TranscriptionOrchestrator,
)

_MONGO_URL = os.environ["MONGODB_URL"]
_TEST_DB = "transcriber_test"


def _mongo_available() -> bool:
    if MongoClient is None:
        return False
    try:
        c = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=1000)
        c.admin.command("ping")
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason=f"MongoDB unavailable at {_MONGO_URL}"
)


# ── fakes ────────────────────────────────────────────────

class FakeWhisper:
    """罐頭轉錄結果。fail/empty 用來模擬失敗路徑。"""

    def __init__(self, *, text="hello world", segments=None, language="en",
                 fail=False, empty=False):
        self._text = text
        self._segments = segments if segments is not None else [
            {"text": "hello", "start": 0.0, "end": 0.5},
            {"text": "world", "start": 0.5, "end": 1.0},
        ]
        self._language = language
        self._fail = fail
        self._empty = empty

    def transcribe(self, mp3_path, language=None, progress_callback=None):
        if self._fail:
            raise RuntimeError("whisper boom")
        if progress_callback is not None:
            progress_callback(1.0, 1.0)
        if self._empty:
            return None, [], None
        return self._text, list(self._segments), self._language

    def transcribe_in_chunks(self, mp3_path, language=None, progress_callback=None):
        if progress_callback is not None:
            progress_callback(1.0, 1.0)
        return self.transcribe(mp3_path, language)

    def _merge_speaker_to_segments(self, segments, diar_segments):
        # subtitle 模式:把 speaker 併進 segments
        return [{**s, "speaker": "A"} for s in segments]

    def _merge_transcription_with_diarization(self, segments, diar_segments):
        # paragraph 模式:回傳含 speaker 標記的整段文字
        return "A: " + " ".join(s["text"] for s in segments)


class FakePunctuation:
    def __init__(self, *, fail=False):
        self._fail = fail

    def process(self, text, provider=None, language=None, progress_callback=None):
        if self._fail:
            raise RuntimeError("gemini quota exceeded")
        if progress_callback is not None:
            progress_callback(1, 1)
        return text + "[punct]", "fake-model", {"total": 10, "prompt": 6, "completion": 4}


class CancellingPunctuation:
    """模擬使用者在 PUNCTUATION 階段按取消:process 中途把 task 標成 cancelled。"""

    def __init__(self, db, task_id):
        self._db = db
        self._task_id = task_id

    def process(self, text, provider=None, language=None, progress_callback=None):
        self._db.tasks.update_one({"_id": self._task_id}, {"$set": {"status": "cancelled"}})
        if progress_callback is not None:
            progress_callback(1, 1)   # → _update_punctuation_progress → check_cancelled
        return text + "[punct]", "fake-model", {"total": 1}


class FakeDiarization:
    """記錄收到的音檔路徑——用來斷言 grilling 裁決「diarization 走 WAV」。"""

    def __init__(self, *, segments=None, fail=False):
        self._segments = segments if segments is not None else [
            {"speaker": "A", "start": 0.0, "end": 1.0},
        ]
        self._fail = fail
        self.called_with = None

    def perform_diarization(self, audio_path, max_speakers=None):
        self.called_with = Path(audio_path)
        if self._fail:
            raise RuntimeError("pyannote boom")
        return list(self._segments)


class FakeAudioSource:
    """假 AudioSource——acquire 回傳 fixture 音檔,記錄 cleanup 收到的 succeeded。"""

    def __init__(self, audio_path: Path):
        self._audio_path = audio_path
        self.cleaned_with = None

    def acquire(self, dest_dir: Path) -> Path:
        return self._audio_path

    def cleanup(self, succeeded: bool) -> None:
        self.cleaned_with = succeeded


class RecordingProgressStore:
    """記錄所有 set_phase 呼叫,供斷言 phase 序列與單調性。"""

    def __init__(self):
        self.events = []   # [(Phase, phase_progress)]
        self.cleared = []

    def set_phase(self, task_id, phase, phase_progress, message="", details=None):
        self.events.append((phase, phase_progress))

    def clear(self, task_id):
        self.cleared.append(task_id)

    def get(self, task_id):
        return None


# ── fixtures ─────────────────────────────────────────────

@pytest.fixture(scope="module")
def mongo_client():
    client = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
    yield client
    client.drop_database(_TEST_DB)
    client.close()


@pytest.fixture
def db(mongo_client):
    database = mongo_client[_TEST_DB]
    for coll in ("tasks", "transcriptions", "segments", "reservations", "users"):
        database[coll].delete_many({})
    return database


@pytest.fixture
def tiny_audio(tmp_path):
    """ffmpeg 生一個 1 秒靜音 wav——PREPARATION 的 convert_to_mp3 真的會跑。"""
    path = tmp_path / "tiny.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "1", str(path)],
        check=True, capture_output=True,
    )
    return path


# ── helpers ──────────────────────────────────────────────

def _insert_task(db, *, task_type="paragraph", status="processing", error=None,
                 user_id=None, audio_duration_seconds=0):
    task_id = str(uuid.uuid4())
    doc = {
        "_id": task_id,
        "status": status,
        "task_type": task_type,
        "user": {"user_id": user_id or str(ObjectId()), "tier": "free"},
        "config": {},
        "file": {"filename": "meeting.m4a"},
        "stats": {"audio_duration_seconds": audio_duration_seconds},
        "keep_audio": False,
        "timestamps": {},
    }
    if error is not None:
        doc["error"] = error
    db.tasks.insert_one(doc)
    return task_id


def _make_orchestrator(db, *, whisper=None, punctuation=None, diarization=None,
                       progress_store=None):
    return TranscriptionOrchestrator(
        db=db,
        progress_store=progress_store or RecordingProgressStore(),
        whisper=whisper or FakeWhisper(),
        punctuation=punctuation or FakePunctuation(),
        diarization=diarization,
    )


def _run(orc, task_id, audio_source, *, language="en", use_chunking=False,
         use_punctuation=True, punctuation_provider="gemini",
         use_diarization=False, max_speakers=None, ui_language=None):
    orc.run(
        task_id, audio_source, language, use_chunking, use_punctuation,
        punctuation_provider, use_diarization, max_speakers, ui_language,
    )


# ── tests ────────────────────────────────────────────────

class TestHappyPath:
    def test_paragraph_completes_and_persists(self, db, tiny_audio):
        """happy path:status→completed、transcriptions/segments 落地。"""
        task_id = _insert_task(db, task_type="paragraph")
        src = FakeAudioSource(tiny_audio)
        orc = _make_orchestrator(db)

        _run(orc, task_id, src)

        task = db.tasks.find_one({"_id": task_id})
        assert task["status"] == "completed"
        assert db.transcriptions.find_one({"_id": task_id}) is not None
        assert db.segments.find_one({"_id": task_id}) is not None
        assert src.cleaned_with is True   # 成功 → cleanup(succeeded=True)

    def test_completion_unsets_stale_error(self, db, tiny_audio):
        """裁決:採用 Worker 的 unset error——完成時清掉殘留 error 欄位。"""
        task_id = _insert_task(db, error={"code": "SERVER_RESTART", "message": "x"})
        orc = _make_orchestrator(db)

        _run(orc, task_id, FakeAudioSource(tiny_audio))

        task = db.tasks.find_one({"_id": task_id})
        assert task["status"] == "completed"
        assert "error" not in task

    def test_subtitle_mode_merges_speakers_into_segments(self, db, tiny_audio):
        """subtitle + diarization → 走 _merge_speaker_to_segments。"""
        task_id = _insert_task(db, task_type="subtitle")
        whisper = FakeWhisper()
        orc = _make_orchestrator(db, whisper=whisper, diarization=FakeDiarization())

        _run(orc, task_id, FakeAudioSource(tiny_audio), use_diarization=True)

        seg_doc = db.segments.find_one({"_id": task_id})
        assert seg_doc is not None
        assert all("speaker" in s for s in seg_doc["segments"])


class TestDiarization:
    def test_diarization_receives_wav_not_mp3(self, db, tiny_audio):
        """裁決:diarization 餵 WAV(不是 MP3)。"""
        diar = FakeDiarization()
        orc = _make_orchestrator(db, diarization=diar)

        _run(orc, _insert_task(db), FakeAudioSource(tiny_audio), use_diarization=True)

        assert diar.called_with is not None
        assert diar.called_with.suffix == ".wav"

    def test_diarization_failure_degrades_to_plain(self, db, tiny_audio):
        """diarization 失敗 → 降級純轉錄,任務仍 completed。"""
        task_id = _insert_task(db)
        orc = _make_orchestrator(db, diarization=FakeDiarization(fail=True))

        _run(orc, task_id, FakeAudioSource(tiny_audio), use_diarization=True)

        assert db.tasks.find_one({"_id": task_id})["status"] == "completed"
        assert db.transcriptions.find_one({"_id": task_id}) is not None


class TestPunctuationFallback:
    def test_punctuation_failure_keeps_original_text(self, db, tiny_audio):
        """標點失敗 → 用原文完成,不標 failed。"""
        task_id = _insert_task(db)
        orc = _make_orchestrator(db, punctuation=FakePunctuation(fail=True))

        _run(orc, task_id, FakeAudioSource(tiny_audio))

        task = db.tasks.find_one({"_id": task_id})
        assert task["status"] == "completed"
        content = db.transcriptions.find_one({"_id": task_id})["content"]
        assert "[punct]" not in content   # 用原文,沒套標點


class TestFailurePath:
    def test_whisper_exception_marks_failed(self, db, tiny_audio):
        task_id = _insert_task(db)
        src = FakeAudioSource(tiny_audio)
        orc = _make_orchestrator(db, whisper=FakeWhisper(fail=True))

        _run(orc, task_id, src)

        assert db.tasks.find_one({"_id": task_id})["status"] == "failed"
        assert src.cleaned_with is False   # 失敗 → cleanup(succeeded=False)

    def test_empty_transcription_marks_failed(self, db, tiny_audio):
        task_id = _insert_task(db)
        orc = _make_orchestrator(db, whisper=FakeWhisper(empty=True))

        _run(orc, task_id, FakeAudioSource(tiny_audio))

        assert db.tasks.find_one({"_id": task_id})["status"] == "failed"


class TestCancellation:
    def test_cancelled_status_aborts_without_overwriting(self, db, tiny_audio):
        """裁決:取消用 DB status poll。status=cancelled → 中止,不覆蓋狀態。"""
        task_id = _insert_task(db, status="cancelled")
        src = FakeAudioSource(tiny_audio)
        orc = _make_orchestrator(db)

        _run(orc, task_id, src)

        task = db.tasks.find_one({"_id": task_id})
        assert task["status"] == "cancelled"   # 沒被 completed/failed 覆蓋
        assert db.transcriptions.find_one({"_id": task_id}) is None
        assert src.cleaned_with is False

    def test_cancel_during_punctuation_aborts(self, db, tiny_audio):
        """裁決:PUNCTUATION 階段也要能即時取消,不被標點 fallback 的 except 吞掉。"""
        task_id = _insert_task(db)
        orc = _make_orchestrator(db, punctuation=CancellingPunctuation(db, task_id))

        _run(orc, task_id, FakeAudioSource(tiny_audio))

        task = db.tasks.find_one({"_id": task_id})
        assert task["status"] == "cancelled"                          # 沒被 completed 覆蓋
        assert db.transcriptions.find_one({"_id": task_id}) is None    # 沒走到存結果


class TestProgressSequence:
    def test_phases_advance_in_order(self, db, tiny_audio):
        """裁決:進度語意統一——PREPARATION → TRANSCRIPTION → PUNCTUATION 不倒退。"""
        ps = RecordingProgressStore()
        orc = _make_orchestrator(db, progress_store=ps)

        _run(orc, _insert_task(db), FakeAudioSource(tiny_audio))

        order = {Phase.PREPARATION: 0, Phase.TRANSCRIPTION: 1, Phase.PUNCTUATION: 2}
        seen = [order[p] for p, _ in ps.events]
        assert seen == sorted(seen), f"phase 倒退了: {ps.events}"
        assert {Phase.PREPARATION, Phase.TRANSCRIPTION, Phase.PUNCTUATION} <= {
            p for p, _ in ps.events
        }


class TestQuota:
    def test_successful_run_consumes_reservation_and_deducts(self, db, tiny_audio):
        """成功 → 兩步式扣款:刪預扣 + 套 consumption pipeline 扣 usage。"""
        user_id = str(ObjectId())
        task_id = _insert_task(db, user_id=user_id, audio_duration_seconds=120)
        db.users.insert_one({"_id": ObjectId(user_id), "usage": {"duration_minutes": 0.0}})
        db.reservations.insert_one(
            {"task_id": task_id, "user_id": user_id, "duration_minutes": 2.0, "created_at": 0}
        )
        orc = _make_orchestrator(db)

        _run(orc, task_id, FakeAudioSource(tiny_audio))

        assert db.reservations.find_one({"task_id": task_id}) is None   # 預扣已 consume
        user = db.users.find_one({"_id": ObjectId(user_id)})
        assert user["usage"]["duration_minutes"] == 2.0                 # 120s = 2min 已扣

    def test_failed_run_releases_reservation(self, db, tiny_audio):
        """失敗 → 釋放預扣。"""
        task_id = _insert_task(db, audio_duration_seconds=120)
        db.reservations.insert_one(
            {"task_id": task_id, "duration_minutes": 2.0, "created_at": 0}
        )
        orc = _make_orchestrator(db, whisper=FakeWhisper(fail=True))

        _run(orc, task_id, FakeAudioSource(tiny_audio))

        assert db.tasks.find_one({"_id": task_id})["status"] == "failed"
        assert db.reservations.find_one({"task_id": task_id}) is None   # 預扣已釋放
