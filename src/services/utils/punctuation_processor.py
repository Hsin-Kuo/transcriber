"""
PunctuationProcessor - 標點符號處理器
職責：使用 AI 模型為轉錄文字添加標點符號
"""

from typing import Optional, Tuple, Dict, Any, Callable
import os


class PunctuationProcessor:
    """標點符號處理器

    使用 Gemini 或 OpenAI 為轉錄文字添加標點符號和分段
    """

    def __init__(
        self,
        default_provider: str = "gemini",
        gemini_model: str = "gemini-2.0-flash",
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
            "gemini-2.0-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-2.5-flash",
            "gemini-flash-latest",
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

        if provider == "openai":
            return self._punctuate_with_openai(text, language)
        else:
            return self._punctuate_with_gemini(
                text,
                language,
                chunk_size,
                progress_callback
            )

    # ========== 私有方法 ==========

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

        # 提取 token 使用量
        token_usage = None
        if hasattr(resp, 'usage') and resp.usage:
            token_usage = {
                "total": resp.usage.total_tokens,
                "prompt": resp.usage.prompt_tokens,
                "completion": resp.usage.completion_tokens
            }
            print(f"📊 Token 使用: {token_usage['total']} (輸入: {token_usage['prompt']}, 輸出: {token_usage['completion']})")

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
        import google.generativeai as genai

        # 自動決定 chunk_size
        if chunk_size is None:
            if language == "zh":
                chunk_size = 4000  # 中文：4000 字
            else:
                chunk_size = 15000  # 其他語言：15000 字元

        # 如果文字不長，直接處理
        if len(text) <= chunk_size:
            system_msg, user_msg = self._get_punctuation_prompt(language, text)
            prompt = f"{system_msg}\n\n{user_msg}"
            result, model_used, token_usage = self._call_gemini_with_retry(prompt)
            return result, model_used, token_usage

        # 長文本：分段處理
        print(f"📝 文字較長（{len(text)} 字），將分段處理（每段約 {chunk_size} 字）...")

        chunks = self._split_text_into_chunks(text, chunk_size)
        total_chunks = len(chunks)
        print(f"🔄 分為 {total_chunks} 段處理...")

        results = []
        model_used = None
        # 累加所有 chunk 的 token 使用量
        total_token_usage = {"total": 0, "prompt": 0, "completion": 0}

        for chunk_idx, chunk_text in enumerate(chunks, start=1):
            print(f"🎯 處理第 {chunk_idx}/{total_chunks} 段...")

            # 進度回調
            if progress_callback:
                progress_callback(chunk_idx, total_chunks)

            # 獲取分段提示語
            system_msg, user_msg = self._get_chunked_punctuation_prompt(
                language, chunk_text, chunk_idx, total_chunks
            )
            prompt = f"{system_msg}\n\n{user_msg}"

            # 調用 Gemini
            result, chunk_model, chunk_token_usage = self._call_gemini_with_retry(prompt)
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
            print(f"📊 總 Token 使用: {total_token_usage['total']} (輸入: {total_token_usage['prompt']}, 輸出: {total_token_usage['completion']})")

        # 合併結果
        final_token_usage = total_token_usage if total_token_usage["total"] > 0 else None
        return "\n\n".join(results), model_used or self.gemini_model, final_token_usage

    def _call_gemini_with_retry(
        self,
        prompt: str,
        max_retries: Optional[int] = None
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
                resp = model.generate_content(
                    [{"role": "user", "parts": [prompt]}],
                    generation_config={"temperature": 0.2}
                )

                result = (resp.text or "").strip()

                if fallback_index >= 0:
                    print(f"✅ 使用備援模型 {current_model} 成功")

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
                    print(f"📊 Token 使用: {total} (輸入: {prompt_tokens}, 輸出: {completion})")

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
                    print(f"⚠️ Google API Key 配額已用完 (嘗試 {attempt + 1}，模型: {current_model})")

                    # 如果所有 keys 都配額耗盡，嘗試切換到下一個備援模型
                    if quota_exceeded_count >= len(google_api_keys):
                        fallback_index += 1

                        if fallback_index < len(self.gemini_fallback_models):
                            current_model = self.gemini_fallback_models[fallback_index]
                            print(f"💡 切換到備用模型 {current_model}")
                            tried_models.append(current_model)
                            quota_exceeded_count = 0
                            current_key_index = 0  # 重置 key 索引
                            continue
                        else:
                            # 所有備援模型都用完了
                            print(f"❌ 所有模型的配額都已用完")
                            raise RuntimeError(
                                f"所有 Google API Keys 都調用失敗。"
                                f"已嘗試模型: {', '.join(tried_models)}。"
                                f"最後錯誤: {error_msg}"
                            ) from last_error
                else:
                    print(f"⚠️ Google API Key 調用失敗 (嘗試 {attempt + 1}): {error_msg}")

                # 如果還有 key 可用，繼續嘗試
                if attempt < max_attempts - 1:
                    print(f"🔄 切換到下一個 API Key...")
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
        if language == "zh":
            system_msg = "你是嚴謹的逐字稿潤飾助手，只做標點與分段。"
            user_msg = (
                "請將以下『中文逐字稿』加上適當標點符號並合理分段。"
                "不要省略或添加內容，不要意譯，保留固有名詞與數字。"
                "**重要：如果文字中有說話者標籤（例如 [SPEAKER_00]、[Speaker A] 等），請完整保留這些標籤，不要修改或刪除。**"
                f"輸出純文字即可：\n\n{text}"
            )
        elif language == "en":
            system_msg = "You are a precise transcript editor. Only add punctuation and paragraphing."
            user_msg = (
                "Please add appropriate punctuation and paragraphing to the following English transcript. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "**Important: If the text contains speaker labels (e.g., [SPEAKER_00], [Speaker A]), preserve them completely without modification or removal.**"
                f"Output plain text only:\n\n{text}"
            )
        elif language == "ja":
            system_msg = "あなたは正確な文字起こし編集者です。句読点と段落分けのみを行います。"
            user_msg = (
                "以下の日本語文字起こしに適切な句読点と段落を追加してください。"
                "内容の省略や追加はせず、意訳せず、固有名詞と数字はそのまま保持してください。"
                "**重要：話者ラベル（例：[SPEAKER_00]、[Speaker A]など）が含まれている場合は、完全に保持し、変更や削除をしないでください。**"
                f"プレーンテキストのみ出力してください：\n\n{text}"
            )
        elif language == "ko":
            system_msg = "당신은 정확한 전사 편집자입니다. 구두점과 단락 나누기만 수행합니다."
            user_msg = (
                "다음 한국어 전사에 적절한 구두점과 단락을 추가해주세요. "
                "내용을 생략하거나 추가하지 말고, 의역하지 말고, 고유명사와 숫자는 그대로 유지하세요. "
                "**중요: 화자 레이블(예: [SPEAKER_00], [Speaker A])이 포함된 경우 완전히 보존하고 수정하거나 삭제하지 마세요.**"
                f"일반 텍스트만 출력하세요:\n\n{text}"
            )
        else:
            # 其他語言使用英文提示
            system_msg = "You are a precise transcript editor. Only add punctuation and paragraphing."
            user_msg = (
                f"Please add appropriate punctuation and paragraphing to the following transcript. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "**Important: If the text contains speaker labels (e.g., [SPEAKER_00], [Speaker A]), preserve them completely without modification or removal.**"
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
        if language == "zh":
            system_msg = (
                "你是嚴謹的逐字稿潤飾助手。只做『中文標點補全與合理分段』，"
                "不要省略或添加內容，不要意譯，非必要不要用刪節號，保留固有名詞與數字。"
                "**重要：如果文字中有說話者標籤（例如 [SPEAKER_00]、[Speaker A] 等），請完整保留這些標籤。**"
            )
            if chunk_idx == 1:
                user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 1 段）：\n\n{chunk_text}"
            elif chunk_idx == total_chunks:
                user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是最後一段，接續前文）：\n\n{chunk_text}"
            else:
                user_msg = f"請為以下中文逐字稿加上適當標點並分段（這是第 {chunk_idx} 段，接續前文）：\n\n{chunk_text}"
        elif language == "en":
            system_msg = (
                "You are a precise transcript editor. Only add punctuation and paragraphing. "
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers. "
                "**Important: Preserve all speaker labels (e.g., [SPEAKER_00], [Speaker A]) completely.**"
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
                "**重要：話者ラベル（例：[SPEAKER_00]、[Speaker A]）を完全に保持してください。**"
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
                "**중요: 화자 레이블(예: [SPEAKER_00], [Speaker A])을 완전히 보존하세요.**"
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
                "Do not omit or add content, do not paraphrase, preserve proper nouns and numbers."
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
        """將文字分割成多個小段

        Args:
            text: 要分割的文字
            chunk_size: 每段大小（字元數）

        Returns:
            分段列表
        """
        chunks = []
        start = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))
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
