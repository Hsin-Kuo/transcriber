"""MongoDB 查詢條件的共用建構工具。

集中「使用者輸入 → Mongo 條件」的轉換，避免每個 repo/router 各寫一次
`{"$regex": user_input}` 這種容易漏掉 escape 的形狀。
"""
import re
from typing import Any, Dict, Optional

# 搜尋字串長度上限。過長的 pattern 除了無意義，也會放大 regex 掃描成本。
MAX_SEARCH_LENGTH = 100


def safe_regex(value: Optional[str], *, max_length: int = MAX_SEARCH_LENGTH) -> Optional[Dict[str, Any]]:
    """把使用者輸入轉成不分大小寫的「字面子字串」比對條件。

    一律 re.escape：使用者輸入若直接當 regex，像 `(a+)+$` 這種 pattern 會造成
    catastrophic backtracking，一次請求就能在 DB 端燒掉大量 CPU（ReDoS）。
    搜尋框要的是子字串比對，不是讓呼叫端自帶 regex 語法。

    Returns:
        可直接指派給欄位的條件 dict；輸入為空（或只有空白）時回傳 None，
        由呼叫端決定「不加這個條件」。
    """
    if not value:
        return None
    trimmed = value.strip()[:max_length]
    if not trimmed:
        return None
    return {"$regex": re.escape(trimmed), "$options": "i"}
