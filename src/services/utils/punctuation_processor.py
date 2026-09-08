"""
PunctuationProcessor - 標點符號處理器
職責：使用 AI 模型為轉錄文字添加標點符號
"""

from typing import Optional, Tuple, Dict, Any, Callable
import bisect
import os
import re

from src.utils.logger import get_logger
from src.utils.text_utils import (
    SPEAKER_LABEL_PATTERN,
    is_content_char,
    is_opening_punct,
)

log = get_logger(__name__)


# ── LLM 前言/結尾註記偵測（_strip_llm_preamble 用）────────────────────────
# 雙關鍵詞規則：一行要同時含「前言動詞」與「領域詞」才視為 LLM 客套話，缺一不剝——
# 避免誤傷正文（例：「以下是今天的重點：」有動詞無領域詞，屬真實內容，必須保留）。
_PREAMBLE_VERB_RE = re.compile(
    r"好的|這是|这是|以下是|以下為|以下为|以上是|以上為|以上为|以上就是"
    r"|為您|为您|已完成|已為|已为|幫您|帮您"
    r"|\bHere is\b|\bHere's\b|\bSure\b|\bCertainly\b|\bBelow is\b|\bAbove is\b"
    r"|以下が|こちらが|以上が|次のとおり"
    r"|다음은|여기에|이상이",
    re.IGNORECASE,
)
_PREAMBLE_DOMAIN_RE = re.compile(
    r"逐字稿|文字稿|潤飾|润饰|標點|标点|分段|轉錄|转录"
    r"|transcript|punctuat|paragraph"
    r"|文字起こし|句読点|段落"
    r"|전사|구두점|단락",
    re.IGNORECASE,
)
# markdown 圍欄開頭（``` 或 ```text 等變體）
_FENCE_OPEN_RE = re.compile(r"^```[A-Za-z0-9_\-]*$")

# ── 語者標籤保全（labels-never-reach-the-LLM）────────────────────────────
# 背景：標籤原本隨文字一起送進 Gemini，靠 prompt 請它「完整保留」。實測
# （gemini-2.5-flash-lite，2026-09）呈現劑量反應：chunk 內標籤 58~340 個時
# 保留率 100%，但只剩 1 個時兩次試驗都被整批刪光（0%）。長篇獨白正好落在
# 「標籤極少」那端，於是前半段語者標記全滅、後半段（密集問答）完好——這就是
# 使用者回報「一半之後才有語者」的成因。
# 對策：標籤根本不進 LLM。剝標籤 → 只把純文字送去標點 → 依字元對齊切回逐輪次
# → 重貼標籤。labels_out == labels_in 由構造保證，與模型行為無關。
# 標籤 pattern 單一來源在 text_utils；此處只套需要的 flags 編譯，避免手抄變體分歧。
_SPEAKER_TURN_PREFIX_RE = re.compile(
    rf"^({SPEAKER_LABEL_PATTERN})[ \t]?",
    re.IGNORECASE,
)
# 重貼後的結構性驗證用（只數行首標籤）——必須與上面的 prefix regex 同源，
# 否則 labels_lost 檢查會因為兩套 pattern 不一致而失去意義。
_SPEAKER_LABEL_COUNT_RE = re.compile(
    rf"^(?:{SPEAKER_LABEL_PATTERN})",
    re.IGNORECASE | re.MULTILINE,
)
# `_split_text_into_chunks` 找斷點用
_SPEAKER_LABEL_SEARCH_RE = re.compile(SPEAKER_LABEL_PATTERN, re.IGNORECASE)

# ── 輪次邊界對齊（切點錨點吸附）────────────────────────────────────────────
# 舊版切點純靠「累計內容字元數 × 全域 scale」。LLM 加標點時會**局部**刪贅字，
# 而 scale 是全域均值，兩者的差就是該邊界的越界量——實測 staging 任務：
# 漂浮段落有 82.8% 結束在句子中間（有標籤輪次只有 4.9%），越界量中位數 11 字。
# 對策：計數只當估計值，再吸附到 LLM 自己給的錨點（空行 > 句末標點）。
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_SENTENCE_END_CHARS = "。？！…；.?!;"
# 吸附窗口 = max(_ANCHOR_WINDOW_MIN, 片段長度 × _ANCHOR_WINDOW_RATIO)。
# 選值依據（e2e 重播 245 輪次、量測「輪次結尾落在句中」的比率）：
#   0.06/8 → 22.4% ; 0.10/12 → 9.8% ; 0.15/16 → 4.9% ; 0.20/20 → 3.3% ; 0.30/30 → 3.3%
# 取 0.15/16——曲線的膝點，剛好打到真實資料的 4.9% 基線。不取 0.20+ 的平台區：
# 窗口越寬，切點能被拉離字元估計值越遠，真實資料上錨點型態更雜時誤吸附的代價越大。
_ANCHOR_WINDOW_RATIO = 0.15
_ANCHOR_WINDOW_MIN = 16

# 輪次 body 內的換行（含上游 segments 自帶的）：`\n\n` 從此專職輪次分隔符，
# body 內部一律收掉，否則前端一切分就多出無標籤的漂浮段落。
_TURN_BODY_NEWLINE_RE = re.compile(r"[ \t]*[\r\n]+[ \t]*")
# 不用空白接續的語言（CJK）——拉丁語系換單一空格，否則會把單字黏起來
_NO_SPACE_LANGUAGES = ("zh", "zh-TW", "zh-CN", "ja", "ko")


class PunctuationProcessor:
    """標點符號處理器

    使用 Gemini 或 OpenAI 為轉錄文字添加標點符號和分段
    """

    def __init__(
        self,
        default_provider: str = "gemini",
        gemini_model: str = "gemini-2.5-flash-lite",
        openai_model: str = "gpt-4o-mini"
    ):
        """初始化 PunctuationProcessor

        Args:
            default_provider: 預設提供商（"gemini" 或 "openai"）
            gemini_model: Gemini 模型名稱
            openai_model: OpenAI 模型名稱
        """
        self.default_provider = default_provider
        self.gemini_model = gemini_model
        self.openai_model = openai_model

        # Gemini 備援模型列表（按優先順序）
        self.gemini_fallback_models = [
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-2.5-pro",
        ]

    def process(
        self,
        text: str,
        provider: Optional[str] = None,
        language: str = "zh",
        chunk_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """處理文字，添加標點符號和分段

        Args:
            text: 要處理的文字
            provider: API 提供商（"gemini" 或 "openai"），None 使用預設
            language: 語言代碼（zh/en/ja/ko 等）
            chunk_size: 分段大小（字元數），None 則自動決定
            progress_callback: 進度回調函數 callback(current_chunk, total_chunks)

        Returns:
            (處理後的文字, 使用的模型名稱, token_usage) 元組
            token_usage: {"total": int, "prompt": int, "completion": int} 或 None
        """
        provider = provider or self.default_provider

        # 語者標籤保全在 provider 分派「之上」——兩個 provider 共用，
        # 否則 punct_provider='openai'（routers 白名單允許）仍會把標籤送進 LLM。
        turns = self._parse_speaker_turns(text)
        if turns is not None:
            return self._punctuate_speaker_turns(
                turns, provider, language, chunk_size, progress_callback
            )

        return self._punctuate_plain(
            text, provider, language, chunk_size, progress_callback
        )

    def _punctuate_plain(
        self,
        text: str,
        provider: str,
        language: str,
        chunk_size: Optional[int],
        progress_callback: Optional[Callable[[int, int], None]],
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """無標籤文字的原有分派路徑（行為未變）。"""
        if provider == "openai":
            return self._punctuate_with_openai(text, language)
        return self._punctuate_with_gemini(
            text, language, chunk_size, progress_callback
        )

    # ========== 私有方法 ==========

    def _estimate_max_output_tokens(self, input_text: str, language: str) -> int:
        """估算標點處理的合理輸出 token 上限，防止 LLM 重複迴圈跑滿 65k tokens。

        標點處理輸出最多比輸入長 20-30%，留 buffer 後 cap 在 60000。
        """
        char_count = len(input_text)
        if language in ("zh", "zh-TW", "zh-CN", "ja", "ko"):
            estimated = int(char_count * 1.6) + 500
        else:
            estimated = int(char_count * 0.5) + 500
        return min(estimated, 60000)

    def _is_output_exploded(self, input_text: str, output_text: str) -> bool:
        """偵測 Gemini 輸出是否異常膨脹（疑似 LLM 重複迴圈）。"""
        if not input_text or not output_text:
            return False
        return len(output_text) > len(input_text) * 1.5

    def _strip_llm_preamble(self, text: str) -> str:
        """剝除 LLM 回應的開場白/結尾註記/markdown 圍欄（保守規則，防誤傷正文）。

        實例（使用者回報）：「好的，這是為您潤飾後的逐字稿，已完成中文標點補全與
        合理分段，並保留了所有原文內容：」——prompt 已明令禁止，此處是後處理守門。

        規則：
        - markdown 圍欄：開頭 ```（含 ```text 等變體）與結尾 ``` 「成對」才剝。
        - 前言行：僅當「第一個非空行」同時滿足 (a) 以全形/半形冒號結尾
          (b) 含前言動詞 (c) 含領域詞 (d) 不含 "[SPEAKER_" → 移除該行與其後連續空行。
        - 結尾註記：「最後一個非空行」同時滿足 (b)+(c)+(d) 且以標點結尾
          （「以上是……」變體多以句號/冒號收尾）→ 移除該行與其前連續空行。
        雙關鍵詞（動詞+領域詞）缺一不剝——「以下是今天的重點：」這類真實內容不受影響。
        """
        if not text:
            return text

        lines = text.split("\n")

        def _first_nonempty() -> int:
            for i, line in enumerate(lines):
                if line.strip():
                    return i
            return -1

        def _last_nonempty() -> int:
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip():
                    return i
            return -1

        # 1. markdown 圍欄（成對才剝）
        fi, li = _first_nonempty(), _last_nonempty()
        if (
            fi != -1 and li != -1 and fi < li
            and _FENCE_OPEN_RE.match(lines[fi].strip())
            and lines[li].strip() == "```"
        ):
            del lines[li]
            del lines[fi]

        # 2. 前言行（第一個非空行，四條件全中才剝）
        fi = _first_nonempty()
        if fi != -1:
            line = lines[fi].strip()
            if (
                line.endswith((":", "："))
                and "[SPEAKER_" not in line
                and _PREAMBLE_VERB_RE.search(line)
                and _PREAMBLE_DOMAIN_RE.search(line)
            ):
                j = fi + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                lines = lines[:fi] + lines[j:]

        # 不剝結尾註記：正文最後一句幾乎都以句號收尾，且「以上就是我們整理
        # 逐字稿的方法。」這類真實內容與 LLM 結尾註記在規則層面無法可靠區分
        # ——誤刪正文的代價高於留下罕見註記。結尾行為只靠 prompt 禁令約束；
        # 若日後有實證案例再依樣本設計規則。
        return "\n".join(lines).strip()

    def _remove_cjk_latin_spaces(self, text: str) -> str:
        """移除中英文、全形標點與英文之間被 AI 擅自插入的空白"""
        # 中文字與英文/數字之間的空白
        text = re.sub(r'([\u4e00-\u9fff])\s+([A-Za-z0-9])', r'\1\2', text)
        text = re.sub(r'([A-Za-z0-9])\s+([\u4e00-\u9fff])', r'\1\2', text)
        # 全形標點與英文/數字之間的空白
        text = re.sub(r'([\u3000-\u303F\uFF00-\uFFEF])\s+([A-Za-z0-9])', r'\1\2', text)
        text = re.sub(r'([A-Za-z0-9])\s+([\u3000-\u303F\uFF00-\uFFEF])', r'\1\2', text)
        return text

    def _punctuate_with_openai(
        self,
        text: str,
        language: str = "zh"
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """使用 OpenAI 添加標點符號

        Args:
            text: 要處理的文字
            language: 語言代碼

        Returns:
            (處理後的文字, 使用的模型名稱, token_usage) 元組
        """
        from openai import OpenAI

        client = OpenAI()

        # 獲取提示語
        system_msg, user_msg = self._get_punctuation_prompt(language, text)

        resp = client.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
        )

        result = resp.choices[0].message.content.strip()
        result = self._strip_llm_preamble(result)
        if language in ("zh", "zh-TW", "zh-CN"):
            result = self._remove_cjk_latin_spaces(result)

        # 提取 token 使用量
        token_usage = None
        if hasattr(resp, 'usage') and resp.usage:
            token_usage = {
                "total": resp.usage.total_tokens,
                "prompt": resp.usage.prompt_tokens,
                "completion": resp.usage.completion_tokens
            }
            log.debug(
                "punctuation.token_usage",
                provider="openai",
                total=token_usage["total"],
                prompt=token_usage["prompt"],
                completion=token_usage["completion"],
            )

        return result, self.openai_model, token_usage

    def _punctuate_with_gemini(
        self,
        text: str,
        language: str = "zh",
        chunk_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """使用 Google Gemini 添加標點符號（支援長文本分段處理）

        Args:
            text: 要處理的文字
            language: 語言代碼
            chunk_size: 分段大小（字元數），None 則自動決定
            progress_callback: 進度回調函數

        Returns:
            (處理後的文字, 使用的模型名稱, token_usage) 元組
        """
        # 自動決定 chunk_size（考慮輸出限制 65,536 tokens）
        # 標籤保全的分流已上移到 `process()`，此處只處理無標籤文字。
        chunk_size = self._resolve_chunk_size(language, chunk_size)

        # 如果文字不長，直接處理
        if len(text) <= chunk_size:
            result, model_used, token_usage = self._punctuate_chunk(text, language)
            return result, model_used, token_usage

        # 長文本：分段處理
        chunks = self._split_text_into_chunks(text, chunk_size)
        total_chunks = len(chunks)
        log.info(
            "punctuation.chunking",
            input_chars=len(text),
            chunk_size=chunk_size,
            total_chunks=total_chunks,
        )

        results = []
        model_used = None
        # 累加所有 chunk 的 token 使用量
        total_token_usage = {"total": 0, "prompt": 0, "completion": 0}

        for chunk_idx, chunk_text in enumerate(chunks, start=1):
            log.debug("punctuation.chunk_processing", chunk_idx=chunk_idx, total_chunks=total_chunks)

            # 進度回調
            if progress_callback:
                progress_callback(chunk_idx, total_chunks)

            result, chunk_model, chunk_token_usage = self._punctuate_chunk(
                chunk_text, language, chunk_idx, total_chunks
            )
            results.append(result)

            # 記錄使用的模型（使用第一個成功的模型）
            if model_used is None:
                model_used = chunk_model

            # 累加 token 使用量
            if chunk_token_usage:
                total_token_usage["total"] += chunk_token_usage.get("total", 0)
                total_token_usage["prompt"] += chunk_token_usage.get("prompt", 0)
                total_token_usage["completion"] += chunk_token_usage.get("completion", 0)

        # 如果有累計的 token 使用量，輸出總量
        if total_token_usage["total"] > 0:
            log.info(
                "punctuation.token_usage_total",
                provider="gemini",
                total=total_token_usage["total"],
                prompt=total_token_usage["prompt"],
                completion=total_token_usage["completion"],
            )

        # 合併結果
        final_token_usage = total_token_usage if total_token_usage["total"] > 0 else None
        return "\n\n".join(results), model_used or self.gemini_model, final_token_usage

    # ── 語者標籤保全路徑 ────────────────────────────────────────────────

    @staticmethod
    def _align_tolerance(total_target: int) -> int:
        """對齊容差：允許的可比字元漂移量。

        單純用 `max(50, 10%)` 會在小片段上失效——一個 20 字的片段就算被砍到只剩 6 字
        （70% 內容消失）仍在 50 的絕對下限內，靜默通過。故絕對下限本身再以
        總量的 25% 封頂：大片段維持 10% 比例容差，小片段不可能整段被吃掉。
        """
        proportional = int(total_target * 0.1)
        absolute_floor = min(50, int(total_target * 0.25))
        return max(proportional, absolute_floor)

    def _comparable_len(self, text: str) -> int:
        """可比字元數：只數內容字元（字母/數字/組合記號），忽略標點與空白。"""
        return sum(1 for ch in text if is_content_char(ch))

    @staticmethod
    def _new_token_usage() -> Dict[str, int]:
        return {"total": 0, "prompt": 0, "completion": 0}

    @staticmethod
    def _accumulate_token_usage(
        total: Dict[str, int], chunk_usage: Optional[Dict[str, int]]
    ) -> None:
        """把單次呼叫的 token 用量累加進總計（原本在兩條路徑各抄一份）。"""
        if not chunk_usage:
            return
        for key in ("total", "prompt", "completion"):
            total[key] += chunk_usage.get(key, 0)

    @staticmethod
    def _finalize_token_usage(total: Dict[str, int]) -> Optional[Dict[str, int]]:
        """有用量才 log 總計並回傳，全零視為無資料（維持原行為）。"""
        if total["total"] <= 0:
            return None
        log.info(
            "punctuation.token_usage_total",
            provider="gemini",
            total=total["total"],
            prompt=total["prompt"],
            completion=total["completion"],
        )
        return total

    def _resolve_chunk_size(self, language: str, chunk_size: Optional[int]) -> int:
        """決定分段大小（字元數）。原本內嵌在 `_punctuate_with_gemini`，抽出供兩條路徑共用。"""
        if chunk_size is not None:
            return chunk_size
        if language in ("zh", "zh-TW", "zh-CN", "ja", "ko"):
            return 20000  # 中日韓：每字約 1-1.5 tokens，需較小 chunk
        return 60000  # 英文等拉丁語系：每字元約 0.3 tokens

    def _punctuate_chunk(
        self,
        chunk_text: str,
        language: str,
        chunk_idx: Optional[int] = None,
        total_chunks: Optional[int] = None,
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """對單一片段呼叫 Gemini 並套用既有防護（前言剝除 / 膨脹回退 / CJK 空白）。

        原本散在單次與分段兩處的相同邏輯，抽成單點供三條路徑共用（單次、分段、
        語者標籤保全），確保防護不會因為新增路徑而漏套。
        chunk_idx 為 None → 用單次提示語；否則用分段提示語。
        """
        if chunk_idx is None:
            system_msg, user_msg = self._get_punctuation_prompt(language, chunk_text)
        else:
            system_msg, user_msg = self._get_chunked_punctuation_prompt(
                language, chunk_text, chunk_idx, total_chunks
            )
        prompt = f"{system_msg}\n\n{user_msg}"

        max_out = self._estimate_max_output_tokens(chunk_text, language)
        result, model, token_usage = self._call_gemini_with_retry(
            prompt, max_output_tokens=max_out
        )
        result = self._strip_llm_preamble(result)
        if self._is_output_exploded(chunk_text, result):
            log.warning(
                "punctuation.output_exploded",
                chunk_idx=chunk_idx,
                total_chunks=total_chunks,
                input_chars=len(chunk_text),
                output_chars=len(result),
            )
            result = chunk_text
        if language in ("zh", "zh-TW", "zh-CN"):
            result = self._remove_cjk_latin_spaces(result)
        return result, model, token_usage

    def _parse_speaker_turns(self, text: str) -> Optional[list]:
        """把 `_merge_transcription_with_diarization` 的輸出解析成 [(label, text), ...]。

        輸入格式：`\\n\\n` 分隔、每行 `[SPEAKER_xx] 文字`。
        回傳 None 表示「這不是帶標籤的文字」→ 呼叫端維持原行為（回歸底線）。

        **切分依據是「標籤」而不是「空行」**：上游 segments 的文字本身就可能帶
        `\\n\\n`（實測 237/2443 段），若照空行硬切，一個語者輪次會被拆成
        「有標籤的前半 + 無標籤的後半」，後半在輸出就成了無標籤漂浮段落
        （實測 staging 427 段落中 187 個是這樣來的）。因此沒有標籤前綴的片段
        一律**併回前一個輪次**，只有開頭就無標籤的情況才保留成 label=None 輪次。
        """
        parts = [p for p in text.split("\n\n") if p.strip()]
        if not parts:
            return None

        turns: list = []
        found_label = False
        for part in parts:
            m = _SPEAKER_TURN_PREFIX_RE.match(part)
            if m:
                found_label = True
                turns.append((m.group(1), part[m.end():]))
            elif turns:
                # 無標籤片段 = 前一輪次被上游換行切斷的後半，併回去
                label, body = turns[-1]
                turns[-1] = (label, f"{body}\n\n{part}")
            else:
                turns.append((None, part))

        return turns if found_label else None

    def _group_turns_into_chunks(self, texts: list, chunk_size: int) -> list:
        """把逐輪次純文字打包成 chunk，單一輪次不跨 chunk。

        回傳 [[(turn_idx, piece_text), ...], ...]。
        單一輪次長度超過 chunk_size 時在行內再切成多片（沿用
        `_split_text_into_chunks`），各片共用同一個 turn_idx，重貼時 rejoin 回同一行。
        """
        chunks: list = []
        current: list = []
        current_len = 0
        sep_len = 2  # "\n\n"

        for idx, t in enumerate(texts):
            if len(t) > chunk_size:
                # 超長輪次：先收掉手上的 chunk，再把這一輪自己切片獨佔數個 chunk
                if current:
                    chunks.append(current)
                    current, current_len = [], 0
                for piece in self._split_text_into_chunks(t, chunk_size):
                    chunks.append([(idx, piece)])
                continue

            addition = len(t) + (sep_len if current else 0)
            if current and current_len + addition > chunk_size:
                chunks.append(current)
                current, current_len = [(idx, t)], len(t)
            else:
                current.append((idx, t))
                current_len += addition

        if current:
            chunks.append(current)
        return chunks

    def _align_output_to_pieces(self, output: str, pieces: list) -> list:
        """把一次 LLM 呼叫的輸出，依各片段的「可比字元數」切回逐片段。

        可比字元 = 去掉標點與空白後的字元；LLM 只該增刪標點/斷行，不該改字，
        所以用累計可比字元數決定切點，不依賴模型保留任何分隔符號。
        輸出與輸入的可比字元數若差距過大（截斷/暴走），回傳 None 讓呼叫端回退原文。
        """
        targets = [self._comparable_len(p) for p in pieces]
        total_target = sum(targets)
        comparable_out = self._comparable_len(output)

        if total_target == 0:
            return None
        # 容差：允許 10%（或 50 字元）的漂移，超出視為輸出不可信。
        # 這道守門必須在「單 piece 早退」之前——超長輪次被切成的每個片段都是
        # 單 piece chunk，正是長獨白（本次修復的動機場景）走的路；若早退繞過檢查，
        # LLM 截斷輸出會被靜默接受，還照樣 log labels_preserved。
        if abs(comparable_out - total_target) > self._align_tolerance(total_target):
            log.warning(
                "punctuation.align_mismatch",
                input_comparable=total_target,
                output_comparable=comparable_out,
                pieces=len(pieces),
            )
            return None

        if len(pieces) == 1:
            return [output.strip()]

        # 依實際輸出長度等比縮放切點，吸收小幅漂移
        scale = comparable_out / total_target if total_target else 1.0

        # 內容字元前綴計數：prefix[i] = output[:i] 的內容字元數。
        # 有了它，「第 n 個內容字元的位置」可用 bisect 直接查，不必邊掃邊數——
        # 錨點吸附會讓切點前後移動，逐次重數會退化成 O(n²)。
        prefix = [0] * (len(output) + 1)
        for i, ch in enumerate(output):
            prefix[i + 1] = prefix[i] + (1 if is_content_char(ch) else 0)

        # 錨點：LLM 自己給的空行 > 句末標點。位置一律取「錨點之後」，
        # 讓空行/句號歸前一片段。
        blank_anchors = [m.end() for m in _BLANK_LINE_RE.finditer(output)]
        sentence_anchors = [
            i + 1 for i, ch in enumerate(output) if ch in _SENTENCE_END_CHARS
        ]

        cut_points: list = []
        prev_cut = 0
        for target in targets[:-1]:
            # 估計位置以「上一個已吸附的切點」為原點，而不是從頭累計——
            # 從頭累計會讓每個邊界的誤差疊加到後面所有邊界（實測越界量與段落
            # 序號正相關 r=0.232）。以上一個切點為原點後，誤差只影響當前邊界。
            need = prefix[prev_cut] + int(round(target * scale))
            # 計數估計位置：第 need 個內容字元之後
            est = bisect.bisect_left(prefix, need)
            est = max(0, min(est, len(output)))
            # 把估計點後緊接的收尾標點/空白歸給前一片段；遇到開口標點就停——
            # 那是下一位語者的開頭引號，吞過去會讓 A 行尾懸掛「、B 行 」不成對。
            while (
                est < len(output)
                and not is_content_char(output[est])
                and not is_opening_punct(output[est])
            ):
                est += 1

            # 吸附窗口按片段長度取比例：越界量實測中位數 11 字、漂浮段落長度
            # 中位數 29 字，10% 對一般片段（數百至數千字）足以涵蓋，又不會跨到
            # 隔壁片段；短片段用 12 字下限（仍大於越界中位數）。
            window = max(_ANCHOR_WINDOW_MIN, int(target * _ANCHOR_WINDOW_RATIO))
            cut = self._snap_to_anchor(
                est, window, blank_anchors, sentence_anchors,
                lower=prev_cut + 1, upper=len(output),
            )
            cut_points.append(cut)
            prev_cut = cut

        out_pieces = []
        start = 0
        for cut in cut_points:
            out_pieces.append(output[start:cut].strip())
            start = cut
        out_pieces.append(output[start:].strip())
        return out_pieces

    @staticmethod
    def _snap_to_anchor(
        est: int,
        window: int,
        blank_anchors: list,
        sentence_anchors: list,
        lower: int,
        upper: int,
    ) -> int:
        """把計數估計位置吸附到窗口內最接近的錨點。

        優先序：空行 > 句末標點 > 原估計位置。同類錨點有多個時取**最接近估計位置**
        者（不是第一個）——實測 LLM 給的空行數是輪次數的 1.78 倍，貪心取第一個會
        systematically 選錯。
        `lower`/`upper` 夾出合法區間並保證切點單調遞增，不會回退、不會產生空片段。
        """
        lower = max(0, min(lower, upper))
        est = max(lower, min(est, upper))

        low_bound = max(lower, est - window)
        high_bound = min(upper, est + window)

        # 距離優先、種類次之：空行的優先序只用來打平手。
        # 嚴格「空行永遠贏」會挑到輪次內部的分段空行而放掉正落在估計點上的句末
        # 標點——實測那樣會讓輪次結尾落在句中的比率反而上升。
        candidates = []
        for priority, anchors in ((0, blank_anchors), (1, sentence_anchors)):
            if not anchors:
                continue
            lo = bisect.bisect_left(anchors, low_bound)
            hi = bisect.bisect_right(anchors, high_bound)
            for c in anchors[lo:hi]:
                candidates.append((abs(c - est), priority, c))

        if candidates:
            return min(candidates)[2]

        return est

    def _punctuate_speaker_turns(
        self,
        turns: list,
        provider: str,
        language: str,
        chunk_size: Optional[int],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """標籤保全版標點：標籤留在本地，只有純文字進 LLM，事後重貼。

        兩個 provider 共用。openai 原本就不分段（整份送出），這裡維持該語意：
        全部輪次併成單一 chunk，只是多了剝離/重貼與對齊。
        """
        labels = [label for label, _ in turns]
        # 進 LLM 前先收掉輪次內的換行（來自上游 segments 或併回的續段），
        # 免得模型把它當既有分段、在輸出裡照抄放大
        texts = [self._normalize_turn_body(t, language) for _, t in turns]
        label_count = sum(1 for label in labels if label)

        if provider == "openai":
            # 維持 openai 既有語意：不分段，一次送完
            chunks = [[(i, t) for i, t in enumerate(texts)]]
            resolved_chunk_size = None
        else:
            resolved_chunk_size = self._resolve_chunk_size(language, chunk_size)
            chunks = self._group_turns_into_chunks(texts, resolved_chunk_size)
        total_chunks = len(chunks)

        log.info(
            "punctuation.chunking",
            provider=provider,
            input_chars=sum(len(t) for t in texts),
            chunk_size=resolved_chunk_size,
            total_chunks=total_chunks,
            speaker_turns=len(turns),
            speaker_labels=label_count,
            label_safe_mode=True,
        )

        per_turn: list = [[] for _ in texts]
        model_used = None
        total_token_usage = self._new_token_usage()

        for chunk_idx, chunk_pieces in enumerate(chunks, start=1):
            if progress_callback:
                progress_callback(chunk_idx, total_chunks)

            piece_texts = [p for _, p in chunk_pieces]
            chunk_text = "\n\n".join(piece_texts)
            if provider == "openai":
                result, chunk_model, chunk_token_usage = self._punctuate_with_openai(
                    chunk_text, language
                )
            else:
                # 只有一個 chunk 時用單次提示語——否則最常見尺寸的 diarized 任務
                # 會平白吃到「這是第 1 部分」的分段 prompt，是純粹的回歸。
                idx = chunk_idx if total_chunks > 1 else None
                result, chunk_model, chunk_token_usage = self._punctuate_chunk(
                    chunk_text, language, idx, total_chunks if idx else None
                )

            aligned = self._align_output_to_pieces(result, piece_texts)
            if aligned is None:
                # 對齊失敗 → 該 chunk 整批回退原文（內容不遺失，只是沒標點）
                aligned = piece_texts
            # 不用 zip(strict=)：本地 dev venv 仍是 3.9（strict= 需 3.10+），
            # 與 whisper_processor 同慣例改用 enumerate。
            for pos, (turn_idx, original) in enumerate(chunk_pieces):
                piece_out = aligned[pos] if pos < len(aligned) else ""
                per_turn[turn_idx].append((original, piece_out or original))

            if model_used is None:
                model_used = chunk_model
            self._accumulate_token_usage(total_token_usage, chunk_token_usage)

        # 重貼標籤（格式與 `_merge_transcription_with_diarization` 完全一致）
        lines = []
        for turn_idx, label in enumerate(labels):
            body = self._normalize_turn_body(
                self._join_turn_pieces(per_turn[turn_idx]), language
            )
            lines.append(f"{label} {body}" if label else body)
        final_text = "\n\n".join(lines)

        # 結構性驗證：標籤由本地重貼，數量必然守恆；不符代表程式碼有 bug，不是 LLM 行為
        rebuilt = len(_SPEAKER_LABEL_COUNT_RE.findall(final_text))
        if rebuilt == label_count:
            log.info(
                "punctuation.labels_preserved",
                labels_in=label_count,
                labels_out=rebuilt,
                turns=len(turns),
            )
        else:
            log.error(
                "punctuation.labels_lost",
                labels_in=label_count,
                labels_out=rebuilt,
                turns=len(turns),
            )

        final_token_usage = self._finalize_token_usage(total_token_usage)
        default_model = self.openai_model if provider == "openai" else self.gemini_model
        return final_text, model_used or default_model, final_token_usage

    @staticmethod
    def _normalize_turn_body(body: str, language: str) -> str:
        """收掉輪次 body 內的換行——`\\n\\n` 專職當輪次分隔符。

        一個語者輪次是一個發話單位，本身不該再被分段；body 內若殘留 `\\n\\n`，
        前端按 `\\n\\n` 切分就會多出「沒有標籤的漂浮段落」（實測 staging：
        427 段落中 187 個是這樣來的，佔 43.8%）。
        來源有兩處，這裡一併收掉：LLM 標點時自行插入的、以及上游 segments
        文字本身就帶的（實測 237/2443 段自帶換行）。

        CJK 直接接續（中日韓不用空白分詞）；拉丁語系換單一空格，否則會把
        前後單字黏成一個字。
        """
        joiner = "" if language in _NO_SPACE_LANGUAGES else " "
        body = _TURN_BODY_NEWLINE_RE.sub(joiner, body)
        if joiner == " ":
            body = re.sub(r" {2,}", " ", body)
        return body.strip()

    @staticmethod
    def _join_turn_pieces(pieces: list) -> str:
        """把同一輪次的切片接回一行，保留切點原本的空白。

        `_split_text_into_chunks` 會在空格後斷開（片段尾端帶著那個空格），
        而對齊輸出經過 `.strip()`——直接 `"".join` 會把分隔空白吃掉，
        讓英文在切點黏成 'thelazy' / 'dogand'。CJK 無空格，不受影響。
        """
        out: list = []
        for pos, (original, punctuated) in enumerate(pieces):
            if pos > 0:
                boundary_had_space = (
                    pieces[pos - 1][0][-1:].isspace() or original[:1].isspace()
                )
                already_separated = bool(out) and out[-1][-1:].isspace()
                if boundary_had_space and not already_separated:
                    out.append(" ")
            out.append(punctuated)
        return "".join(out).strip()

    def _call_gemini_with_retry(
        self,
        prompt: str,
        max_retries: Optional[int] = None,
        max_output_tokens: Optional[int] = None
    ) -> Tuple[str, str, Optional[Dict[str, int]]]:
        """調用 Gemini API，支援自動重試和模型備援

        Args:
            prompt: 提示文字
            max_retries: 最大重試次數

        Returns:
            (處理後的文字, 使用的模型名稱, token_usage) 元組

        Raises:
            RuntimeError: 所有 API Keys 和備援模型都失敗
        """
        import google.generativeai as genai

        # 獲取 Google API Keys
        google_api_keys = self._load_google_api_keys()

        if max_retries is None:
            max_retries = len(google_api_keys)

        last_error = None
        quota_exceeded_count = 0
        current_model = self.gemini_model
        fallback_index = -1
        tried_models = [self.gemini_model]
        current_key_index = 0

        max_attempts = max_retries * (len(self.gemini_fallback_models) + 1)

        for attempt in range(max_attempts):
            try:
                # 獲取下一個 API Key（輪詢）
                api_key = google_api_keys[current_key_index % len(google_api_keys)]
                current_key_index += 1

                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(current_model)

                # 調用 API
                gen_config: Dict[str, Any] = {"temperature": 0.2}
                if max_output_tokens:
                    gen_config["max_output_tokens"] = max_output_tokens
                resp = model.generate_content(
                    [{"role": "user", "parts": [prompt]}],
                    generation_config=gen_config
                )

                result = (resp.text or "").strip()

                if fallback_index >= 0:
                    log.info("punctuation.fallback_model_succeeded", model=current_model)

                # 提取 token 使用量
                token_usage = None
                if hasattr(resp, 'usage_metadata') and resp.usage_metadata:
                    total = getattr(resp.usage_metadata, 'total_token_count', 0)
                    prompt_tokens = getattr(resp.usage_metadata, 'prompt_token_count', 0)
                    completion = getattr(resp.usage_metadata, 'candidates_token_count', 0)
                    token_usage = {
                        "total": total,
                        "prompt": prompt_tokens,
                        "completion": completion
                    }
                    log.debug(
                        "punctuation.token_usage",
                        provider="gemini",
                        model=current_model,
                        total=total,
                        prompt=prompt_tokens,
                        completion=completion,
                    )

                return result, current_model, token_usage

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 檢查是否為 429 配額錯誤
                is_quota_error = (
                    "429" in error_msg or
                    "quota" in error_msg.lower() or
                    "Quota exceeded" in error_msg
                )

                if is_quota_error:
                    quota_exceeded_count += 1
                    log.warning("punctuation.quota_exceeded", attempt=attempt + 1, model=current_model)

                    # 如果所有 keys 都配額耗盡，嘗試切換到下一個備援模型
                    if quota_exceeded_count >= len(google_api_keys):
                        fallback_index += 1

                        if fallback_index < len(self.gemini_fallback_models):
                            current_model = self.gemini_fallback_models[fallback_index]
                            log.warning("punctuation.switching_fallback_model", model=current_model)
                            tried_models.append(current_model)
                            quota_exceeded_count = 0
                            current_key_index = 0  # 重置 key 索引
                            continue
                        else:
                            # 所有備援模型都用完了
                            log.error("punctuation.all_models_quota_exceeded", tried_models=tried_models)
                            raise RuntimeError(
                                f"所有 Google API Keys 都調用失敗。"
                                f"已嘗試模型: {', '.join(tried_models)}。"
                                f"最後錯誤: {error_msg}"
                            ) from last_error
                else:
                    log.warning("punctuation.api_call_failed", attempt=attempt + 1, error=error_msg)

                # 如果還有 key 可用，繼續嘗試
                if attempt < max_attempts - 1:
                    log.debug("punctuation.switching_api_key")
                    continue
                else:
                    raise RuntimeError(
                        f"所有 Google API Keys 都調用失敗。"
                        f"已嘗試模型: {', '.join(tried_models)}。"
                        f"最後錯誤: {error_msg}"
                    ) from last_error

        raise RuntimeError(
            f"無法調用 Gemini API。已嘗試模型: {', '.join(tried_models)}"
        ) from last_error

    def _get_punctuation_prompt(
        self,
        language: str,
        text: str
    ) -> Tuple[str, str]:
        """根據語言生成適當的標點提示語

        Args:
            language: 語言代碼（zh/en/ja/ko 等）
            text: 要處理的文字

        Returns:
            (system_message, user_message) 元組
        """
        if language in ("zh", "zh-TW", "zh-CN"):
            if language == "zh-TW":
                script_note = "請使用『繁體中文』輸出。"
            elif language == "zh-CN":
                script_note = "请使用『简体中文』输出。"
            else:
                script_note = ""
            system_msg = "你是嚴謹的逐字稿潤飾助手，只做標點與分段。"
            user_msg = (
                f"請將以下『中文逐字稿』加上適當標點符號並『合理分段』。{script_note}"
                "不要省略或添加內容，不要意譯，保留固有名詞與數字。"
                "不要在中英文之間插入空白，保持原文的空白狀態。"
                "**重要：如果文字中有說話者標籤（例如 [SPEAKER_00]），請完整保留這些標籤，不要修改或刪除。**"
                "直接輸出處理後的逐字稿本文，回覆的第一個字元就必須是逐字稿內容；禁止任何前言、開場白、說明、標題或結尾註記，禁止使用 markdown 程式碼圍欄。"
                f"輸出純文字即可：\n\n{text}"
            )
        elif language == "en":
            system_msg = (
                "You are a precise transcript editor. Only add punctuation and paragraphing. "
                "Output the processed transcript directly; the very first character of your reply must be transcript content. Do not include any preamble, introduction, explanation, heading, or closing remark. Do not use markdown code fences."
            )
            user_msg = (
                "Please add appropriate punctuation and paragraphing to the following English transcript. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "**Important: If the text contains speaker labels (e.g., [SPEAKER_00], [Speaker A]), preserve them completely without modification or removal.**"
                f"Output plain text only:\n\n{text}"
            )
        elif language == "ja":
            system_msg = (
                "あなたは正確な文字起こし編集者です。句読点と段落分けのみを行います。"
                "処理後の文字起こし本文を直接出力し、返答の最初の文字は必ず本文でなければなりません。前置き・説明・見出し・結びの注記は一切禁止です。markdownのコードフェンスも使用しないでください。"
            )
            user_msg = (
                "以下の日本語文字起こしに適切な句読点と段落を追加してください。"
                "内容の省略や追加はせず、意訳せず、固有名詞と数字はそのまま保持してください。"
                "**重要：話者ラベル（例：[SPEAKER_00]）が含まれている場合は、完全に保持し、変更や削除をしないでください。**"
                f"プレーンテキストのみ出力してください：\n\n{text}"
            )
        elif language == "ko":
            system_msg = (
                "당신은 정확한 전사 편집자입니다. 구두점과 단락 나누기만 수행합니다. "
                "처리된 전사 본문을 바로 출력하고, 응답의 첫 글자는 반드시 전사 내용이어야 합니다. 서문, 도입부, 설명, 제목, 맺음말을 일절 금지합니다. markdown 코드 펜스도 사용하지 마세요."
            )
            user_msg = (
                "다음 한국어 전사에 적절한 구두점과 단락을 추가해주세요. "
                "내용을 생략하거나 추가하지 말고, 의역하지 말고, 고유명사와 숫자는 그대로 유지하세요. "
                "**중요: 화자 레이블(예: [SPEAKER_00], [Speaker A])이 포함된 경우 완전히 보존하고 수정하거나 삭제하지 마세요.**"
                f"일반 텍스트만 출력하세요:\n\n{text}"
            )
        else:
            # 其他語言使用英文提示
            system_msg = (
                "You are a precise transcript editor. Only add punctuation and paragraphing. "
                "Output the processed transcript directly; the very first character of your reply must be transcript content. Do not include any preamble, introduction, explanation, heading, or closing remark. Do not use markdown code fences."
            )
            user_msg = (
                f"Please add appropriate punctuation and paragraphing to the following transcript. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "**Important: If the text contains speaker labels (e.g., [SPEAKER_00]), preserve them completely without modification or removal.**"
                f"Output plain text only:\n\n{text}"
            )

        return system_msg, user_msg

    def _get_chunked_punctuation_prompt(
        self,
        language: str,
        chunk_text: str,
        chunk_idx: int,
        total_chunks: int
    ) -> Tuple[str, str]:
        """為長文本分段生成提示語

        Args:
            language: 語言代碼
            chunk_text: 當前分段文字
            chunk_idx: 當前分段索引（從1開始）
            total_chunks: 總分段數

        Returns:
            (system_message, user_message) 元組
        """
        if language in ("zh", "zh-TW", "zh-CN"):
            if language == "zh-TW":
                script_note = "請使用『繁體中文』輸出。"
            elif language == "zh-CN":
                script_note = "请使用『简体中文』输出。"
            else:
                script_note = ""
            system_msg = (
                f"你是嚴謹的逐字稿潤飾助手。只做『中文標點補全』與『合理分段』，{script_note}"
                "不要省略或添加內容，不要意譯，非必要不要用刪節號，保留固有名詞與數字。"
                "不要在中英文之間插入空白，保持原文的空白狀態。"
                "**重要：如果文字中有說話者標籤（例如 [SPEAKER_00]），請完整保留這些標籤。**"
                "直接輸出處理後的逐字稿本文，回覆的第一個字元就必須是逐字稿內容；禁止任何前言、開場白、說明、標題或結尾註記，禁止使用 markdown 程式碼圍欄。"
            )
            if chunk_idx == 1:
                user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 1 部分）：\n\n{chunk_text}"
            elif chunk_idx == total_chunks:
                user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是最後一部分，接續前文）：\n\n{chunk_text}"
            else:
                user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 {chunk_idx} 部分，接續前文）：\n\n{chunk_text}"
        elif language == "en":
            system_msg = (
                "You are a precise transcript editor. Only add punctuation and paragraphing. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "**Important: Preserve all speaker labels (e.g., [SPEAKER_00]) completely.**"
                "Output the processed transcript directly; the very first character of your reply must be transcript content. Do not include any preamble, introduction, explanation, heading, or closing remark. Do not use markdown code fences."
            )
            if chunk_idx == 1:
                user_msg = f"Add punctuation and paragraphing to this English transcript (part 1):\n\n{chunk_text}"
            elif chunk_idx == total_chunks:
                user_msg = f"Add punctuation and paragraphing to this English transcript (final part, continuing from previous):\n\n{chunk_text}"
            else:
                user_msg = f"Add punctuation and paragraphing to this English transcript (part {chunk_idx}, continuing from previous):\n\n{chunk_text}"
        elif language == "ja":
            system_msg = (
                "あなたは正確な文字起こし編集者です。句読点と段落分けのみを行います。"
                "内容の省略や追加はせず、意訳せず、固有名詞と数字はそのまま保持してください。"
                "**重要：話者ラベル（例：[SPEAKER_00]）を完全に保持してください。**"
                "処理後の文字起こし本文を直接出力し、返答の最初の文字は必ず本文でなければなりません。前置き・説明・見出し・結びの注記は一切禁止です。markdownのコードフェンスも使用しないでください。"
            )
            if chunk_idx == 1:
                user_msg = f"以下の日本語文字起こしに句読点と段落を追加してください（第1部分）：\n\n{chunk_text}"
            elif chunk_idx == total_chunks:
                user_msg = f"以下の日本語文字起こしに句読点と段落を追加してください（最後の部分、前の続き）：\n\n{chunk_text}"
            else:
                user_msg = f"以下の日本語文字起こしに句読点と段落を追加してください（第{chunk_idx}部分、前の続き）：\n\n{chunk_text}"
        elif language == "ko":
            system_msg = (
                "당신은 정확한 전사 편집자입니다. 구두점과 단락 나누기만 수행합니다. "
                "내용을 생략하거나 추가하지 말고, 의역하지 말고, 고유명사와 숫자는 그대로 유지하세요. "
                "**중요: 화자 레이블(예: [SPEAKER_00])을 완전히 보존하세요.**"
                "처리된 전사 본문을 바로 출력하고, 응답의 첫 글자는 반드시 전사 내용이어야 합니다. 서문, 도입부, 설명, 제목, 맺음말을 일절 금지합니다. markdown 코드 펜스도 사용하지 마세요."
            )
            if chunk_idx == 1:
                user_msg = f"다음 한국어 전사에 구두점과 단락을 추가해주세요 (1부):\n\n{chunk_text}"
            elif chunk_idx == total_chunks:
                user_msg = f"다음 한국어 전사에 구두점과 단락을 추가해주세요 (마지막 부분, 이전 계속):\n\n{chunk_text}"
            else:
                user_msg = f"다음 한국어 전사에 구두점과 단락을 추가해주세요 ({chunk_idx}부, 이전 계속):\n\n{chunk_text}"
        else:
            # 其他語言使用英文提示
            system_msg = (
                "You are a precise transcript editor. Only add punctuation and paragraphing. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "Output the processed transcript directly; the very first character of your reply must be transcript content. Do not include any preamble, introduction, explanation, heading, or closing remark. Do not use markdown code fences."
            )
            if chunk_idx == 1:
                user_msg = f"Add punctuation and paragraphing to this transcript (part 1):\n\n{chunk_text}"
            elif chunk_idx == total_chunks:
                user_msg = f"Add punctuation and paragraphing to this transcript (final part, continuing from previous):\n\n{chunk_text}"
            else:
                user_msg = f"Add punctuation and paragraphing to this transcript (part {chunk_idx}, continuing from previous):\n\n{chunk_text}"

        return system_msg, user_msg

    def _split_text_into_chunks(
        self,
        text: str,
        chunk_size: int
    ) -> list[str]:
        """將文字分割成多個小段，盡量在合適的位置斷開

        會優先在以下位置斷開（按優先順序）：
        1. 說話者標籤前（如 [SPEAKER_00]）
        2. 換行符
        3. 空格（適用於英文等語言）

        Args:
            text: 要分割的文字
            chunk_size: 每段大小（字元數）

        Returns:
            分段列表
        """
        import re

        chunks = []
        start = 0

        while start < len(text):
            # 如果剩餘文字不超過 chunk_size，直接加入
            if start + chunk_size >= len(text):
                chunks.append(text[start:])
                break

            # 預設結束位置
            end = start + chunk_size

            # 在 chunk 範圍內尋找最佳斷點（從後往前找）
            search_start = max(start, end - min(2000, chunk_size // 4))  # 在最後 1/4 或 2000 字內尋找
            search_region = text[search_start:end]

            best_break = None

            # 優先找說話者標籤（如 [SPEAKER_00]、[Speaker A] 等）
            speaker_matches = list(_SPEAKER_LABEL_SEARCH_RE.finditer(search_region))
            if speaker_matches:
                # 使用最後一個說話者標籤的位置作為斷點
                best_break = search_start + speaker_matches[-1].start()

            # 如果沒找到說話者標籤，找換行符
            if best_break is None:
                last_newline = search_region.rfind('\n')
                if last_newline != -1:
                    best_break = search_start + last_newline + 1  # 換行符後斷開

            # 如果沒找到換行符，找空格（對英文有用）
            if best_break is None:
                last_space = search_region.rfind(' ')
                if last_space != -1:
                    best_break = search_start + last_space + 1  # 空格後斷開

            # 如果找到合適斷點，使用它；否則使用原始 chunk_size
            if best_break is not None and best_break > start:
                end = best_break

            chunks.append(text[start:end])
            start = end

        return chunks

    def _load_google_api_keys(self) -> list[str]:
        """從環境變數載入所有 Google API Keys

        Returns:
            API Keys 列表
        """
        keys = []
        i = 1

        while True:
            key = os.getenv(f"GOOGLE_API_KEY_{i}")
            if not key:
                break
            keys.append(key)
            i += 1

        # 如果沒有找到編號的 keys，嘗試使用單一的 GOOGLE_API_KEY
        if not keys:
            single_key = os.getenv("GOOGLE_API_KEY")
            if single_key:
                keys.append(single_key)

        if not keys:
            raise ValueError("未設定任何 GOOGLE_API_KEY")

        return keys
