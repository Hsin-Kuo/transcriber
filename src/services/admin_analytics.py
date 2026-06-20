"""AdminAnalytics — 後台統計的 aggregation + merge/derive。

把原本埋在 admin.py `/statistics` endpoint 裡的 3-collection aggregation 與 Python 端
合併/衍生邏輯收斂於此。分兩層：
  - 純函式（本檔上半）：吃 aggregation 結果 dict、回 response 區塊；無 Mongo，可快速 unit test。
  - AdminAnalytics(db)（下半）：跑 pipeline 的 orchestration + 組 full_report()。

詳見 CONTEXT.md「後台統計」。
"""
from datetime import datetime, timedelta, timezone

TZ_UTC8 = timezone(timedelta(hours=8))


# ── 純函式（無 Mongo；統計的 merge / derive 邏輯）──────────────────────────────

def derive_overview(
    *,
    total_tasks: int,
    completed_tasks: int,
    processing_tasks: int,
    failed_tasks: int,
    total_users: int,
    active_users: int,
) -> dict:
    """總覽區塊：計數 + success_rate（除零保護）。"""
    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "processing_tasks": processing_tasks,
        "failed_tasks": failed_tasks,
        "success_rate": round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0,
        "total_users": total_users,
        "active_users": active_users,
    }


def merge_daily(daily_tasks_stats: list, daily_summaries_stats: list) -> list:
    """每日統計：以 task 日期為主軸，合併同日 summary。

    保留原行為——只遍歷有 task 的日期；summary-only 的日期不出現在結果。
    """
    summary_map = {s["_id"]: s for s in daily_summaries_stats}
    out = []
    for t in daily_tasks_stats:
        date = t["_id"]
        s = summary_map.get(date, {})
        punct_tokens = t["punctuation_tokens"]
        summary_tokens = s.get("summary_tokens", 0)
        out.append({
            "date": date,
            "tasks_count": t["tasks_count"],
            "summaries_count": s.get("summaries_count", 0),
            "punctuation_tokens": punct_tokens,
            "summary_tokens": summary_tokens,
            "total_tokens": punct_tokens + summary_tokens,
        })
    return out


def merge_top_users(user_tasks_stats: list, user_summary_stats: list, *, limit: int = 10) -> list:
    """合併使用者 task / summary token，按 total_tokens 由高到低取 top-N。

    輸入 user_tasks_stats 原本按 tasks_count 排序；這裡依 total_tokens 重排再截斷。
    """
    summary_map = {s["_id"]: s for s in user_summary_stats}
    merged = []
    for u in user_tasks_stats:
        user_id = u["_id"]
        s = summary_map.get(user_id, {})
        punct_tokens = u["punctuation_tokens"]
        summary_tokens = s.get("summary_tokens", 0)
        merged.append({
            "user_id": user_id,
            "tasks_count": u["tasks_count"],
            "summaries_count": s.get("summaries_count", 0),
            "punctuation_tokens": punct_tokens,
            "summary_tokens": summary_tokens,
            "total_tokens": punct_tokens + summary_tokens,
        })
    merged.sort(key=lambda x: x["total_tokens"], reverse=True)
    return merged[:limit]


def _safe_avg(total: float, count: int) -> float:
    """total/count，round 2 位；count 為 0 回 0（除零保護）。"""
    return round(total / count, 2) if count > 0 else 0


def format_named_counts(stats: list, *, key: str, default: str) -> list:
    """把 `[{_id, count}]` 的 aggregation 結果轉成 `[{<key>: label, count}]`；_id 為 None 用 default。"""
    return [{key: (s["_id"] or default), "count": s["count"]} for s in stats]


def format_performance(duration_stats: dict) -> dict:
    """平均處理時間區塊：round 2 位，缺值（無完成任務）回 0。"""
    return {
        "avg_duration_seconds": round(duration_stats.get("avg_duration", 0), 2),
        "min_duration_seconds": round(duration_stats.get("min_duration", 0), 2),
        "max_duration_seconds": round(duration_stats.get("max_duration", 0), 2),
    }


def combine_token_usage(punct_stats: dict, summary_stats: dict) -> dict:
    """token 使用區塊：標點（tasks）+ AI 總結（summaries）兩來源合計 + 各自平均。"""
    p_total = punct_stats.get("total_tokens", 0)
    s_total = summary_stats.get("total_tokens", 0)
    p_count = punct_stats.get("tasks_with_tokens", 0)
    s_count = summary_stats.get("summaries_with_tokens", 0)
    return {
        "total_tokens": p_total + s_total,
        "prompt_tokens": punct_stats.get("total_prompt_tokens", 0) + summary_stats.get("total_prompt_tokens", 0),
        "completion_tokens": punct_stats.get("total_completion_tokens", 0) + summary_stats.get("total_completion_tokens", 0),
        "punctuation": {
            "total_tokens": p_total,
            "prompt_tokens": punct_stats.get("total_prompt_tokens", 0),
            "completion_tokens": punct_stats.get("total_completion_tokens", 0),
            "tasks_count": p_count,
            "avg_tokens_per_task": _safe_avg(p_total, p_count),
        },
        "summary": {
            "total_tokens": s_total,
            "prompt_tokens": summary_stats.get("total_prompt_tokens", 0),
            "completion_tokens": summary_stats.get("total_completion_tokens", 0),
            "summaries_count": s_count,
            "avg_tokens_per_summary": _safe_avg(s_total, s_count),
        },
    }


def summarize_subscriptions(sub_list: list, price_of) -> tuple:
    """訂閱分佈 + MRR。price_of(tier, cycle)->價格(或 None)，注入以免耦合 NewebpayService。

    回 (subscriber_count, mrr)。年繳價格 /12 換算成月，未定價 tier 不計入 MRR。
    只追蹤 basic/pro × monthly/yearly 四個 subscriber_count key；其餘 tier 仍計入 MRR。
    """
    subscriber_count = {
        "basic_monthly": 0, "basic_yearly": 0,
        "pro_monthly": 0, "pro_yearly": 0,
    }
    mrr = 0
    for item in sub_list:
        tier = item["_id"].get("tier", "")
        cycle = item["_id"].get("billing_cycle", "")
        key = f"{tier}_{cycle}"
        if key in subscriber_count:
            subscriber_count[key] = item["count"]
        price = price_of(tier, cycle)
        if price:
            monthly = price / 12 if cycle == "yearly" else price
            mrr += monthly * item["count"]
    return subscriber_count, mrr


def format_recent_orders(recent_raw: list, email_map: dict) -> list:
    """近期已付款訂單列表：join user email、補齊缺漏欄位。"""
    return [{
        "order_no": o.get("merchant_order_no", ""),
        "user_email": email_map.get(o.get("user_id", ""), ""),
        "amount": o.get("amount_twd", 0),
        "type": o.get("type", ""),
        "tier": o.get("tier", ""),
        "paid_at": o.get("paid_at"),
    } for o in recent_raw]


# ── orchestration（跑 pipeline + 用上面的純函式組 report）──────────────────────

_EMPTY_TOKENS = {
    "total_tokens": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0,
}


def _thirty_days_ago_ts() -> int:
    """30 天前（以 UTC+8 當天 00:00 起算）的 Unix timestamp（秒）。"""
    dt = datetime.now(TZ_UTC8).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    return int(dt.timestamp())


def _daily_group(date_field: str, count_key: str, token_path: str, token_key: str, cutoff_ts: int) -> list:
    """每日統計 pipeline（UTC+8 分日）。cutoff_ts 由呼叫端算一次傳入（兩條 pipeline 共用同一界線）。"""
    return [
        {"$match": {date_field: {"$gte": cutoff_ts}}},
        {"$group": {
            "_id": {"$dateToString": {
                "format": "%Y-%m-%d",
                "date": {"$toDate": {"$multiply": [f"${date_field}", 1000]}},
                "timezone": "+08:00",
            }},
            count_key: {"$sum": 1},
            token_key: {"$sum": {"$ifNull": [f"${token_path}", 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]


def _model_group(field: str) -> list:
    return [
        {"$match": {field: {"$exists": True, "$ne": None}}},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]


class AdminAnalytics:
    """後台統計：跑 3-collection aggregation，組成 /statistics 回應。"""

    def __init__(self, db):
        self.db = db

    async def _agg(self, collection, pipeline, *, one: bool = False, default: dict = None):
        cursor = collection.aggregate(pipeline)
        rows = await cursor.to_list(length=1 if one else None)
        if one:
            return rows[0] if rows else dict(default or {})
        return rows

    async def full_report(self) -> dict:
        db = self.db

        # 1/8 計數
        total_tasks = await db.tasks.count_documents({})
        completed_tasks = await db.tasks.count_documents({"status": "completed"})
        processing_tasks = await db.tasks.count_documents({"status": "processing"})
        failed_tasks = await db.tasks.count_documents({"status": "failed"})
        total_users = await db.users.count_documents({})
        active_users = await db.users.count_documents({"is_active": True})

        # 2 token 使用
        punct_tokens = await self._agg(db.tasks, [
            {"$match": {"stats.token_usage.total": {"$exists": True, "$ne": None}}},
            {"$group": {
                "_id": None,
                "total_tokens": {"$sum": "$stats.token_usage.total"},
                "total_prompt_tokens": {"$sum": "$stats.token_usage.prompt"},
                "total_completion_tokens": {"$sum": "$stats.token_usage.completion"},
                "tasks_with_tokens": {"$sum": 1},
            }},
        ], one=True, default={**_EMPTY_TOKENS, "tasks_with_tokens": 0})
        summary_tokens = await self._agg(db.summaries, [
            {"$match": {"metadata.token_usage.total": {"$exists": True, "$ne": None}}},
            {"$group": {
                "_id": None,
                "total_tokens": {"$sum": "$metadata.token_usage.total"},
                "total_prompt_tokens": {"$sum": "$metadata.token_usage.prompt"},
                "total_completion_tokens": {"$sum": "$metadata.token_usage.completion"},
                "summaries_with_tokens": {"$sum": 1},
            }},
        ], one=True, default={**_EMPTY_TOKENS, "summaries_with_tokens": 0})

        # 3 模型使用
        punct_models = await self._agg(db.tasks, _model_group("models.punctuation"))
        trans_models = await self._agg(db.tasks, _model_group("models.transcription"))
        diar_models = await self._agg(db.tasks, _model_group("models.diarization"))
        summary_models = await self._agg(db.summaries, _model_group("metadata.model"))

        # 4 每日統計（兩條 pipeline 共用同一個 30 天界線）
        cutoff = _thirty_days_ago_ts()
        daily_tasks = await self._agg(db.tasks, _daily_group(
            "timestamps.created_at", "tasks_count", "stats.token_usage.total", "punctuation_tokens", cutoff))
        daily_summaries = await self._agg(db.summaries, _daily_group(
            "created_at", "summaries_count", "metadata.token_usage.total", "summary_tokens", cutoff))

        # 5 top users
        user_tasks = await self._agg(db.tasks, [
            {"$group": {
                "_id": "$user.user_id",
                "tasks_count": {"$sum": 1},
                "punctuation_tokens": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}},
            }},
            {"$sort": {"tasks_count": -1}},
            {"$limit": 20},
        ])
        user_summaries = await self._agg(db.summaries, [
            {"$lookup": {"from": "tasks", "localField": "_id", "foreignField": "_id", "as": "task_info"}},
            {"$unwind": {"path": "$task_info", "preserveNullAndEmptyArrays": True}},
            {"$group": {
                "_id": "$task_info.user.user_id",
                "summaries_count": {"$sum": 1},
                "summary_tokens": {"$sum": {"$ifNull": ["$metadata.token_usage.total", 0]}},
            }},
        ])

        # 6 平均處理時間
        duration = await self._agg(db.tasks, [
            {"$match": {"status": "completed", "stats.duration_seconds": {"$exists": True, "$ne": None}}},
            {"$group": {
                "_id": None,
                "avg_duration": {"$avg": "$stats.duration_seconds"},
                "min_duration": {"$min": "$stats.duration_seconds"},
                "max_duration": {"$max": "$stats.duration_seconds"},
            }},
        ], one=True, default={"avg_duration": 0, "min_duration": 0, "max_duration": 0})

        # 7 標點服務使用
        punct_providers = await self._agg(db.tasks, [
            {"$group": {"_id": "$config.punct_provider", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ])

        return {
            "overview": derive_overview(
                total_tasks=total_tasks, completed_tasks=completed_tasks,
                processing_tasks=processing_tasks, failed_tasks=failed_tasks,
                total_users=total_users, active_users=active_users,
            ),
            "token_usage": combine_token_usage(punct_tokens, summary_tokens),
            "model_usage": {
                "punctuation": format_named_counts(punct_models, key="model", default="未知"),
                "transcription": format_named_counts(trans_models, key="model", default="未知"),
                "diarization": format_named_counts(diar_models, key="model", default="未知"),
                "summary": format_named_counts(summary_models, key="model", default="未知"),
            },
            "daily_stats": merge_daily(daily_tasks, daily_summaries),
            "top_users": merge_top_users(user_tasks, user_summaries),
            "performance": format_performance(duration),
            "punct_provider_usage": format_named_counts(punct_providers, key="provider", default="none"),
        }

    async def revenue(self) -> dict:
        """營收 dashboard：MRR / 訂閱分佈 / 總收入 / 近 6 月 / 近期訂單 / 流失指標。"""
        from bson import ObjectId
        from ..utils.newebpay_service import NewebpayService
        from ..utils.time_utils import get_utc_timestamp

        db = self.db
        now = get_utc_timestamp()

        # 1 訂閱分佈 + MRR（price 注入 → summarize 不耦合 NewebpayService）
        sub_list = await self._agg(db.users, [
            {"$match": {"subscription.status": "active"}},
            {"$group": {
                "_id": {"tier": "$subscription.tier", "billing_cycle": "$subscription.billing_cycle"},
                "count": {"$sum": 1},
            }},
        ])
        subscriber_count, mrr = summarize_subscriptions(sub_list, NewebpayService.get_subscription_price)

        # 2 總收入 / 3 額外額度收入
        total = await self._agg(db.orders, [
            {"$match": {"status": "paid"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount_twd"}}},
        ], one=True, default={"total": 0})
        extra = await self._agg(db.orders, [
            {"$match": {"status": "paid", "type": "extra_quota"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount_twd"}}},
        ], one=True, default={"total": 0})

        # 4 近 6 個月月收入
        six_months_ago = now - (180 * 86400)
        monthly_list = await self._agg(db.orders, [
            {"$match": {"status": "paid", "paid_at": {"$gte": six_months_ago}}},
            {"$addFields": {"paid_date": {"$toDate": {"$multiply": ["$paid_at", 1000]}}}},
            {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$paid_date"}}, "amount": {"$sum": "$amount_twd"}}},
            {"$sort": {"_id": -1}},
            {"$limit": 6},
        ])
        monthly_revenue = [{"month": m["_id"], "amount": m["amount"]} for m in monthly_list]

        # 5 近 10 筆已付款訂單 + join email
        recent_raw = await db.orders.find(
            {"status": "paid"},
            {"merchant_order_no": 1, "amount_twd": 1, "type": 1, "tier": 1, "user_id": 1, "paid_at": 1},
        ).sort("paid_at", -1).limit(10).to_list(length=10)
        user_ids = list({o.get("user_id") for o in recent_raw if o.get("user_id")})
        email_map = {}
        if user_ids:
            async for u in db.users.find(
                {"_id": {"$in": [ObjectId(uid) for uid in user_ids]}}, {"email": 1}
            ):
                email_map[str(u["_id"])] = u.get("email", "")
        recent_orders = format_recent_orders(recent_raw, email_map)

        # 6 流失指標（「本月」以日曆月初為界，非滾動 30 天）
        pending_cancel = await db.users.count_documents({
            "subscription.status": "active",
            "subscription.cancel_at_period_end": True,
        })
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        month_start = int(datetime(now_dt.year, now_dt.month, 1, tzinfo=timezone.utc).timestamp())
        expired_this_month = await db.users.count_documents({
            "subscription.status": {"$in": ["expired", "past_due"]},
            "subscription.current_period_end": {"$gte": month_start, "$lt": now},
        })

        return {
            "mrr": int(mrr),
            "subscriber_count": subscriber_count,
            "total_revenue": total.get("total", 0),
            "monthly_revenue": monthly_revenue,
            "recent_orders": recent_orders,
            "churn": {"pending_cancel": pending_cancel, "expired_this_month": expired_this_month},
            "extra_quota_revenue": extra.get("total", 0),
        }


def build_admin_analytics(db) -> AdminAnalytics:
    return AdminAnalytics(db)
