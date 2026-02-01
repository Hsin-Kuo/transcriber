"""
SummaryService - AI 摘要服務
職責：使用 Gemini API 生成逐字稿摘要
"""

import os
import json
import re
from typing import Optional, Dict, Any, Tuple, List

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..database.repositories.summary_repo import SummaryRepository
from ..database.repositories.task_repo import TaskRepository


class SummaryService:
    """AI 摘要服務"""

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        default_model: str = "gemini-2.5-flash"
    ):
        """初始化 SummaryService

        Args:
            db: MongoDB 資料庫實例
            default_model: 預設 Gemini 模型
        """
        self.db = db
        self.summary_repo = SummaryRepository(db)
        self.task_repo = TaskRepository(db)
        self.default_model = default_model

        # Gemini 備援模型列表（按優先順序）
        self.fallback_models = [
            "gemini-2.5-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
        ]

    async def generate_summary(
        self,
        task_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """生成 AI 摘要

        Args:
            task_id: 任務 ID
            user_id: 使用者 ID（用於權限驗證）

        Returns:
            生成結果 {task_id, status, summary?, error?}
        """
        try:
            # 1. 驗證任務存在且屬於該用戶
            task = await self.task_repo.get_by_id(task_id)
            if not task:
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "error": "找不到該任務"
                }

            if task.get("user", {}).get("user_id") != user_id:
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "error": "無權存取此任務"
                }

            # 2. 獲取逐字稿內容
            content = await self._get_transcript_content(task_id)
            if not content:
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "error": "無法獲取逐字稿內容"
                }

            # 3. 更新任務狀態為處理中
            await self.task_repo.update(task_id, {"summary_status": "processing"})

            # 4. 偵測語言
            language = self._detect_language(content)

            # 5. 調用 Gemini API 生成摘要
            summary_data, model_used, token_usage = await self._generate_with_gemini(content, language)

            if not summary_data:
                await self.task_repo.update(task_id, {"summary_status": "failed"})
                return {
                    "task_id": task_id,
                    "status": "failed",
                    "error": "AI 生成摘要失敗"
                }

            # 6. 儲存摘要到資料庫
            metadata = {
                "model": model_used,
                "language": language,
                "source_length": len(content)
            }

            # 如果有 token 使用量，加入 metadata
            if token_usage:
                metadata["token_usage"] = {
                    "total": token_usage.get("total", 0),
                    "prompt": token_usage.get("prompt", 0),
                    "completion": token_usage.get("completion", 0)
                }
                print(f"📊 保存摘要 Token 使用量: {token_usage}")

            doc = await self.summary_repo.upsert(task_id, summary_data, metadata)

            # 7. 更新任務狀態為完成
            await self.task_repo.update(task_id, {
                "summary_status": "completed",
                "summary_id": task_id
            })

            # 8. 返回結果
            return {
                "task_id": task_id,
                "status": "completed",
                "summary": {
                    "task_id": task_id,
                    "content": doc["content"],
                    "metadata": doc["metadata"],
                    "created_at": doc["created_at"],
                    "updated_at": doc["updated_at"]
                }
            }

        except Exception as e:
            print(f"❌ 生成摘要失敗: {e}")
            # 更新任務狀態為失敗
            try:
                await self.task_repo.update(task_id, {"summary_status": "failed"})
            except Exception:
                pass
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(e)
            }

    async def get_summary(
        self,
        task_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """獲取摘要

        Args:
            task_id: 任務 ID
            user_id: 使用者 ID

        Returns:
            摘要資料，不存在則返回 None
        """
        # 驗證權限
        task = await self.task_repo.get_by_id(task_id)
        if not task or task.get("user", {}).get("user_id") != user_id:
            return None

        doc = await self.summary_repo.get_by_task_id(task_id)
        if not doc:
            return None

        return {
            "task_id": task_id,
            "content": doc["content"],
            "metadata": doc["metadata"],
            "created_at": doc["created_at"],
            "updated_at": doc["updated_at"]
        }

    async def delete_summary(
        self,
        task_id: str,
        user_id: str
    ) -> bool:
        """刪除摘要

        Args:
            task_id: 任務 ID
            user_id: 使用者 ID

        Returns:
            是否刪除成功
        """
        # 驗證權限
        task = await self.task_repo.get_by_id(task_id)
        if not task or task.get("user", {}).get("user_id") != user_id:
            return False

        # 刪除摘要
        success = await self.summary_repo.delete(task_id)

        # 更新任務狀態
        if success:
            await self.task_repo.update(task_id, {
                "summary_status": None,
                "summary_id": None
            })

        return success

    async def _get_transcript_content(self, task_id: str) -> Optional[str]:
        """獲取逐字稿內容

        Args:
            task_id: 任務 ID

        Returns:
            逐字稿文字內容
        """
        # 從 transcripts collection 獲取
        transcript = await self.db.transcripts.find_one({"_id": task_id})
        if transcript and transcript.get("content"):
            return transcript["content"]

        # 如果沒有，嘗試從 segments 組合
        segments_doc = await self.db.segments.find_one({"_id": task_id})
        if segments_doc and segments_doc.get("segments"):
            texts = [seg.get("text", "") for seg in segments_doc["segments"]]
            return " ".join(texts)

        return None

    def _detect_language(self, text: str) -> str:
        """偵測文字語言

        Args:
            text: 文字內容

        Returns:
            語言代碼 (zh/en/ja/ko 等)
        """
        # 簡單的語言偵測：檢查中日韓字符比例
        sample = text[:1000]  # 只檢查前 1000 字

        # 中文字符
        chinese_count = len(re.findall(r'[\u4e00-\u9fff]', sample))
        # 日文假名
        japanese_count = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', sample))
        # 韓文
        korean_count = len(re.findall(r'[\uac00-\ud7af]', sample))

        total_cjk = chinese_count + japanese_count + korean_count

        if total_cjk > len(sample) * 0.1:  # CJK 字符超過 10%
            if japanese_count > chinese_count * 0.3:
                return "ja"
            elif korean_count > chinese_count * 0.3:
                return "ko"
            else:
                return "zh"

        return "en"

    async def _generate_with_gemini(
        self,
        text: str,
        language: str
    ) -> Tuple[Optional[Dict[str, Any]], str, Optional[Dict[str, int]]]:
        """使用 Gemini API 生成摘要

        Args:
            text: 逐字稿文字
            language: 語言代碼

        Returns:
            (摘要內容, 使用的模型名稱, token_usage) 元組
        """
        import google.generativeai as genai

        # 獲取 API Keys
        api_keys = self._load_google_api_keys()
        if not api_keys:
            raise ValueError("未設定任何 GOOGLE_API_KEY")

        # 生成 prompt
        prompt = self._get_summary_prompt(language, text)

        # 嘗試調用 API
        current_model = self.default_model
        fallback_index = -1
        tried_models = [self.default_model]
        quota_exceeded_count = 0
        last_error = None

        max_attempts = len(api_keys) * (len(self.fallback_models) + 1)

        for attempt in range(max_attempts):
            try:
                # 輪詢 API Key
                api_key = api_keys[attempt % len(api_keys)]
                genai.configure(api_key=api_key)

                model = genai.GenerativeModel(current_model)

                # 調用 API
                resp = model.generate_content(
                    [{"role": "user", "parts": [prompt]}],
                    generation_config={"temperature": 0.3}
                )

                result_text = (resp.text or "").strip()

                # 解析 JSON 回應
                summary_data = self._parse_summary_response(result_text)

                if summary_data:
                    if fallback_index >= 0:
                        print(f"✅ 使用備援模型 {current_model} 成功生成摘要")

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

                    return summary_data, current_model, token_usage

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 檢查是否為配額錯誤
                is_quota_error = (
                    "429" in error_msg or
                    "quota" in error_msg.lower() or
                    "Quota exceeded" in error_msg
                )

                if is_quota_error:
                    quota_exceeded_count += 1
                    print(f"⚠️ Google API Key 配額已用完 (嘗試 {attempt + 1}，模型: {current_model})")

                    # 如果所有 keys 都配額耗盡，嘗試切換模型
                    if quota_exceeded_count >= len(api_keys):
                        fallback_index += 1

                        if fallback_index < len(self.fallback_models):
                            current_model = self.fallback_models[fallback_index]
                            print(f"💡 切換到備用模型 {current_model}")
                            tried_models.append(current_model)
                            quota_exceeded_count = 0
                            continue
                        else:
                            print(f"❌ 所有模型的配額都已用完")
                            break
                else:
                    print(f"⚠️ API 調用失敗 (嘗試 {attempt + 1}): {error_msg}")

                if attempt < max_attempts - 1:
                    continue

        print(f"❌ 無法生成摘要。已嘗試模型: {', '.join(tried_models)}")
        return None, "", None

    def _get_summary_prompt(self, language: str, text: str) -> str:
        """生成摘要的 prompt

        Args:
            language: 語言代碼
            text: 逐字稿文字

        Returns:
            完整的 prompt
        """
        # 限制文字長度避免超出 token 限制
        max_length = 30000
        if len(text) > max_length:
            text = text[:max_length] + "..."

        if language == "zh":
            return f"""【角色設定】
你是一個自然語言處理 API，專門負責將語音轉錄文字轉換為結構化的 JSON 數據。你的輸出將直接被程式碼解析，請務必嚴格遵守格式要求。

【任務說明】
請分析輸入的「轉錄文字」，識別其情境（會議、講座、訪談、或其他），並提取關鍵資訊。

【處理邏輯】
1. 情境識別：判斷文本屬於哪種類型。
2. 動態提取：
   - 若為會議：重點提取「待辦事項 (Action Items)」與「決議」。
   - 若為講座：重點提取「核心概念」與「知識點」。
   - 若為訪談：重點提取「受訪者觀點」與「金句」。
   - 若為一般內容：提取主要論點與結論。
3. 資料清洗：修正錯別字，去除贅字，確保摘要內容通順專業。

【輸出格式 - JSON Schema】
請僅輸出一個合法的 JSON 物件，不要包含 Markdown 標記（如 ```json）或任何額外文字。JSON 結構如下：

{{
  "meta": {{
    "type": "Meeting | Lecture | Interview | General",
    "detected_topic": "自動生成的標題或主題",
    "sentiment": "Positive | Neutral | Negative"
  }},
  "summary": "200字以內的執行摘要 (Executive Summary)",
  "key_points": [
    "條列式重點1",
    "條列式重點2",
    "條列式重點3"
  ],
  "segments": [
    {{
      "topic": "該段落的小標題",
      "content": "該段落的詳細摘要",
      "keywords": ["關鍵字1", "關鍵字2"]
    }}
  ],
  "action_items": [
    {{
      "owner": "負責人（若無則為 null）",
      "task": "任務內容",
      "deadline": "期限（若無則為 null）"
    }}
  ]
}}

【注意事項】
- key_points 請提供 3-5 個重點
- segments 請依內容邏輯分為 2-4 個段落
- action_items 若非會議或無待辦事項，請回傳空陣列 []
- 所有文字請使用繁體中文

【輸入文字】
{text}"""

        elif language == "ja":
            return f"""【役割設定】
あなたは自然言語処理APIで、音声書き起こしテキストを構造化JSONデータに変換する専門家です。出力はコードで直接解析されるため、フォーマット要件を厳守してください。

【タスク説明】
入力された「書き起こしテキスト」を分析し、シナリオ（会議、講義、インタビュー、その他）を識別して、重要な情報を抽出してください。

【処理ロジック】
1. シナリオ識別：テキストのタイプを判断。
2. 動的抽出：
   - 会議の場合：「アクションアイテム」と「決定事項」を重点的に抽出。
   - 講義の場合：「核心概念」と「知識ポイント」を重点的に抽出。
   - インタビューの場合：「インタビュイーの見解」と「名言」を重点的に抽出。
3. データクリーニング：誤字を修正し、冗長な表現を削除。

【出力形式 - JSON Schema】
有効なJSONオブジェクトのみを出力してください。Markdownマーク（```jsonなど）や追加テキストは含めないでください。

{{
  "meta": {{
    "type": "Meeting | Lecture | Interview | General",
    "detected_topic": "自動生成されたタイトルまたはトピック",
    "sentiment": "Positive | Neutral | Negative"
  }},
  "summary": "200文字以内のエグゼクティブサマリー",
  "key_points": ["ポイント1", "ポイント2", "ポイント3"],
  "segments": [
    {{
      "topic": "セグメントのサブタイトル",
      "content": "セグメントの詳細な要約",
      "keywords": ["キーワード1", "キーワード2"]
    }}
  ],
  "action_items": [
    {{
      "owner": "担当者（なければnull）",
      "task": "タスク内容",
      "deadline": "期限（なければnull）"
    }}
  ]
}}

【入力テキスト】
{text}"""

        elif language == "ko":
            return f"""【역할 설정】
당신은 음성 전사 텍스트를 구조화된 JSON 데이터로 변환하는 자연어 처리 API입니다. 출력은 코드에서 직접 파싱되므로 형식 요구 사항을 엄격히 준수하세요.

【작업 설명】
입력된 "전사 텍스트"를 분석하여 시나리오(회의, 강의, 인터뷰 또는 기타)를 식별하고 핵심 정보를 추출하세요.

【처리 로직】
1. 시나리오 식별: 텍스트 유형 판단.
2. 동적 추출:
   - 회의인 경우: "액션 아이템"과 "결정 사항" 중점 추출.
   - 강의인 경우: "핵심 개념"과 "지식 포인트" 중점 추출.
   - 인터뷰인 경우: "인터뷰이 관점"과 "명언" 중점 추출.
3. 데이터 정리: 오타 수정, 불필요한 표현 제거.

【출력 형식 - JSON Schema】
유효한 JSON 객체만 출력하세요. Markdown 마크(```json 등)나 추가 텍스트를 포함하지 마세요.

{{
  "meta": {{
    "type": "Meeting | Lecture | Interview | General",
    "detected_topic": "자동 생성된 제목 또는 주제",
    "sentiment": "Positive | Neutral | Negative"
  }},
  "summary": "200자 이내의 요약",
  "key_points": ["포인트1", "포인트2", "포인트3"],
  "segments": [
    {{
      "topic": "세그먼트 소제목",
      "content": "세그먼트 상세 요약",
      "keywords": ["키워드1", "키워드2"]
    }}
  ],
  "action_items": [
    {{
      "owner": "담당자(없으면 null)",
      "task": "작업 내용",
      "deadline": "기한(없으면 null)"
    }}
  ]
}}

【입력 텍스트】
{text}"""

        else:  # English and others
            return f"""【Role Definition】
You are a natural language processing API specialized in converting speech-to-text transcripts into structured JSON data. Your output will be directly parsed by code, so please strictly follow the format requirements.

【Task Description】
Analyze the input "transcript text", identify its context (Meeting, Lecture, Interview, or General), and extract key information.

【Processing Logic】
1. Context Identification: Determine the type of content.
2. Dynamic Extraction:
   - For Meetings: Focus on extracting "Action Items" and "Decisions".
   - For Lectures: Focus on extracting "Core Concepts" and "Key Learnings".
   - For Interviews: Focus on extracting "Interviewee Perspectives" and "Notable Quotes".
   - For General: Extract main arguments and conclusions.
3. Data Cleaning: Correct typos, remove filler words, ensure professional and coherent summaries.

【Output Format - JSON Schema】
Output only a valid JSON object. Do not include Markdown markers (such as ```json) or any additional text.

{{
  "meta": {{
    "type": "Meeting | Lecture | Interview | General",
    "detected_topic": "Auto-generated title or topic",
    "sentiment": "Positive | Neutral | Negative"
  }},
  "summary": "Executive summary within 200 words",
  "key_points": [
    "Key point 1",
    "Key point 2",
    "Key point 3"
  ],
  "segments": [
    {{
      "topic": "Segment subtitle",
      "content": "Detailed summary of this segment",
      "keywords": ["keyword1", "keyword2"]
    }}
  ],
  "action_items": [
    {{
      "owner": "Person responsible (null if none)",
      "task": "Task description",
      "deadline": "Deadline mentioned (null if none)"
    }}
  ]
}}

【Notes】
- Provide 3-5 key_points
- Divide content into 2-4 logical segments
- Return empty array [] for action_items if not a meeting or no action items found

【Input Text】
{text}"""

    def _parse_summary_response(self, response: str) -> Optional[Dict[str, Any]]:
        """解析 AI 回應的 JSON

        Args:
            response: AI 回應文字

        Returns:
            解析後的摘要資料，失敗返回 None
        """
        try:
            # 移除可能的 markdown 標記
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            # 解析 JSON
            data = json.loads(response)

            # 處理 meta 欄位
            meta = data.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}

            parsed_meta = {
                "type": meta.get("type", "General"),
                "detected_topic": meta.get("detected_topic", ""),
                "sentiment": meta.get("sentiment", "Neutral")
            }

            # 驗證 type 值
            valid_types = ["Meeting", "Lecture", "Interview", "General"]
            if parsed_meta["type"] not in valid_types:
                parsed_meta["type"] = "General"

            # 驗證 sentiment 值
            valid_sentiments = ["Positive", "Neutral", "Negative"]
            if parsed_meta["sentiment"] not in valid_sentiments:
                parsed_meta["sentiment"] = "Neutral"

            # 處理 summary
            summary = data.get("summary", "")
            if not isinstance(summary, str):
                summary = ""

            # 處理 key_points
            key_points = data.get("key_points", [])
            if not isinstance(key_points, list):
                key_points = []
            key_points = [str(p) for p in key_points[:5]]  # 最多 5 條

            # 處理 segments
            segments_raw = data.get("segments", [])
            if not isinstance(segments_raw, list):
                segments_raw = []

            segments = []
            all_keywords = []
            for seg in segments_raw[:4]:  # 最多 4 個段落
                if isinstance(seg, dict):
                    seg_keywords = seg.get("keywords", [])
                    if not isinstance(seg_keywords, list):
                        seg_keywords = []
                    seg_keywords = [str(k) for k in seg_keywords[:5]]
                    all_keywords.extend(seg_keywords)

                    segments.append({
                        "topic": str(seg.get("topic", "")),
                        "content": str(seg.get("content", "")),
                        "keywords": seg_keywords
                    })

            # 處理 action_items
            action_items_raw = data.get("action_items", [])
            if not isinstance(action_items_raw, list):
                action_items_raw = []

            action_items = []
            for item in action_items_raw[:10]:  # 最多 10 個待辦
                if isinstance(item, dict) and item.get("task"):
                    action_items.append({
                        "owner": item.get("owner"),
                        "task": str(item.get("task", "")),
                        "deadline": item.get("deadline")
                    })

            # 組合結果（包含向後兼容的欄位）
            return {
                "meta": parsed_meta,
                "summary": summary[:500],  # 最多 500 字
                "key_points": key_points,
                "segments": segments,
                "action_items": action_items,
                # 向後兼容欄位
                "highlights": key_points,  # 映射到 key_points
                "keywords": list(set(all_keywords))[:10]  # 從 segments 收集關鍵字
            }

        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失敗: {e}")
            print(f"回應內容: {response[:200]}...")
            return None
        except Exception as e:
            print(f"❌ 解析回應失敗: {e}")
            return None

    def _load_google_api_keys(self) -> List[str]:
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

        return keys
