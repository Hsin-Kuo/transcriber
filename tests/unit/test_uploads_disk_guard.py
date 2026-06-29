"""init 磁碟容量守門 _has_room_for 的純函式測試。

不需 MongoDB。只設 JWT_SECRET_KEY 讓 src.routers.uploads 能 import。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.routers import uploads  # noqa: E402

GB = 1024 ** 3


def test_room_when_plenty_free():
    """放得下檔案後剩餘遠高於底線 → 放行。"""
    assert uploads._has_room_for(1 * GB, 5 * GB) is True


def test_no_room_when_would_drop_below_reserve():
    """放得下檔案，但剩餘會低於保留底線 → 拒絕。"""
    # 5GB free - 4GB file = 1GB < 2GB 底線
    assert uploads._has_room_for(4 * GB, 5 * GB) is False


def test_boundary_exactly_reserve_is_allowed():
    """剛好等於底線 → 放行（>= 而非 >）。"""
    free = uploads.DISK_RESERVE_BYTES + 1 * GB
    assert uploads._has_room_for(1 * GB, free) is True


def test_file_larger_than_free_rejected():
    """檔案比可用空間還大 → 必拒（負數遠低於底線）。"""
    assert uploads._has_room_for(10 * GB, 1 * GB) is False
