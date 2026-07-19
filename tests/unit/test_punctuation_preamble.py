"""標點階段 LLM 前言剝除（_strip_llm_preamble）與各回應處理點的掛載測試。

使用者回報實例：LLM 在逐字稿前加開場白（「好的，這是為您潤飾後的逐字稿，……：」）。
雙層防禦：prompt 明令禁止 + 後處理守門（保守雙關鍵詞規則，防誤傷正文）。
"""
from src.services.utils.punctuation_processor import PunctuationProcessor

# 使用者回報的實際前言
REPORTED_PREAMBLE = "好的，這是為您潤飾後的逐字稿，已完成中文標點補全與合理分段，並保留了所有原文內容："

BODY = "[SPEAKER_00] 今天我們來討論一下產品的規劃。\n\n[SPEAKER_01] 好，我先講第一點。"


def _proc():
    return PunctuationProcessor()


# ── _strip_llm_preamble 純函數行為 ──────────────────────────────────────

def test_reported_preamble_is_stripped_and_body_preserved():
    text = f"{REPORTED_PREAMBLE}\n\n{BODY}"

    out = _proc()._strip_llm_preamble(text)

    assert out == BODY


def test_normal_output_with_speaker_label_untouched():
    # 正常輸出（含 [SPEAKER_00] 開頭）→ 零改動
    assert _proc()._strip_llm_preamble(BODY) == BODY


def test_plain_normal_output_untouched():
    # 無 speaker 標籤的一般正文也零改動（首行無冒號結尾）
    text = "今天我們來討論一下產品的規劃。\n\n好，我先講第一點。"
    assert _proc()._strip_llm_preamble(text) == text


def test_content_line_with_verb_but_no_domain_word_kept():
    # 疑似但非前言的真實內容：「以下是今天的重點：」有動詞（以下是）無領域詞 → 保留
    text = "以下是今天的重點：\n\n第一，產品時程。\n第二，人力配置。"
    assert _proc()._strip_llm_preamble(text) == text


def test_content_line_with_domain_word_but_no_verb_kept():
    # 有領域詞（逐字稿）無前言動詞 → 保留（雙關鍵詞缺一不剝）
    text = "逐字稿整理注意事項：\n\n請大家會後補充。"
    assert _proc()._strip_llm_preamble(text) == text


def test_preamble_line_containing_speaker_tag_kept():
    # 即使動詞+領域詞+冒號都中，含 [SPEAKER_ 的行屬正文 → 保留
    text = "[SPEAKER_00] 好的，這是為您潤飾後的逐字稿，標點如下：\n後續內容。"
    assert _proc()._strip_llm_preamble(text) == text


def test_markdown_fence_stripped_in_pairs():
    text = f"```text\n{BODY}\n```"
    assert _proc()._strip_llm_preamble(text) == BODY

    # 只有開頭圍欄、沒有結尾 → 不成對，不剝
    text_unpaired = f"```text\n{BODY}"
    assert _proc()._strip_llm_preamble(text_unpaired) == text_unpaired


def test_fence_and_preamble_combined():
    text = f"```\n{REPORTED_PREAMBLE}\n\n{BODY}\n```"
    assert _proc()._strip_llm_preamble(text) == BODY


def test_trailing_lines_never_stripped():
    # 刻意不剝結尾行：正文最後一句幾乎都以句號收尾，且與 LLM 結尾註記無法
    # 可靠區分（「以上就是我們整理逐字稿的方法。」是真實內容）——誤刪代價
    # 高於留下罕見註記，結尾只靠 prompt 禁令。兩種樣態都必須原樣保留。
    for tail in (
        "以上是為您潤飾後的逐字稿，已完成標點補全。",  # 真的像 LLM 註記
        "以上就是我們整理逐字稿的方法。",  # 真實內容
        "以上就是今天的會議內容。",
    ):
        text = f"{BODY}\n\n{tail}"
        assert _proc()._strip_llm_preamble(text) == text


def test_english_content_word_containing_sure_not_stripped():
    # 'measure' 不可 substring 命中 'Sure'（詞界 \b 防護）
    text = "We measure punctuation quality as follows:\n\nFirst, the accuracy."
    assert _proc()._strip_llm_preamble(text) == text


def test_empty_and_whitespace_input_safe():
    assert _proc()._strip_llm_preamble("") == ""
    assert _proc()._strip_llm_preamble("   \n  ") == ""


# ── 回應處理點掛載（mock LLM 回傳帶前言的內容）────────────────────────────

def test_gemini_single_shot_strips_preamble(monkeypatch):
    proc = _proc()
    llm_response = f"{REPORTED_PREAMBLE}\n\n{BODY}"
    monkeypatch.setattr(
        proc, "_call_gemini_with_retry",
        lambda prompt, max_output_tokens=None: (llm_response, "fake-gemini", None),
    )

    result, model, _usage = proc._punctuate_with_gemini(BODY, language="zh")

    assert result == BODY
    assert model == "fake-gemini"


def test_gemini_chunked_strips_preamble_in_every_chunk(monkeypatch):
    proc = _proc()
    # 每個 chunk 的回應都帶前言（含中段 chunk）——每個都要剝
    calls = []

    def fake_call(prompt, max_output_tokens=None):
        calls.append(prompt)
        # 從 prompt 尾端取回該 chunk 的原文（prompt 以 \n\n{chunk_text} 結尾）
        chunk_text = prompt.rsplit("\n\n", 1)[-1]
        return f"{REPORTED_PREAMBLE}\n\n{chunk_text}", "fake-gemini", None

    monkeypatch.setattr(proc, "_call_gemini_with_retry", fake_call)

    long_text = "\n".join(f"[SPEAKER_00] 第{i}句話的內容測試。" for i in range(20))
    result, _model, _usage = proc._punctuate_with_gemini(
        long_text, language="zh", chunk_size=100
    )

    assert len(calls) > 1  # 確實走了分段路徑（每 chunk 一次呼叫）
    assert REPORTED_PREAMBLE.rstrip("：") not in result
    assert "[SPEAKER_00] 第0句話的內容測試。" in result
    assert "[SPEAKER_00] 第19句話的內容測試。" in result


def test_openai_path_strips_preamble(monkeypatch):
    proc = _proc()
    llm_response = f"{REPORTED_PREAMBLE}\n\n{BODY}"

    class FakeMessage:
        content = llm_response

    class FakeChoice:
        message = FakeMessage()

    class FakeResp:
        choices = [FakeChoice()]
        usage = None

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda: FakeClient())

    result, model, _usage = proc._punctuate_with_openai(BODY, language="zh")

    assert result == BODY
    assert model == proc.openai_model
