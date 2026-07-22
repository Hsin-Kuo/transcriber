"""LLM API 定價表 + 成本試算純函式。

用途：後台 AI 成本統計（標點強化 punctuation / AI 摘要 summary 的 token → USD）。

設計：
  - 純資料 + 純函式，無 Mongo、無 I/O，可快速 unit test。
  - 單價集中於 `PRICING`，別把數字散落在 aggregation 邏輯裡。
  - 定價「會變動」：Google / OpenAI 皆不定期調價。更新時只改本檔並更新
    下方 `PRICING_VERIFIED_AT`，其餘計算不受影響。

計價假設（重要，會影響金額正確性）：
  - **文字級距**：標點與摘要都是「文字 in / 文字 out」，故 Gemini input 採 text 價，
    非 audio 價（audio input 較貴，但本專案不餵音訊 token 給 Gemini）。
  - **gemini-2.5-pro 採 ≤200k prompt 級距**：實際呼叫是分段（chunk）送出，單次
    prompt 遠低於 200k；DB 內存的是整篇「累加值」，若據此判 >200k 會誤用高價級距
    而高估成本，故一律用低價級距。
  - **標準即時呼叫**：不套用 cached input / Batch API 的折扣檔位。

單價來源（USD / 1,000,000 tokens）：
  - Gemini：https://ai.google.dev/gemini-api/docs/pricing
  - gpt-4o-mini：https://developers.openai.com/api/docs/models/gpt-4o-mini
"""
from typing import Optional

PRICING_VERIFIED_AT = "2026-07-20"

# 每 1,000,000 tokens 的美金單價（input=prompt、output=completion）。
PRICING = {
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},   # ≤200k prompt 級距
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

# 別名 → 具體版本。程式碼中的 fallback 清單含 *-latest 別名（會被 Google hot-swap），
# 這裡對應到目前指向的實際模型以便計價；若 Google 改指向，更新此表。
ALIASES = {
    "gemini-flash-latest": "gemini-2.5-flash",
    "gemini-flash-lite-latest": "gemini-2.5-flash-lite",
}

_PER_MILLION = 1_000_000


def resolve_model(model: Optional[str]) -> Optional[str]:
    """把別名正規化成定價表用的具體模型名。"""
    if not model:
        return model
    return ALIASES.get(model, model)


def price_of(model: Optional[str]) -> Optional[dict]:
    """回該模型的 {input, output} 單價；未收錄回 None。"""
    return PRICING.get(resolve_model(model))


def cost_usd(
    model: Optional[str],
    prompt_tokens: int,
    completion_tokens: int,
) -> Optional[float]:
    """依模型單價把 prompt / completion tokens 換算成美金成本。

    未收錄的模型回 None（呼叫端須視為「無法計價」，不可當 0，以免靜默低估）。
    """
    price = price_of(model)
    if price is None:
        return None
    return (
        prompt_tokens / _PER_MILLION * price["input"]
        + completion_tokens / _PER_MILLION * price["output"]
    )


def pricing_table_for_response() -> dict:
    """組成 API 回應用的定價區塊（含幣別、級距、查證日期等 caveat）。"""
    return {
        "unit": "USD per 1,000,000 tokens",
        "verified_at": PRICING_VERIFIED_AT,
        "models": PRICING,
        "aliases": ALIASES,
        "assumptions": [
            "Gemini input 採 text 級距（非 audio）",
            "gemini-2.5-pro 採 ≤200k prompt 級距",
            "不套用 cached input / Batch API 折扣",
        ],
    }
