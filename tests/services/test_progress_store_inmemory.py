"""InMemoryProgressStore 的 invariants 測試（Stage 1）

可以用 pytest 跑，也可以直接 `python tests/services/test_progress_store_inmemory.py`。
"""

import sys
import threading
import unittest
from pathlib import Path

# 讓測試可以從 repo root 直接 `python tests/...` 跑
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.progress_store import (  # noqa: E402
    InMemoryProgressStore,
    PHASE_WEIGHTS,
    Phase,
    _compute_overall_percentage,
)


class TestComputeOverallPercentage(unittest.TestCase):
    def test_preparation_at_zero(self):
        self.assertEqual(_compute_overall_percentage(Phase.PREPARATION, 0.0), 0.0)

    def test_preparation_complete(self):
        self.assertEqual(_compute_overall_percentage(Phase.PREPARATION, 1.0), 10.0)

    def test_transcription_half(self):
        self.assertEqual(
            _compute_overall_percentage(Phase.TRANSCRIPTION, 0.5),
            10.0 + 77.0 * 0.5,
        )

    def test_punctuation_complete(self):
        self.assertEqual(_compute_overall_percentage(Phase.PUNCTUATION, 1.0), 100.0)

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(PHASE_WEIGHTS.values()), 100.0)


class TestInMemoryProgressStore(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryProgressStore()

    def test_get_unknown_task_returns_none(self):
        self.assertIsNone(self.store.get("unknown"))

    def test_set_phase_then_get(self):
        self.store.set_phase("t1", Phase.PREPARATION, 0.5, message="hi")
        snap = self.store.get("t1")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.phase, Phase.PREPARATION)
        self.assertEqual(snap.phase_progress, 0.5)
        self.assertEqual(snap.overall_percentage, 5.0)
        self.assertEqual(snap.message, "hi")
        self.assertEqual(snap.details, {})

    def test_set_phase_includes_details(self):
        self.store.set_phase(
            "t1",
            Phase.TRANSCRIPTION,
            0.3,
            message="3/10",
            details={"completed_chunks": 3, "total_chunks": 10},
        )
        snap = self.store.get("t1")
        self.assertEqual(snap.details, {"completed_chunks": 3, "total_chunks": 10})

    def test_set_phase_rejects_negative_progress(self):
        with self.assertRaises(ValueError):
            self.store.set_phase("t1", Phase.PREPARATION, -0.1)

    def test_set_phase_rejects_progress_above_one(self):
        with self.assertRaises(ValueError):
            self.store.set_phase("t1", Phase.PREPARATION, 1.5)

    def test_phase_cannot_go_backwards(self):
        self.store.set_phase("t1", Phase.PUNCTUATION, 0.5)
        with self.assertRaises(ValueError):
            self.store.set_phase("t1", Phase.TRANSCRIPTION, 0.0)

    def test_phase_can_advance(self):
        self.store.set_phase("t1", Phase.PREPARATION, 1.0)
        self.store.set_phase("t1", Phase.TRANSCRIPTION, 0.5)
        snap = self.store.get("t1")
        self.assertEqual(snap.phase, Phase.TRANSCRIPTION)

    def test_phase_can_update_in_place(self):
        self.store.set_phase("t1", Phase.TRANSCRIPTION, 0.3)
        self.store.set_phase("t1", Phase.TRANSCRIPTION, 0.7)
        snap = self.store.get("t1")
        self.assertEqual(snap.phase_progress, 0.7)

    def test_clear_removes_snapshot(self):
        self.store.set_phase("t1", Phase.PREPARATION, 0.5)
        self.store.clear("t1")
        self.assertIsNone(self.store.get("t1"))

    def test_clear_is_idempotent(self):
        self.store.clear("never_existed")
        self.store.set_phase("t1", Phase.PREPARATION, 0.5)
        self.store.clear("t1")
        self.store.clear("t1")  # 第二次也不該爆
        self.assertIsNone(self.store.get("t1"))

    def test_clear_then_set_resets_phase_history(self):
        # 清掉之後可以重新從 PREPARATION 開始（不殘留 phase 順序檢查）
        self.store.set_phase("t1", Phase.PUNCTUATION, 0.5)
        self.store.clear("t1")
        self.store.set_phase("t1", Phase.PREPARATION, 0.0)
        snap = self.store.get("t1")
        self.assertEqual(snap.phase, Phase.PREPARATION)

    def test_multiple_tasks_isolated(self):
        self.store.set_phase("a", Phase.PREPARATION, 1.0)
        self.store.set_phase("b", Phase.PUNCTUATION, 0.5)
        self.assertEqual(self.store.get("a").overall_percentage, 10.0)
        self.assertEqual(
            self.store.get("b").overall_percentage,
            10.0 + 77.0 + 13.0 * 0.5,
        )

    def test_thread_safety(self):
        # 多執行緒同時寫不同 task — 不該爆，最終所有 task 都拿得到 snapshot
        def worker(task_id: str):
            for i in range(50):
                self.store.set_phase(
                    task_id,
                    Phase.TRANSCRIPTION,
                    i / 50.0,
                    message=f"{i}",
                )

        threads = [
            threading.Thread(target=worker, args=(f"task{i}",)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(10):
            snap = self.store.get(f"task{i}")
            self.assertIsNotNone(snap)
            self.assertEqual(snap.phase, Phase.TRANSCRIPTION)


if __name__ == "__main__":
    unittest.main()
