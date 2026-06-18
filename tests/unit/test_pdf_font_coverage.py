"""PDF 字型涵蓋 fallback 測試（修簡體字在 NotoSansTC 缺字 → 豆腐）。

NotoSansTC 不含部分簡體字（这/简…），但程式碼把所有漢字都依 primary_lang 導到 TC →
那些字變豆腐。resolve_font 逐字檢查涵蓋、缺則 fallback 到有的字型（SC 是 superset）。
用合成涵蓋表測純邏輯，不依賴字型檔 / ReportLab。
"""
import pytest

from src.utils.pdf import script_detect as sd


@pytest.fixture
def coverage():
    """隔離 module 全域 _FONT_COVERAGE：測試前清空、測試後還原。"""
    saved = dict(sd._FONT_COVERAGE)
    sd._FONT_COVERAGE.clear()
    yield
    sd._FONT_COVERAGE.clear()
    sd._FONT_COVERAGE.update(saved)


def test_preferred_font_used_when_it_covers(coverage):
    sd.register_font_coverage(sd.FONT_TC, {ord("學"), ord("這")})
    sd.register_font_coverage(sd.FONT_SC, {ord("學"), ord("這"), ord("这")})
    assert sd.resolve_font(sd.FONT_TC, ord("學")) == sd.FONT_TC


def test_fallback_to_superset_when_preferred_lacks_glyph(coverage):
    # TC 缺「这」、SC 有 → 應 fallback 到 SC（修豆腐的核心）
    sd.register_font_coverage(sd.FONT_TC, {ord("學")})
    sd.register_font_coverage(sd.FONT_SC, {ord("學"), ord("这"), ord("简")})
    assert sd.resolve_font(sd.FONT_TC, ord("这")) == sd.FONT_SC
    assert sd.resolve_font(sd.FONT_TC, ord("简")) == sd.FONT_SC


def test_empty_coverage_keeps_preferred(coverage):
    # 涵蓋表未建立（理論上 preload 後才用）→ 不退化，回首選
    assert sd.resolve_font(sd.FONT_TC, ord("这")) == sd.FONT_TC


def test_no_font_covers_returns_preferred(coverage):
    # 所有字型都沒有 → 回首選（會顯示豆腐，但已盡力；不另外炸）
    sd.register_font_coverage(sd.FONT_TC, {ord("a")})
    sd.register_font_coverage(sd.FONT_SC, {ord("a")})
    assert sd.resolve_font(sd.FONT_TC, ord("𠀀")) == sd.FONT_TC


def test_wrap_text_uses_fallback_font_per_char(coverage):
    sd.register_font_coverage(sd.FONT_TC, {ord("繁"), ord("體")})
    sd.register_font_coverage(sd.FONT_SC, {ord("繁"), ord("體"), ord("这")})
    out = sd.wrap_text_with_font_tags("繁體这", "zh-TW")
    assert '<font name="NotoSansTC">繁體</font>' in out  # TC 字 → TC
    assert '<font name="NotoSansSC">这</font>' in out      # TC 缺 → fallback SC
