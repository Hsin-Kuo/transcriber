"""worker_core.priority 純函數測試。

驗證雙佇列 N:1 取用順序與 streak 計數規則——無副作用、不碰 SQS。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.worker_core.priority import (  # noqa: E402
    NORMAL,
    PRIORITY,
    build_poll_sequence,
    next_streak,
    poll_order,
)

RATIO = 3
LONG = 20


class TestPollOrder:
    @pytest.mark.parametrize("streak", [0, 1, 2])
    def test_below_ratio_prefers_priority(self, streak):
        first, second, reset_after = poll_order(streak, RATIO)
        assert (first, second) == (PRIORITY, NORMAL)
        assert reset_after is False

    @pytest.mark.parametrize("streak", [3, 4, 99])
    def test_at_or_above_ratio_prefers_normal_and_resets(self, streak):
        first, second, reset_after = poll_order(streak, RATIO)
        assert (first, second) == (NORMAL, PRIORITY)
        assert reset_after is True

    def test_ratio_one_alternates_every_round(self):
        # ratio=1 → streak 0 偏好 priority、streak 1 起每輪都讓 normal 先選
        assert poll_order(0, 1)[:2] == (PRIORITY, NORMAL)
        assert poll_order(1, 1)[:2] == (NORMAL, PRIORITY)


class TestBuildPollSequence:
    BOTH = {PRIORITY, NORMAL}

    def test_priority_first_short_normal_long(self):
        # streak < ratio：priority short-poll(0)、normal long-poll
        seq = build_poll_sequence(PRIORITY, NORMAL, self.BOTH, LONG)
        assert seq == [(PRIORITY, 0), (NORMAL, LONG)]

    def test_normal_first_on_reset_slot(self):
        # 第 N 輪對調：normal short-poll(0)、priority long-poll
        seq = build_poll_sequence(NORMAL, PRIORITY, self.BOTH, LONG)
        assert seq == [(NORMAL, 0), (PRIORITY, LONG)]

    def test_only_normal_configured_single_long_poll(self):
        # 優先佇列未配置 → 單條 normal long-poll，等同舊版單佇列行為
        seq = build_poll_sequence(PRIORITY, NORMAL, {NORMAL}, LONG)
        assert seq == [(NORMAL, LONG)]

    def test_skips_unconfigured_priority_keeps_long_poll_on_last(self):
        seq = build_poll_sequence(NORMAL, PRIORITY, {NORMAL}, LONG)
        assert seq == [(NORMAL, LONG)]


class TestNextStreak:
    def test_priority_increments(self):
        assert next_streak(0, False, PRIORITY) == 1
        assert next_streak(2, False, PRIORITY) == 3

    def test_normal_resets(self):
        assert next_streak(2, False, NORMAL) == 0

    def test_reset_after_always_zeros_even_on_priority(self):
        # 第 N 輪（normal-first 時隙）：一般佇列空、fallback 抽到 priority，streak 仍歸 0
        assert next_streak(3, True, PRIORITY) == 0
        assert next_streak(3, True, NORMAL) == 0


class TestStreakSequence:
    """模擬連續取用，驗證 N:1 比例與「第 N 輪一律歸 0」的整體行為。"""

    def test_pure_priority_traffic_is_bounded_by_ratio(self):
        # 只有 priority 任務：streak 在 0..RATIO 之間循環，永不超過 RATIO
        streak, seen_max = 0, 0
        for _ in range(20):
            _, _, reset_after = poll_order(streak, RATIO)
            # 一般佇列永遠空 → 一律抽到 priority
            streak = next_streak(streak, reset_after, PRIORITY)
            seen_max = max(seen_max, streak)
        assert seen_max == RATIO  # 達到 RATIO 後下一輪 reset_after 歸 0

    def test_mixed_traffic_honors_three_to_one(self):
        # priority 充足、normal 也有貨：每 RATIO 顆 priority 後恰好讓 1 顆 normal
        streak = 0
        picks = []
        for _ in range(8):
            first, _, reset_after = poll_order(streak, RATIO)
            # 偏好佇列有貨就抽它（兩佇列皆有貨）
            picked = first
            streak = next_streak(streak, reset_after, picked)
            picks.append(picked)
        # 前 RATIO 顆 priority、第 RATIO+1 顆 normal，週期重複
        assert picks == [PRIORITY, PRIORITY, PRIORITY, NORMAL,
                         PRIORITY, PRIORITY, PRIORITY, NORMAL]
