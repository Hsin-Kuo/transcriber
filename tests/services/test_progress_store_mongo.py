"""MongoProgressStore 整合測試。

需要連得到的 MongoDB（預設讀 MONGODB_URL，否則 mongodb://localhost:27020）。
連不上時整組 skip。
"""

import os
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from pymongo import MongoClient
    from pymongo.errors import ServerSelectionTimeoutError
except ImportError:  # pragma: no cover
    MongoClient = None
    ServerSelectionTimeoutError = Exception

from src.services.progress_store import (  # noqa: E402
    MongoProgressStore,
    Phase,
)


_MONGO_URL = os.getenv(
    "MONGODB_URL",
    "mongodb://localhost:27020/?directConnection=true",
)
_TEST_DB_NAME = "transcriber_test"
_TEST_COLL_NAME = "task_progress_test"


def _mongo_available() -> bool:
    if MongoClient is None:
        return False
    try:
        client = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=1000)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


_AVAILABLE = _mongo_available()


@unittest.skipUnless(_AVAILABLE, f"MongoDB unavailable at {_MONGO_URL}")
class TestMongoProgressStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient(_MONGO_URL, serverSelectionTimeoutMS=2000)
        cls.collection = cls.client[_TEST_DB_NAME][_TEST_COLL_NAME]

    @classmethod
    def tearDownClass(cls):
        cls.client.drop_database(_TEST_DB_NAME)
        cls.client.close()

    def setUp(self):
        # 每個測試前清空 collection（保留 indexes）
        self.collection.delete_many({})
        self.store = MongoProgressStore(self.collection)
        # 用唯一 id 進一步隔離，免得 setup race
        self.tid = f"test-{uuid.uuid4().hex[:8]}"

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.store.get("never_written"))

    def test_set_then_get(self):
        self.store.set_phase(self.tid, Phase.PREPARATION, 0.5, message="hi")
        snap = self.store.get(self.tid)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.phase, Phase.PREPARATION)
        self.assertEqual(snap.phase_progress, 0.5)
        self.assertEqual(snap.overall_percentage, 5.0)
        self.assertEqual(snap.message, "hi")

    def test_set_with_details(self):
        self.store.set_phase(
            self.tid,
            Phase.TRANSCRIPTION,
            0.3,
            message="3/10",
            details={"completed_chunks": 3, "total_chunks": 10},
        )
        snap = self.store.get(self.tid)
        self.assertEqual(snap.details, {"completed_chunks": 3, "total_chunks": 10})

    def test_phase_progress_out_of_range(self):
        with self.assertRaises(ValueError):
            self.store.set_phase(self.tid, Phase.PREPARATION, 1.5)
        with self.assertRaises(ValueError):
            self.store.set_phase(self.tid, Phase.PREPARATION, -0.1)

    def test_phase_cannot_go_backwards(self):
        self.store.set_phase(self.tid, Phase.PUNCTUATION, 0.5)
        with self.assertRaises(ValueError):
            self.store.set_phase(self.tid, Phase.TRANSCRIPTION, 0.0)

    def test_phase_can_advance(self):
        self.store.set_phase(self.tid, Phase.PREPARATION, 1.0)
        self.store.set_phase(self.tid, Phase.TRANSCRIPTION, 0.5)
        snap = self.store.get(self.tid)
        self.assertEqual(snap.phase, Phase.TRANSCRIPTION)

    def test_set_updates_in_place(self):
        self.store.set_phase(self.tid, Phase.TRANSCRIPTION, 0.3)
        self.store.set_phase(self.tid, Phase.TRANSCRIPTION, 0.7, message="updated")
        snap = self.store.get(self.tid)
        self.assertEqual(snap.phase_progress, 0.7)
        self.assertEqual(snap.message, "updated")

    def test_clear_removes_doc(self):
        self.store.set_phase(self.tid, Phase.PREPARATION, 0.5)
        self.store.clear(self.tid)
        self.assertIsNone(self.store.get(self.tid))

    def test_clear_idempotent(self):
        self.store.clear("never_existed")  # 不該爆
        self.store.set_phase(self.tid, Phase.PREPARATION, 0.5)
        self.store.clear(self.tid)
        self.store.clear(self.tid)
        self.assertIsNone(self.store.get(self.tid))

    def test_clear_then_set_resets_phase_history(self):
        self.store.set_phase(self.tid, Phase.PUNCTUATION, 0.5)
        self.store.clear(self.tid)
        self.store.set_phase(self.tid, Phase.PREPARATION, 0.0)
        self.assertEqual(self.store.get(self.tid).phase, Phase.PREPARATION)

    def test_ttl_index_exists(self):
        # MongoProgressStore.__init__ 應該已建好 TTL index
        index_info = self.collection.index_information()
        ttl_indexes = [
            (name, info)
            for name, info in index_info.items()
            if "expireAfterSeconds" in info
        ]
        self.assertEqual(len(ttl_indexes), 1, f"預期一個 TTL index，找到 {ttl_indexes}")
        name, info = ttl_indexes[0]
        self.assertEqual(info["expireAfterSeconds"], 6 * 60 * 60)
        self.assertEqual(info["key"], [("updated_at", 1)])

    def test_ensure_indexes_idempotent(self):
        # 重複建 store 不該爆
        MongoProgressStore(self.collection)
        MongoProgressStore(self.collection)

    def test_updated_at_changes_on_each_set(self):
        self.store.set_phase(self.tid, Phase.PREPARATION, 0.1)
        first = self.store.get(self.tid).updated_at
        time.sleep(0.01)
        self.store.set_phase(self.tid, Phase.PREPARATION, 0.2)
        second = self.store.get(self.tid).updated_at
        self.assertGreater(second, first)


if __name__ == "__main__":
    if not _AVAILABLE:
        print(f"⚠️  MongoDB at {_MONGO_URL} unavailable — skipping all tests.")
    unittest.main()
