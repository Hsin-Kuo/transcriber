"""AdminAnalytics 純函式單元測試。

統計的 merge / derive 邏輯（除零保護、top-N 截斷、date-map 合併、token 合計）原本埋在
admin.py 的 HTTP endpoint 裡、只能起 FastAPI + 塞 Mongo 才測得到。抽成純函式後，餵
aggregation 結果 dict 即可斷言，不碰 Mongo / FastAPI。
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "a3f2c1b8e4d6a9f5c2b8e1d4a6f9c3b2e5d8a1f4c7b6e3d2a5f8c1b4e7d6a9f2",
)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.services.admin_analytics import (  # noqa: E402
    combine_token_usage,
    derive_overview,
    format_named_counts,
    format_performance,
    format_recent_orders,
    merge_daily,
    merge_top_users,
    summarize_subscriptions,
)


class TestDeriveOverview:
    def test_success_rate_computed(self):
        ov = derive_overview(
            total_tasks=200, completed_tasks=150, processing_tasks=10,
            failed_tasks=40, total_users=80, active_users=50,
        )
        assert ov["success_rate"] == 75.0
        assert ov["total_tasks"] == 200 and ov["completed_tasks"] == 150
        assert ov["total_users"] == 80 and ov["active_users"] == 50

    def test_zero_tasks_no_division_error(self):
        ov = derive_overview(
            total_tasks=0, completed_tasks=0, processing_tasks=0,
            failed_tasks=0, total_users=0, active_users=0,
        )
        assert ov["success_rate"] == 0


class TestCombineTokenUsage:
    def test_combines_and_computes_averages(self):
        punct = {"total_tokens": 1000, "total_prompt_tokens": 600,
                 "total_completion_tokens": 400, "tasks_with_tokens": 4}
        summary = {"total_tokens": 300, "total_prompt_tokens": 200,
                   "total_completion_tokens": 100, "summaries_with_tokens": 2}
        tu = combine_token_usage(punct, summary)
        assert tu["total_tokens"] == 1300
        assert tu["prompt_tokens"] == 800 and tu["completion_tokens"] == 500
        assert tu["punctuation"]["avg_tokens_per_task"] == 250.0   # 1000/4
        assert tu["summary"]["avg_tokens_per_summary"] == 150.0     # 300/2
        assert tu["punctuation"]["tasks_count"] == 4
        assert tu["summary"]["summaries_count"] == 2

    def test_zero_counts_no_division_error(self):
        empty = {"total_tokens": 0, "total_prompt_tokens": 0,
                 "total_completion_tokens": 0, "tasks_with_tokens": 0}
        empty_s = {"total_tokens": 0, "total_prompt_tokens": 0,
                   "total_completion_tokens": 0, "summaries_with_tokens": 0}
        tu = combine_token_usage(empty, empty_s)
        assert tu["total_tokens"] == 0
        assert tu["punctuation"]["avg_tokens_per_task"] == 0
        assert tu["summary"]["avg_tokens_per_summary"] == 0


class TestMergeDaily:
    def test_merges_tasks_and_summaries_by_date(self):
        tasks = [
            {"_id": "2026-06-01", "tasks_count": 5, "punctuation_tokens": 100},
            {"_id": "2026-06-02", "tasks_count": 3, "punctuation_tokens": 50},
        ]
        summaries = [{"_id": "2026-06-01", "summaries_count": 2, "summary_tokens": 30}]
        out = merge_daily(tasks, summaries)
        d1 = next(d for d in out if d["date"] == "2026-06-01")
        assert d1["summaries_count"] == 2 and d1["summary_tokens"] == 30
        assert d1["total_tokens"] == 130  # 100 + 30
        # 有 task 無 summary 的日期 → summary 欄位歸 0
        d2 = next(d for d in out if d["date"] == "2026-06-02")
        assert d2["summaries_count"] == 0 and d2["summary_tokens"] == 0
        assert d2["total_tokens"] == 50

    def test_summary_only_date_is_dropped(self):
        # 保留原行為：只遍歷 task 日期，summary-only 日期不會出現
        tasks = [{"_id": "2026-06-01", "tasks_count": 1, "punctuation_tokens": 10}]
        summaries = [{"_id": "2026-06-09", "summaries_count": 9, "summary_tokens": 999}]
        out = merge_daily(tasks, summaries)
        assert [d["date"] for d in out] == ["2026-06-01"]


class TestMergeTopUsers:
    def test_resorts_by_total_tokens_not_task_count(self):
        # 輸入按 tasks_count 排序（u1 任務最多），但 u2 token 最多 → 輸出須按 total_tokens
        user_tasks = [
            {"_id": "u1", "tasks_count": 10, "punctuation_tokens": 50},
            {"_id": "u2", "tasks_count": 3, "punctuation_tokens": 500},
        ]
        user_summaries = [{"_id": "u2", "summaries_count": 1, "summary_tokens": 200}]
        out = merge_top_users(user_tasks, user_summaries)
        assert [u["user_id"] for u in out] == ["u2", "u1"]  # u2: 700, u1: 50
        assert out[0]["total_tokens"] == 700
        assert out[0]["summaries_count"] == 1
        assert out[1]["summary_tokens"] == 0  # u1 無 summary

    def test_truncates_to_top_10(self):
        user_tasks = [
            {"_id": f"u{i}", "tasks_count": i, "punctuation_tokens": i * 10}
            for i in range(1, 15)  # 14 users
        ]
        out = merge_top_users(user_tasks, [])
        assert len(out) == 10
        # 最高 token（u14=140）在最前
        assert out[0]["user_id"] == "u14"


class TestFormatters:
    def test_named_counts_maps_id_to_label_with_null_default(self):
        stats = [{"_id": "gemini", "count": 5}, {"_id": None, "count": 2}]
        out = format_named_counts(stats, key="model", default="未知")
        assert out == [{"model": "gemini", "count": 5}, {"model": "未知", "count": 2}]

    def test_named_counts_provider_default(self):
        out = format_named_counts([{"_id": None, "count": 9}], key="provider", default="none")
        assert out == [{"provider": "none", "count": 9}]

    def test_performance_rounds_and_defaults_zero(self):
        assert format_performance({"avg_duration": 12.345, "min_duration": 1.0, "max_duration": 9.99}) == {
            "avg_duration_seconds": 12.35, "min_duration_seconds": 1.0, "max_duration_seconds": 9.99,
        }
        # 空 dict（無完成任務）→ 全 0，不報錯
        assert format_performance({}) == {
            "avg_duration_seconds": 0, "min_duration_seconds": 0, "max_duration_seconds": 0,
        }


_PRICES = {"basic": {"monthly": 100, "yearly": 1000}, "pro": {"monthly": 300, "yearly": 3000}}


def _price_of(tier, cycle):
    return _PRICES.get(tier, {}).get(cycle)


class TestSummarizeSubscriptions:
    def test_mrr_normalizes_yearly_to_monthly(self):
        sub_list = [
            {"_id": {"tier": "basic", "billing_cycle": "monthly"}, "count": 2},
            {"_id": {"tier": "pro", "billing_cycle": "yearly"}, "count": 1},
        ]
        counts, mrr = summarize_subscriptions(sub_list, _price_of)
        assert counts["basic_monthly"] == 2 and counts["pro_yearly"] == 1
        assert counts["pro_monthly"] == 0  # 未出現的 key 仍歸 0
        assert mrr == 100 * 2 + (3000 / 12) * 1  # 月繳原價、年繳/12

    def test_unpriced_tier_skipped_from_mrr(self):
        sub_list = [{"_id": {"tier": "enterprise", "billing_cycle": "monthly"}, "count": 9}]
        counts, mrr = summarize_subscriptions(sub_list, _price_of)
        assert mrr == 0                       # price_of 回 None → 不計入
        assert all(v == 0 for v in counts.values())


class TestFormatRecentOrders:
    def test_joins_email_and_defaults_missing_fields(self):
        raw = [
            {"merchant_order_no": "SL1", "user_id": "u1", "amount_twd": 300, "type": "subscription", "tier": "pro", "paid_at": 111},
            {"user_id": "u2"},  # 缺大部分欄位
        ]
        email_map = {"u1": "a@x.com"}
        out = format_recent_orders(raw, email_map)
        assert out[0] == {"order_no": "SL1", "user_email": "a@x.com", "amount": 300,
                          "type": "subscription", "tier": "pro", "paid_at": 111}
        assert out[1]["user_email"] == ""     # u2 不在 email_map
        assert out[1]["order_no"] == "" and out[1]["amount"] == 0
