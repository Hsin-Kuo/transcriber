"""ProgressStore — 任務執行期進度的單一介面（Stage 1）

統一兩種部署模式下的進度寫入/讀出語意。

Phase 是執行流程的序列階段：PREPARATION → TRANSCRIPTION → PUNCTUATION。
PHASE_WEIGHTS 決定每個階段在總進度的權重，總和 100。
overall_percentage 由 store 在讀出時動態計算，呼叫端只負責回報自己處於哪個 phase
與 phase 內部進度（phase_progress: 0.0~1.0）。

Stage 1 只實作 InMemoryProgressStore（local 模式用）。Stage 2 加入 MongoProgressStore。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Dict, Optional, Protocol


class Phase(Enum):
    PREPARATION = "preparation"
    TRANSCRIPTION = "transcription"
    PUNCTUATION = "punctuation"


# 序列順序 — 越後面越晚。set_phase 不允許回到較早的 phase。
_PHASE_ORDER = [Phase.PREPARATION, Phase.TRANSCRIPTION, Phase.PUNCTUATION]


PHASE_WEIGHTS: Dict[Phase, float] = {
    Phase.PREPARATION: 10.0,
    Phase.TRANSCRIPTION: 77.0,
    Phase.PUNCTUATION: 13.0,
}

assert sum(PHASE_WEIGHTS.values()) == 100.0, "PHASE_WEIGHTS 總和必須是 100"


@dataclass(frozen=True)
class ProgressSnapshot:
    phase: Phase
    phase_progress: float
    overall_percentage: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _compute_overall_percentage(phase: Phase, phase_progress: float) -> float:
    completed_weight = 0.0
    for p in _PHASE_ORDER:
        if p is phase:
            break
        completed_weight += PHASE_WEIGHTS[p]
    current_weight = PHASE_WEIGHTS[phase]
    return min(100.0, completed_weight + current_weight * phase_progress)


class ProgressStore(Protocol):
    """進度儲存的介面。

    Invariants（呼叫端必須知道）：
    - phase_progress 必須在 [0.0, 1.0]
    - phase 不可倒退（從 PUNCTUATION 不能再 set_phase(TRANSCRIPTION)）
    - clear 是 idempotent
    - 實作必須是 thread-safe
    """

    def set_phase(
        self,
        task_id: str,
        phase: Phase,
        phase_progress: float = 0.0,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None: ...

    def get(self, task_id: str) -> Optional[ProgressSnapshot]: ...

    def clear(self, task_id: str) -> None: ...


class InMemoryProgressStore:
    """純記憶體實作（local 模式用）。

    用 dict + Lock 保護。snapshot 是不可變物件，讀出後不需鎖。
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshots: Dict[str, ProgressSnapshot] = {}

    def set_phase(
        self,
        task_id: str,
        phase: Phase,
        phase_progress: float = 0.0,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not 0.0 <= phase_progress <= 1.0:
            raise ValueError(
                f"phase_progress 必須在 [0.0, 1.0]，收到 {phase_progress}"
            )

        new_details = dict(details) if details else {}

        with self._lock:
            existing = self._snapshots.get(task_id)
            if existing is not None:
                existing_idx = _PHASE_ORDER.index(existing.phase)
                new_idx = _PHASE_ORDER.index(phase)
                if new_idx < existing_idx:
                    raise ValueError(
                        f"phase 不可倒退：task {task_id} 已在 {existing.phase.value}，"
                        f"嘗試設成 {phase.value}"
                    )

            self._snapshots[task_id] = ProgressSnapshot(
                phase=phase,
                phase_progress=phase_progress,
                overall_percentage=_compute_overall_percentage(phase, phase_progress),
                message=message,
                details=new_details,
                updated_at=datetime.now(timezone.utc),
            )

    def get(self, task_id: str) -> Optional[ProgressSnapshot]:
        with self._lock:
            return self._snapshots.get(task_id)

    def clear(self, task_id: str) -> None:
        with self._lock:
            self._snapshots.pop(task_id, None)


# task_progress collection 的 TTL：6 小時。Spot 中斷或 worker crash 時自動清。
_PROGRESS_TTL_SECONDS = 6 * 60 * 60


class MongoProgressStore:
    """MongoDB-backed 實作（AWS 模式 worker 寫入 / web server 讀出）。

    Document shape (collection 預設名稱：task_progress)：
        {
            _id: <task_id>,
            phase: "transcription",
            phase_progress: 0.3,
            overall_percentage: 33.1,
            message: "...",
            details: {...},
            updated_at: ISODate(...),
        }

    Init 時會 idempotent 地建 TTL index（依 updated_at，6 小時過期）。

    使用 pymongo（sync）。從 async caller（如 task_service.get_task）呼叫時，
    請用 asyncio.run_in_executor 包裝避免阻塞 event loop。
    """

    def __init__(self, collection: Any) -> None:
        """
        Args:
            collection: pymongo Collection。由呼叫端建立連線並注入。
        """
        self._collection = collection
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        # TTL index — 由 updated_at 決定過期時間
        self._collection.create_index(
            "updated_at",
            expireAfterSeconds=_PROGRESS_TTL_SECONDS,
            name="updated_at_ttl",
        )

    def set_phase(
        self,
        task_id: str,
        phase: Phase,
        phase_progress: float = 0.0,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not 0.0 <= phase_progress <= 1.0:
            raise ValueError(
                f"phase_progress 必須在 [0.0, 1.0]，收到 {phase_progress}"
            )

        # Phase 不可倒退：先讀現況檢查
        existing = self._collection.find_one({"_id": task_id}, {"phase": 1})
        if existing is not None and "phase" in existing:
            try:
                existing_phase = Phase(existing["phase"])
                existing_idx = _PHASE_ORDER.index(existing_phase)
                new_idx = _PHASE_ORDER.index(phase)
                if new_idx < existing_idx:
                    raise ValueError(
                        f"phase 不可倒退：task {task_id} 已在 {existing_phase.value}，"
                        f"嘗試設成 {phase.value}"
                    )
            except (ValueError, KeyError) as e:
                # 如果是上面 raise 的 ValueError 要 re-raise；其他（無效 phase 字串等）忽略，當作沒紀錄
                if "不可倒退" in str(e):
                    raise

        doc = {
            "phase": phase.value,
            "phase_progress": phase_progress,
            "overall_percentage": _compute_overall_percentage(phase, phase_progress),
            "message": message,
            "details": dict(details) if details else {},
            "updated_at": datetime.now(timezone.utc),
        }
        self._collection.update_one(
            {"_id": task_id},
            {"$set": doc},
            upsert=True,
        )

    def get(self, task_id: str) -> Optional[ProgressSnapshot]:
        doc = self._collection.find_one({"_id": task_id})
        if doc is None:
            return None
        try:
            phase = Phase(doc["phase"])
        except (ValueError, KeyError):
            return None
        return ProgressSnapshot(
            phase=phase,
            phase_progress=float(doc.get("phase_progress", 0.0)),
            overall_percentage=float(doc.get("overall_percentage", 0.0)),
            message=doc.get("message", ""),
            details=dict(doc.get("details") or {}),
            updated_at=doc.get("updated_at") or datetime.now(timezone.utc),
        )

    def clear(self, task_id: str) -> None:
        self._collection.delete_one({"_id": task_id})
