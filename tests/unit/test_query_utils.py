"""safe_regex 測試（純函式，不需要 DB）。

這支 helper 是「使用者輸入 → Mongo $regex」的唯一入口，擋的是 ReDoS：
未 escape 的輸入等於讓呼叫端自帶 regex 語法，`(a+)+$` 這類 pattern 會觸發
catastrophic backtracking，在 DB 端燒 CPU。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.database.query_utils import MAX_SEARCH_LENGTH, safe_regex  # noqa: E402


class TestSafeRegex:
    def test_returns_none_for_blank_input(self):
        assert safe_regex(None) is None
        assert safe_regex("") is None
        assert safe_regex("   ") is None

    def test_builds_case_insensitive_condition(self):
        assert safe_regex("abc") == {"$regex": "abc", "$options": "i"}

    def test_strips_surrounding_whitespace(self):
        assert safe_regex("  abc  ")["$regex"] == "abc"

    def test_escapes_redos_pattern(self):
        """惡意 regex 必須變成字面字串，不能保留 regex 語意。"""
        assert safe_regex("(a+)+$")["$regex"] == re.escape("(a+)+$")

    def test_escapes_wildcards(self):
        """`.*` 不該變成萬用字元——否則搜尋語意也會錯，不只是安全問題。"""
        pattern = safe_regex(".*")["$regex"]
        assert pattern == re.escape(".*")
        assert re.fullmatch(pattern, "anything") is None

    def test_truncates_to_max_length(self):
        assert len(safe_regex("a" * 500)["$regex"]) == MAX_SEARCH_LENGTH

    def test_truncation_counts_chars_before_escaping(self):
        """截斷在 escape 前做——escape 後長度會膨脹，但上限管的是輸入字元數。"""
        assert len(safe_regex("(" * 500)["$regex"]) == MAX_SEARCH_LENGTH * 2

    def test_max_length_is_overridable(self):
        assert len(safe_regex("a" * 50, max_length=10)["$regex"]) == 10

    def test_cjk_passes_through_unescaped(self):
        """中文不是 regex metacharacter，escape 後應原樣保留。"""
        assert safe_regex("季度會議")["$regex"] == "季度會議"
