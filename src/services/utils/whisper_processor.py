"""
WhisperProcessor - Whisper 轉錄處理器
職責：Whisper 模型的封裝（無狀態工具類）
"""

from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, TYPE_CHECKING
import bisect
import subprocess
import json
import re
import os
from pydub import AudioSegment
from concurrent.futures import ProcessPoolExecutor, as_completed

# faster_whisper 是 ML 重依賴。
# - GPU Worker / local 開發：有裝（requirements.txt），轉錄走 WhisperModel
# - AWS Web Server / CI 測試：沒裝（requirements-web.txt 不含），WhisperModel = None
# 用 try/except 比舊版「靠 DEPLOY_ENV 環境變數決定」乾淨：CI 不需特別設環境變數也不會炸
try:
    from faster_whisper import WhisperModel, BatchedInferencePipeline
except ImportError:
    WhisperModel = None
    BatchedInferencePipeline = None

from src.utils.logger import get_logger

log = get_logger(__name__)


# ── 早期重切段參數 ────────────────────────────────────────────
# batched(turbo/GPU)的 segment 以 VAD 語音塊為界 → 連續講話會變超長 segment。
# 在 whisper 輸出當下、用 word timestamps 把長段依「字間停頓 / 長度上限」切成較短碎片
# （word timestamps 用完即丟，不外流到 orchestrator/diarization/標點，避免碰下游邏輯）。
# 可調：env 可覆寫（worker 改 .env.worker + 重啟即生效，免重新部署 → 方便現場調）。
RESEG_MAX_SEGMENT_SEC = float(os.getenv("RESEG_MAX_SEGMENT_SEC", "6"))      # 段長硬上限，超過強制切
RESEG_GAP_THRESHOLD_SEC = float(os.getenv("RESEG_GAP_THRESHOLD_SEC", "0.4"))  # 字間停頓 > 此值即切
RESEG_MIN_SEGMENT_SEC = float(os.getenv("RESEG_MIN_SEGMENT_SEC", "1.0"))    # 累積未達此長度時，小停頓不切

# GPU 是否走 BatchedInferencePipeline。預設 true（吞吐高，prod 現狀）。
# 設 false → GPU 改走 sequential model.transcribe：連續解 + 溫度 fallback，覆蓋率高、
# 困難音段較不會整段掉，但較慢（無批次平行）。env 可調，方便比較。
_USE_BATCHED = os.getenv("WHISPER_BATCHED", "true").strip().lower() not in ("false", "0", "no")


def _normalize_language(language: Optional[str]) -> Optional[str]:
    """Map zh-TW/zh-CN to zh for Whisper (which only supports 'zh').

    nan-TW（台語）同樣映到 zh：台語模型（Breeze-ASR-26）是 whisper-large-v2
    微調，tokenizer 只有標準 Whisper 語言 token，台語音檔的漢字輸出走 zh token；
    若 worker 未配置台語專用模型而 fallback 到預設模型，zh 也是最接近的退路。
    """
    if language in ("zh-TW", "zh-CN", "nan-TW"):
        return "zh"
    return language


def _convert_chinese_script(text: str, language: Optional[str]) -> str:
    """Convert Chinese text to Traditional or Simplified after transcription."""
    if language == "zh-TW":
        from zhconv import convert
        return convert(text, "zh-hant")
    elif language == "zh-CN":
        from zhconv import convert
        return convert(text, "zh-hans")
    return text


def _collapse_repeated_segments(segments: List[Dict], max_repeat: int = 2) -> List[Dict]:
    """壓縮連續完全相同 text 的 segments，避免 Whisper 幻覺觸發下游 LLM 重複迴圈。

    保留前 max_repeat 個，最後一個的 end 延伸到原 run 末尾以保留正確時長。
    """
    if not segments:
        return segments

    result: List[Dict] = []
    i = 0
    while i < len(segments):
        current_text = segments[i]["text"].strip()
        j = i + 1
        while j < len(segments) and segments[j]["text"].strip() == current_text:
            j += 1

        run_length = j - i
        if run_length <= max_repeat:
            result.extend(segments[i:j])
        else:
            kept = [dict(seg) for seg in segments[i:i + max_repeat]]
            kept[-1]["end"] = segments[j - 1]["end"]
            result.extend(kept)
            log.warning(
                "whisper.hallucination.collapsed",
                text=current_text,
                run_length=run_length,
                max_repeat=max_repeat,
            )
        i = j
    return result


# ── 幻覺 deny_list ──────────────────────────────────────────────
# Whisper 訓練語料含大量網路字幕，靜音/雜訊段沒有聲學證據時會「背出」這些字幕台詞
# boilerplate（移除 initial_prompt 後大幅減少，但低音量雜訊仍偶發）。這些片語在真實
# 語音逐字稿中幾乎不可能出現，整段命中即丟。
# 保守原則：只列「絕不會是真實語音」的字幕/頻道宣傳台詞，避免誤刪正常句子；命中皆 log。
# 比對前先去除空白（Whisper 可能在 CJK 間插空格），故 pattern 不含空白。
_HALLUCINATION_PATTERNS = [
    re.compile(p) for p in [
        r"Amara\.?org",                                  # (中文)字幕由Amara.org社群/社区提供
        r"字幕.{0,4}社[群區区團团].{0,2}提供",            # 字幕由…社群提供 變體
        r"(中文)?字幕.{0,6}志[願愿]者",                   # 中文字幕志願者 / 字幕由志願者提供
        r"請不吝.{0,8}(點贊|點讚|訂閱|订阅|轉發|转发|打賞|打赏|分享)",  # 頻道宣傳
        r"明[鏡镜].{0,10}(需要您的支持|點點欄目|频道|新闻)",
        r"^(由)?.{0,4}(本字幕|本影片|本视频).{0,8}(提供|製作|制作)$",
        r"詞曲李宗盛",                                    # 具體歌曲 credit 幻覺（字面比對，不擴及泛詞曲）
    ]
]


def _filter_hallucination_segments(segments: List[Dict]) -> List[Dict]:
    """丟掉整段為 Whisper 字幕/頻道 boilerplate 幻覺的 segment。

    比對前去除空白正規化；命中 deny_list 即整段丟棄並 log（可審計，方便日後調 pattern）。
    只比對整段文字，不切割保留——避免誤傷夾雜真實語音的長段。
    """
    if not segments:
        return segments

    kept: List[Dict] = []
    for seg in segments:
        raw = seg.get("text", "")
        norm = re.sub(r"\s+", "", raw.strip())
        hit = next((p.pattern for p in _HALLUCINATION_PATTERNS if p.search(norm)), None)
        if hit:
            log.warning(
                "whisper.hallucination.denylist_dropped",
                text=raw.strip(),
                pattern=hit,
                start=seg.get("start"),
                end=seg.get("end"),
            )
            continue
        kept.append(seg)
    return kept


def _resegment_by_words(segments: List[Dict]) -> List[Dict]:
    """把(可能很長的) whisper segments 依字間停頓 / 長度切成較短碎片。

    輸入：含 `words`（faster-whisper Word list，或 None）的 segment dict。
    輸出：{start, end, text, words} 的 segment dict——words 轉成 plain dict
    列表 [{start, end, word}, ...] 供下游 word 級語者對齊使用；passthrough/
    degenerate 分支不帶 words（下游以「缺 words」為 fallback 訊號）。

    切點：逐字累積，遇到任一即斷段——
      - 累積長度 ≥ RESEG_MAX_SEGMENT_SEC（硬上限），或
      - 與下一字的停頓 > RESEG_GAP_THRESHOLD_SEC 且累積已達 RESEG_MIN_SEGMENT_SEC
    `words` 為空（無語音段等）→ 原樣保留不切。
    """
    out: List[Dict] = []

    def _flush(words_run: list, end: float) -> None:
        text = "".join(w.word for w in words_run).strip()
        if text:
            out.append({
                "start": round(words_run[0].start, 3),
                "end": round(end, 3),
                "text": text,
                "words": [
                    {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                    for w in words_run
                ],
            })

    for seg in segments:
        words = seg.get("words")
        if not words:
            out.append({"start": seg["start"], "end": seg["end"], "text": seg["text"]})
            continue

        # 防呆：faster-whisper batched 的 word timestamps 偶爾在長檔某些區段退化——
        # 字的起點仍對、但 duration 趨近 0，整段字擠在數毫秒內（cross-attention 對齊塌掉）。
        # 此時 word 涵蓋範圍會遠小於 segment 自身範圍。若直接拿這些壞 word 切，會把好好的
        # segment 塌縮成數毫秒 → 下游句子切分把整段話塞進極短時間。偵測到就回退用 segment
        # 級 [start,end]（batched 的 segment 時間是用 timestamp token 算的、可靠），交給後續處理。
        seg_span = float(seg.get("end", 0.0)) - float(seg.get("start", 0.0))
        word_span = float(words[-1].end) - float(words[0].start)
        if seg_span > 0.5 and word_span < seg_span * 0.5:
            log.warning(
                "whisper.resegment.degenerate_words",
                seg_span=round(seg_span, 3), word_span=round(word_span, 3),
                seg_start=round(float(seg.get("start", 0.0)), 3),
            )
            out.append({"start": seg["start"], "end": seg["end"], "text": seg["text"]})
            continue

        cur: list = []
        for i, w in enumerate(words):
            cur.append(w)
            seg_len = w.end - cur[0].start
            nxt_gap = (words[i + 1].start - w.end) if i + 1 < len(words) else None
            force = seg_len >= RESEG_MAX_SEGMENT_SEC
            pause = (
                nxt_gap is not None
                and nxt_gap > RESEG_GAP_THRESHOLD_SEC
                and seg_len >= RESEG_MIN_SEGMENT_SEC
            )
            if force or pause:
                _flush(cur, w.end)
                cur = []
        if cur:
            _flush(cur, cur[-1].end)

    return out


def _apply_time_offset(seg: Dict, offset: float) -> Dict:
    """回傳平移後的 segment；若含 words，每個 word 的 start/end 同步 +offset。"""
    shifted = {
        "start": seg["start"] + offset,
        "end": seg["end"] + offset,
        "text": seg["text"],
    }
    words = seg.get("words")
    if words:
        shifted["words"] = [
            {**w, "start": w["start"] + offset, "end": w["end"] + offset}
            for w in words
        ]
    return shifted


# 重疊搶話區（兩個 diar turn 互相重疊、word 被雙方完整罩住）常出現「重疊秒數精確平手」——
# 嚴格 `>` 比較只會判給先迭代到的 turn，等同偏袒固定順序、與實際插話證據無關。
# PROXIMITY_WEIGHT 只在 overlap_fraction 近平手時才有感（見 _turn_score）：
# word 落在「短 turn 的正中央」= 插話證據強（該 turn 幾乎就是為了涵蓋這個字才短）；
# 落在「長 turn 的尾端」= 證據弱（掃到的只是長 turn 尾巴，中心離很遠）。
# 權重刻意壓低——overlap_fraction 差距明顯時（見驗收 b）proximity 不該蓋過重疊本身的證據力。
PROXIMITY_WEIGHT = 0.1


def _build_turn_index(diar_turns: List[Dict]) -> Tuple[List[Dict], List[float], List[float]]:
    """依 start 排序 diar turns + 建 prefix max-end 陣列，供 bisect 視窗查詢用。

    回傳 (sorted_turns, starts, prefix_max_end)：
    - starts[i] = sorted_turns[i]["start"]（給 bisect 用）
    - prefix_max_end[i] = max(sorted_turns[0..i].end)（非遞減，用來判斷「再往回掃也不會
      有重疊」的提前中止條件——重疊需要 turn.end > span.start，prefix max 提前變得
      ≤ span.start 就代表 0..i 已無候選）
    """
    sorted_turns = sorted(diar_turns, key=lambda t: t["start"])
    starts = [t["start"] for t in sorted_turns]
    prefix_max_end: List[float] = []
    running_max = float("-inf")
    for t in sorted_turns:
        running_max = max(running_max, t["end"])
        prefix_max_end.append(running_max)
    return sorted_turns, starts, prefix_max_end


def _turn_score(start: float, end: float, turn: Dict) -> float:
    """單一 turn 對 [start,end] 的評分：overlap_fraction + PROXIMITY_WEIGHT * proximity。

    - overlap_fraction：重疊秒數 / span 長度（span 長度 0 時視為 1e-6 防除零）。
    - proximity：1 - |span中點 - turn中點| / (turn長度/2)，下限 0；turn 長度 0 時為 0。
    """
    span_len = max(end - start, 1e-6)
    overlap = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
    overlap_fraction = overlap / span_len

    turn_len = turn["end"] - turn["start"]
    if turn_len <= 0:
        proximity = 0.0
    else:
        span_mid = (start + end) / 2.0
        turn_mid = (turn["start"] + turn["end"]) / 2.0
        proximity = max(0.0, 1 - abs(span_mid - turn_mid) / (turn_len / 2.0))

    return overlap_fraction + PROXIMITY_WEIGHT * proximity


def _pick_speaker_indexed(
    start: float,
    end: float,
    sorted_turns: List[Dict],
    starts: List[float],
    prefix_max_end: List[float],
) -> Optional[str]:
    """[start,end] 對 turns 取最高 `_turn_score` 者；零重疊 → 以區間中點距 turn 最近者。

    用 `_build_turn_index` 產出的排序+prefix-max-end 索引，只掃可能與 span 重疊的
    turns（bisect 找上界 + 往回掃到 prefix max-end ≤ span.start 為止），
    避免每個 word 都要 O(turns) 全掃。turns 空 → None。
    """
    if not sorted_turns:
        return None

    # start < end 的 turns 都在 starts[:idx] 內（bisect_left 找第一個 start >= end 的位置）
    idx = bisect.bisect_left(starts, end)

    best_speaker = None
    best_score = 0.0
    i = idx - 1
    while i >= 0:
        if prefix_max_end[i] <= start:
            # 0..i 的 turn.end 全都 <= start → 之後不可能再有重疊，提前中止
            break
        turn = sorted_turns[i]
        overlap = max(0.0, min(end, turn["end"]) - max(start, turn["start"]))
        if overlap > 0.0:
            score = _turn_score(start, end, turn)
            if score > best_score:
                best_score = score
                best_speaker = turn["speaker"]
        i -= 1

    if best_speaker is not None:
        return best_speaker

    # 零重疊（落在 turn 間隙）→ 依區間中點距最近的 turn 歸屬（rare path，全掃沒關係）
    midpoint = (start + end) / 2.0

    def _distance(turn: Dict) -> float:
        if midpoint < turn["start"]:
            return turn["start"] - midpoint
        if midpoint > turn["end"]:
            return midpoint - turn["end"]
        return 0.0

    return min(sorted_turns, key=_distance)["speaker"]


def _pick_speaker_for_span(start: float, end: float, diar_turns: List[Dict]) -> Optional[str]:
    """[start,end] 對 turns 取最高重疊+貼近度評分者；零重疊 → 以區間中點距 turn 最近者。

    模組層函數簽名維持不變（測試直接呼叫）；內部臨時建索引後委派給
    `_pick_speaker_indexed`。效能敏感路徑（逐 word 迴圈）應改用
    `assign_speakers_word_level` 內建的索引重用，不要在迴圈裡呼叫本函數。
    """
    sorted_turns, starts, prefix_max_end = _build_turn_index(diar_turns)
    return _pick_speaker_indexed(start, end, sorted_turns, starts, prefix_max_end)


def _smooth_isolated_word_speakers(speakers: List[str]) -> List[str]:
    """孤立單字（run 長度 1 且前後 run 為同一 speaker）改判為鄰居 speaker。

    以 run 為單位由左至右歸併：孤立 run 併入鄰居後視為同一 run 繼續判斷，
    交替雜訊（A,B,A,B,A）收斂為單一語者，不會殘留新的孤立 run。
    首尾 run 沒有雙側鄰居，一律不動。
    """
    runs: List[List] = []  # [speaker, 長度]
    for spk in speakers:
        if runs and runs[-1][0] == spk:
            runs[-1][1] += 1
        else:
            runs.append([spk, 1])

    merged: List[List] = []
    for run in runs:
        merged.append(run)
        while (
            len(merged) >= 3
            and merged[-2][1] == 1
            and merged[-3][0] == merged[-1][0]
        ):
            absorbed = [merged[-3][0], merged[-3][1] + merged[-2][1] + merged[-1][1]]
            merged[-3:] = [absorbed]

    result: List[str] = []
    for spk, count in merged:
        result.extend([spk] * count)
    return result


def assign_speakers_word_level(
    transcription_segments: List[Dict],
    diar_turns: List[Dict],
) -> List[Dict]:
    """word 級語者指派 + smoothing + 語者變換點切段。

    輸入：segments（可含 words: [{start,end,word}]）、diar turns [{start,end,speaker}]。
    輸出：[{start,end,text,speaker}]，不含 words。
    - 有 words：逐 word 用 `_pick_speaker_indexed`（重疊+貼近度評分，見 `_turn_score`）
      → `_smooth_isolated_word_speakers` → 依 speaker 變換點切開；子段 start=首字 start、
      end=末字 end、text = "".join(w["word"]).strip()（沿用 `_resegment_by_words` 的
      拼接慣例，中英皆正確）。
    - 無 words（passthrough/degenerate 段）：整段用同一份索引評分。
    - diar_turns 空：原樣回傳（不加 speaker、不剝 words——words 的剝除統一由
      orchestrator `_run_transcription_phase` 出口單點處理，此處不重複）。

    效能：turns 只排序 + 建 prefix max-end 索引一次（`_build_turn_index`），
    每個 word/segment 呼叫 `_pick_speaker_indexed` 重用同一份索引（bisect 找窗口，
    不對全部 turns 掃描），把配對成本從 O(words×turns) 降到窗口內 turns 的量級。

    Smoothing 只在 segment 內做（words 只存在於 segment 內，reseg 切點本身就是停頓處），
    跨 segment 的孤立段不在本函數範圍。
    """
    if not diar_turns:
        return transcription_segments

    sorted_turns, starts, prefix_max_end = _build_turn_index(diar_turns)

    out: List[Dict] = []
    for seg in transcription_segments:
        words = seg.get("words")
        if not words:
            speaker = _pick_speaker_indexed(
                seg.get("start", 0.0), seg.get("end", 0.0), sorted_turns, starts, prefix_max_end
            )
            out.append({
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": seg.get("text", ""),
                "speaker": speaker,
            })
            continue

        word_speakers = _smooth_isolated_word_speakers([
            _pick_speaker_indexed(w["start"], w["end"], sorted_turns, starts, prefix_max_end)
            for w in words
        ])

        run_start = 0
        for i in range(1, len(words) + 1):
            if i == len(words) or word_speakers[i] != word_speakers[run_start]:
                run_words = words[run_start:i]
                text = "".join(w["word"] for w in run_words).strip()
                if text:
                    out.append({
                        "start": run_words[0]["start"],
                        "end": run_words[-1]["end"],
                        "text": text,
                        "speaker": word_speakers[run_start],
                    })
                run_start = i

    return out


def transcribe_chunk_worker(
    chunk_path: str,
    model_name: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
    num_workers: int,
    language: Optional[str] = None
) -> Tuple[int, str, List[Dict], str]:
    """
    獨立進程中執行的 chunk 轉錄函數（必須是頂層函數以支持 pickle）

    Args:
        chunk_path: chunk 文件路徑（字符串，可序列化）
        model_name: Whisper 模型名稱
        device: 設備（auto/cpu/cuda）
        compute_type: 計算類型（int8/float16/float32）
        cpu_threads: CPU 線程數
        num_workers: worker 數量
        language: 語言代碼

    Returns:
        (chunk_idx, text, segments, detected_language)
    """
    from faster_whisper import WhisperModel
    from pathlib import Path
    import re

    log.debug("whisper.worker.started", chunk_path=chunk_path)

    # 從文件名提取 chunk_idx（例如：_temp_input_chunk_3.wav → 3）
    chunk_idx = int(re.search(r'chunk_(\d+)', chunk_path).group(1))

    log.debug("whisper.worker.model.loading", chunk_idx=chunk_idx, model_name=model_name)

    # 在進程內獨立創建 Whisper 模型實例
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=num_workers
    )

    log.debug("whisper.worker.transcribe.started", chunk_idx=chunk_idx)

    normalized_lang = _normalize_language(language)
    segments_list, info = model.transcribe(
        chunk_path,
        language=normalized_lang,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=1000),
        condition_on_previous_text=False,
        repetition_penalty=1.1,
        no_repeat_ngram_size=3,
        word_timestamps=True,
        hallucination_silence_threshold=2.0,
    )

    # 收集結果（保留 words 供重切段用；字型轉換由呼叫端的清洗步驟統一處理）
    segments = []
    for segment in segments_list:
        segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": segment.words,
        })

    # 壓縮重複幻覺 → 丟字幕 boilerplate 幻覺 → 依 word timestamps 重切長段 → 重建 full_text
    segments = _collapse_repeated_segments(segments)
    segments = _filter_hallucination_segments(segments)
    segments = _resegment_by_words(segments)
    full_text = " ".join(seg["text"] for seg in segments)
    detected_language = info.language

    log.debug("whisper.worker.transcribe.completed", chunk_idx=chunk_idx, text_length=len(full_text))

    # 清理臨時文件
    try:
        Path(chunk_path).unlink()
        log.debug("whisper.worker.tempfile.deleted", chunk_idx=chunk_idx)
    except Exception as e:
        log.warning("whisper.worker.tempfile.cleanup_failed", chunk_idx=chunk_idx, error=str(e))

    return chunk_idx, full_text, segments, detected_language


class WhisperProcessor:
    """Whisper 轉錄處理器

    封裝 Whisper 模型的轉錄功能，提供無狀態的轉錄方法
    """

    def __init__(self, model: WhisperModel, model_name: str = "medium"):
        """初始化 WhisperProcessor

        Args:
            model: Whisper 模型實例
            model_name: 模型名稱（用於 worker 進程中重新載入模型）
        """
        self.model = model
        self.model_name = model_name  # 保存模型名稱供 worker 使用
        self._batched = None  # BatchedInferencePipeline，GPU 路徑首次使用時 lazy 建立
        # batched 批次大小：每批同時餵 GPU 的 VAD 視窗數。T4 16GB + turbo 可調到 16。
        self._batch_size = int(os.getenv("WHISPER_BATCH_SIZE", "8"))

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[str, List[Dict], str]:
        """轉錄音檔（單次轉錄，不分段）

        Args:
            audio_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）
            progress_callback: segment 完成時呼叫 callback(elapsed_seconds, total_seconds)

        Returns:
            (完整文字, segments 列表, 偵測到的語言)
        """
        audio_path = self._ensure_valid_audio(audio_path)
        segments_list, detected_language = self._transcribe_with_timestamps(
            audio_path, language, progress_callback=progress_callback,
        )

        # 合併所有 segment 的文字
        full_text = " ".join(seg["text"] for seg in segments_list)

        return full_text, segments_list, detected_language

    def _has_gpu(self) -> bool:
        """偵測是否有可用 GPU，決定走 batched(GPU)或平行多進程(CPU)。"""
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def _get_batched_model(self):
        """Lazy 建立並快取 BatchedInferencePipeline（包住同一個 cached model）。

        batched 在 VAD 切出的視窗上做批次推論，GPU 吞吐遠高於逐段序列。
        只在 GPU 路徑使用——CPU 仍走多進程平行。
        """
        if self._batched is None:
            self._batched = BatchedInferencePipeline(model=self.model)
        return self._batched

    def transcribe_in_chunks(
        self,
        audio_path: Path,
        chunk_duration_ms: int = 1500000,  # 25 分鐘
        language: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[str, List[Dict], str]:
        """長音檔轉錄。GPU 走整檔 batched、CPU 走多進程平行，由 device 自動決定。

        GPU：BatchedInferencePipeline 內建 VAD 切分，可直接吞整段長音檔並批次
        推論，不需手動分段——進度 0→100% 連續、程式更簡單。
        CPU：單張 GPU 不存在時，多進程平行(各進程獨立模型)才有意義；GPU 上
        多進程只會搶 VRAM 不會更快。對外是單一方法，呼叫端(Orchestrator)
        不需知道跑在什麼裝置上。chunk_duration_ms 僅 CPU 平行路徑使用。
        """
        if self._has_gpu():
            # batched 內建 VAD 切分，整檔單次轉錄即可，毋須手動 25 分鐘分段
            audio_path = self._ensure_valid_audio(audio_path)
            segments_list, detected_language = self._transcribe_with_timestamps(
                audio_path, language, progress_callback=progress_callback,
            )
            full_text = " ".join(seg["text"] for seg in segments_list)
            return full_text, segments_list, detected_language
        # 平行版 callback 是 (completed, total[, processing])；統一收斂成 (done, total)
        cb = None
        if progress_callback is not None:
            def cb(completed, total, *_extra):
                progress_callback(completed, total)
        return self.transcribe_in_chunks_parallel(
            audio_path,
            chunk_duration_ms=chunk_duration_ms,
            language=language,
            progress_callback=cb,
        )

    def transcribe_in_chunks_parallel(
        self,
        audio_path: Path,
        chunk_duration_ms: int = 1500000,  # 25 分鐘
        language: Optional[str] = None,
        max_workers: int = 3,  # 優化：默認 3 個並行進程
        progress_callback: Optional[callable] = None,
        cancel_check: Optional[callable] = None
    ) -> Tuple[str, List[Dict], str]:
        """將音檔分段後並行轉錄（使用 ProcessPoolExecutor，真正的多進程並行）

        Args:
            audio_path: 音檔路徑
            chunk_duration_ms: 每段長度（毫秒）
            language: 語言代碼（None 表示自動偵測）
            max_workers: 並行工作進程數（默認 3）
            progress_callback: 進度回調函數 callback(completed_count, total_chunks)
            cancel_check: 取消檢查函數，返回 True 表示任務被取消

        Returns:
            (完整文字, segments 列表, 偵測到的語言)
        """
        log.debug("transcribe.parallel.started")

        audio_path = self._ensure_valid_audio(audio_path)

        # 1. 獲取音檔長度並分割
        total_duration_ms = self._get_audio_duration(audio_path)
        total_minutes = total_duration_ms / 1000 / 60
        log.debug("transcribe.audio.duration", total_minutes=round(total_minutes, 1))

        if total_duration_ms <= chunk_duration_ms:
            log.debug("transcribe.direct.started", chunk_threshold_minutes=chunk_duration_ms / 1000 / 60)
            # audio_path 已 normalize，跳過重複 probe
            segments_list, detected_language = self._transcribe_with_timestamps(audio_path, language)
            full_text = " ".join(seg["text"] for seg in segments_list)
            return full_text, segments_list, detected_language

        # 智慧分段（回傳 [(chunk_path, start_seconds), ...]）
        chunk_entries = self._split_audio_into_chunks(audio_path, total_duration_ms, chunk_duration_ms)
        num_chunks = len(chunk_entries)

        # 建立 chunk_idx → start_seconds 的映射
        chunk_offsets = {}
        for chunk_idx, (_chunk_path, start_seconds) in enumerate(chunk_entries, start=1):
            chunk_offsets[chunk_idx] = start_seconds

        # 2. 使用 ProcessPoolExecutor 並行轉錄
        results = {}
        completed_count = 0
        executor = None

        log.debug("transcribe.parallel.pool.created", max_workers=max_workers)

        try:
            executor = ProcessPoolExecutor(max_workers=max_workers)

            # 提交所有任務
            log.debug("transcribe.parallel.tasks.submitting", num_chunks=num_chunks)

            # 準備參數（從當前模型實例獲取配置）
            future_to_idx = {}
            for chunk_path, _ in chunk_entries:
                future = executor.submit(
                    transcribe_chunk_worker,
                    str(chunk_path),  # 轉為字符串以支持序列化
                    self.model_name,
                    "auto",
                    "int8",
                    2,  # 優化後的 cpu_threads
                    1,  # 優化後的 num_workers（避免進程內過度並行）
                    language
                )
                chunk_idx = int(re.search(r'chunk_(\d+)', str(chunk_path)).group(1))
                future_to_idx[future] = chunk_idx

            log.debug("transcribe.parallel.tasks.submitted", num_chunks=num_chunks)

            # 計算初始正在處理中的 chunk 數量（worker 會立即拿走任務）
            processing_count = min(max_workers, num_chunks)
            # 發送初始進度（0 完成，但有 processing_count 個正在處理）
            if progress_callback:
                progress_callback(0, num_chunks, processing_count)

            # 收集結果
            for future in as_completed(future_to_idx.keys()):
                # 檢查取消
                if cancel_check and cancel_check():
                    log.warning("transcribe.parallel.cancelled")
                    # 取消所有未完成的 future
                    for f in future_to_idx.keys():
                        f.cancel()
                    # 強制關閉 executor（不等待）
                    log.debug("transcribe.parallel.pool.force_shutdown")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise Exception("任務被取消")

                try:
                    chunk_idx, text, segments, lang = future.result()
                    results[chunk_idx] = (text, segments, lang)
                    completed_count += 1

                    # 計算正在處理中的 chunk 數量
                    # 剩餘未完成的 chunk 中，最多有 max_workers 個正在處理
                    remaining = num_chunks - completed_count
                    processing_count = min(max_workers, remaining)

                    log.debug(
                        "whisper.chunk.transcribed",
                        chunk_idx=chunk_idx,
                        completed_count=completed_count,
                        num_chunks=num_chunks,
                        processing_count=processing_count,
                    )

                    # 更新進度
                    if progress_callback:
                        progress_callback(completed_count, num_chunks, processing_count)

                except Exception as e:
                    chunk_idx = future_to_idx[future]
                    log.error("whisper.chunk.transcribe_failed", chunk_idx=chunk_idx, error=str(e))
                    # 立即失敗：取消所有剩餘任務
                    for f in future_to_idx.keys():
                        f.cancel()
                    # 強制關閉 executor
                    log.debug("transcribe.parallel.pool.force_shutdown")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise Exception(f"並行轉錄失敗：{e}")

        except Exception:
            # 清理所有剩餘的 chunk 檔案
            for chunk_path, _ in chunk_entries:
                try:
                    chunk_path.unlink()
                except OSError:
                    pass
            raise

        finally:
            # 確保 executor 被正確清理
            if executor is not None:
                log.debug("transcribe.parallel.pool.cleanup")
                try:
                    # 優雅關閉，最多等待 10 秒
                    executor.shutdown(wait=True, cancel_futures=False)
                    log.debug("transcribe.parallel.pool.closed")
                except Exception as cleanup_error:
                    log.warning("transcribe.parallel.pool.cleanup_failed", error=str(cleanup_error))

        # 3. 檢查並合併結果
        if len(results) != num_chunks:
            missing = set(range(1, num_chunks + 1)) - set(results.keys())
            raise Exception(f"並行轉錄不完整，缺少 chunks: {missing}")

        # 按 chunk_idx 排序
        sorted_results = [results[idx] for idx in sorted(results.keys())]

        all_text_parts = [text for text, _, _ in sorted_results]
        all_segments = []

        # 合併 segments 並調整時間戳（使用實際切點偏移）
        for chunk_idx, (_text, segments, _lang) in enumerate(sorted_results, start=1):
            time_offset = chunk_offsets[chunk_idx]

            # 調整每個 segment 的時間戳（含 words，供下游 word 級語者對齊使用）
            for seg in segments:
                all_segments.append(_apply_time_offset(seg, time_offset))

        full_text = " ".join(all_text_parts)
        detected_language = sorted_results[0][2] if sorted_results else None

        log.info(
            "transcribe.parallel.completed",
            num_chunks=num_chunks,
            segment_count=len(all_segments),
        )
        return full_text, all_segments, detected_language

    # ========== 私有輔助方法 ==========

    def _ensure_valid_audio(self, audio_path: Path) -> Path:
        """偵測真實音訊格式，若副檔名與實際格式不符則轉碼後回傳新路徑。

        某些使用者把 M4A/AAC/MP4 改名為 .mp3 上傳，直接餵給 ffmpeg 會報
        "Failed to find two consecutive MPEG audio frames"。
        此函數用 ffprobe 偵測真實 codec，若與副檔名不符就轉成
        副檔名對應的格式（例如 .mp3 → re-encode 成真正的 MP3）。
        """
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                 '-show_streams', str(audio_path)],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return audio_path

            probe = json.loads(result.stdout)
            streams = probe.get('streams', [])
            audio_streams = [s for s in streams if s.get('codec_type') == 'audio']
            if not audio_streams:
                return audio_path

            actual_codec = audio_streams[0].get('codec_name', '').lower()
            suffix = audio_path.suffix.lower()

            # 副檔名 → 期望的 codec
            expected = {'.mp3': 'mp3', '.m4a': 'aac', '.aac': 'aac',
                        '.wav': 'pcm', '.flac': 'flac', '.ogg': 'vorbis',
                        '.opus': 'opus'}
            expected_codec = expected.get(suffix)
            if expected_codec and actual_codec.startswith(expected_codec):
                return audio_path  # 格式正確，不需轉換

            log.warning(
                "whisper.audio.codec_mismatch",
                suffix=suffix,
                actual_codec=actual_codec,
            )
            converted_path = audio_path.with_name(audio_path.stem + '_fixed' + suffix)
            convert_result = subprocess.run(
                ['ffmpeg', '-y', '-i', str(audio_path), str(converted_path)],
                capture_output=True, timeout=120
            )
            if convert_result.returncode == 0:
                log.debug("whisper.audio.reencoded", converted_path=converted_path.name)
                return converted_path
            else:
                log.warning(
                    "whisper.audio.reencode_failed",
                    error=convert_result.stderr.decode()[-200:],
                )
                return audio_path

        except Exception as e:
            log.warning("whisper.audio.validate_failed", error=str(e))
            return audio_path

    def _transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[List[Dict], str]:
        """轉錄音檔並返回帶時間戳的 segments

        Args:
            audio_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）
            progress_callback: 每個 segment 完成時呼叫 callback(elapsed_seconds, total_seconds)。
                注意：faster-whisper 的 segments 是 lazy generator，迭代時才實際運算 —
                所以 callback 自然會隨著轉錄進度發生。

        Returns:
            (segments 列表, 偵測到的語言)
        """
        log.debug("whisper.transcribe.started", audio_path=str(audio_path), language=language)

        segments_list = []
        normalized_lang = _normalize_language(language)
        transcribe_kwargs = dict(
            language=normalized_lang,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=1000),
            condition_on_previous_text=False,
            repetition_penalty=1.1,
            no_repeat_ngram_size=3,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
        )
        if self._has_gpu() and _USE_BATCHED:
            # GPU + batched：把 VAD 視窗批次餵 GPU，吞吐高；但只轉 VAD 區段、單一溫度無
            # fallback → 困難音段(低音量/雜訊)可能整段掉。WHISPER_BATCHED=false 改走下面
            # sequential（model.transcribe 連續解 + 溫度 fallback，覆蓋率高但較慢）。
            segments, info = self._get_batched_model().transcribe(
                str(audio_path), batch_size=self._batch_size, **transcribe_kwargs
            )
        else:
            segments, info = self.model.transcribe(str(audio_path), **transcribe_kwargs)
        log.debug("whisper.transcribe.model_returned")

        # 獲取 Whisper 偵測到的語言與總時長
        detected_language = info.language if hasattr(info, 'language') else None
        total_duration = float(getattr(info, "duration", 0) or 0)

        # 字型轉換由呼叫端的清洗步驟統一處理
        for segment in segments:
            segments_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": segment.words,  # 保留供重切段；不外流（_resegment 後丟棄）
            })
            if progress_callback and total_duration > 0:
                try:
                    progress_callback(segment.end, total_duration)
                except Exception as cb_err:
                    # 進度回報不該打斷轉錄本身
                    log.warning("whisper.progress_callback.failed", error=str(cb_err))

        # 壓縮重複幻覺 → 丟字幕 boilerplate 幻覺 → 依 word timestamps 重切長段
        segments_list = _collapse_repeated_segments(segments_list)
        segments_list = _filter_hallucination_segments(segments_list)
        segments_list = _resegment_by_words(segments_list)
        return segments_list, detected_language

    def _get_audio_duration(self, audio_path: Path) -> int:
        """獲取音檔總長度（毫秒）

        優先使用 ffprobe（快速，不載入記憶體），失敗時回退到 pydub

        Args:
            audio_path: 音檔路徑

        Returns:
            音檔長度（毫秒）
        """
        # 使用 ffprobe 獲取音檔資訊，不載入到記憶體
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', str(audio_path)
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                probe_data = json.loads(result.stdout)
                total_duration_seconds = float(probe_data['format']['duration'])
                return int(total_duration_seconds * 1000)

        except Exception as e:
            log.warning("whisper.duration.ffprobe_failed", error=str(e))

        # 回退到 pydub
        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)
        del audio  # 立即釋放記憶體
        return duration_ms

    def _find_silence_near(
        self,
        audio_path: Path,
        target_ms: int,
        search_range_ms: int = 30000,
        noise_db: int = -30,
        min_silence_duration: float = 0.5
    ) -> int:
        """在目標切點附近尋找最近的靜音段

        Args:
            audio_path: 音檔路徑
            target_ms: 目標切點（毫秒）
            search_range_ms: 搜尋範圍 ±（毫秒），預設 ±30 秒
            noise_db: 靜音偵測門檻（dB）
            min_silence_duration: 最短靜音長度（秒）

        Returns:
            調整後的切點（毫秒），找不到靜音則回傳原始 target_ms
        """
        search_start_s = max(0, (target_ms - search_range_ms)) / 1000.0
        search_duration_s = (search_range_ms * 2) / 1000.0

        try:
            result = subprocess.run([
                'ffmpeg', '-i', str(audio_path),
                '-ss', str(search_start_s),
                '-t', str(search_duration_s),
                '-af', f'silencedetect=noise={noise_db}dB:d={min_silence_duration}',
                '-f', 'null', '-'
            ], capture_output=True, text=True, timeout=30)

            stderr = result.stderr

            # 解析 silence_start / silence_end
            silences = []
            silence_starts = re.findall(r'silence_start:\s*([\d.]+)', stderr)
            silence_ends = re.findall(r'silence_end:\s*([\d.]+)', stderr)

            for i in range(min(len(silence_starts), len(silence_ends))):
                # ffmpeg 輸出的時間是相對於 search_start_s 的
                abs_start_ms = int((float(silence_starts[i]) + search_start_s) * 1000)
                abs_end_ms = int((float(silence_ends[i]) + search_start_s) * 1000)
                mid_ms = (abs_start_ms + abs_end_ms) // 2
                silences.append(mid_ms)

            if not silences:
                return target_ms

            # 選離目標切點最近的靜音中點
            best = min(silences, key=lambda s: abs(s - target_ms))
            log.debug(
                "whisper.split.cutpoint_adjusted",
                target_minutes=round(target_ms / 1000 / 60, 1),
                adjusted_minutes=round(best / 1000 / 60, 1),
            )
            return best

        except Exception as e:
            log.warning("whisper.split.silence_detect_failed", error=str(e))
            return target_ms

    def _split_audio_into_chunks(
        self,
        audio_path: Path,
        total_duration_ms: int,
        chunk_duration_ms: int
    ) -> List[Tuple[Path, float]]:
        """將音檔切分為多個 MP3 小段（智慧切割）

        使用 ffmpeg 流式處理，避免記憶體問題。
        切點會自動調整到附近的靜音段，避免切在對話中間。
        最後一段太短（< 20% 目標長度）時會併入前一段。

        Args:
            audio_path: 原始音檔路徑（MP3）
            total_duration_ms: 音檔總長度（毫秒）
            chunk_duration_ms: 每段目標長度（毫秒）

        Returns:
            (chunk 檔案路徑, 該段在原音檔中的起始秒數) 的列表
        """
        if isinstance(audio_path, str):
            audio_path = Path(audio_path)

        # 1. 計算切點並用靜音偵測調整
        cut_points = []  # 不含 0 和 total_duration_ms
        pos = chunk_duration_ms
        while pos < total_duration_ms:
            adjusted = self._find_silence_near(audio_path, pos)
            cut_points.append(adjusted)
            pos = adjusted + chunk_duration_ms

        # 2. 短尾合併：最後一段 < 20% 目標長度時，移除最後一個切點
        if cut_points:
            last_segment_ms = total_duration_ms - cut_points[-1]
            if last_segment_ms < chunk_duration_ms * 0.2:
                removed = cut_points.pop()
                log.debug(
                    "whisper.split.short_tail_merged",
                    last_segment_minutes=round(last_segment_ms / 1000 / 60, 1),
                    removed_cutpoint_minutes=round(removed / 1000 / 60, 1),
                )

        # 3. 建立分段區間
        boundaries = [0] + cut_points + [total_duration_ms]
        num_chunks = len(boundaries) - 1
        log.debug("whisper.split.planned", num_chunks=num_chunks)

        # 4. 依據切點切割
        chunk_files = []
        for chunk_idx in range(num_chunks):
            start_ms = boundaries[chunk_idx]
            end_ms = boundaries[chunk_idx + 1]

            log.debug(
                "whisper.split.chunk.preparing",
                chunk_idx=chunk_idx + 1,
                start_minutes=round(start_ms / 1000 / 60, 1),
                end_minutes=round(end_ms / 1000 / 60, 1),
            )

            temp_path = audio_path.parent / f"_temp_{audio_path.stem}_chunk_{chunk_idx + 1}.mp3"
            start_seconds = start_ms / 1000.0
            duration_seconds = (end_ms - start_ms) / 1000.0

            try:
                subprocess.run([
                    'ffmpeg', '-y', '-i', str(audio_path),
                    '-ss', str(start_seconds),
                    '-t', str(duration_seconds),
                    '-acodec', 'libmp3lame',
                    '-b:a', '128k',
                    '-ar', '16000',
                    '-ac', '1',
                    str(temp_path)
                ], check=True, capture_output=True, timeout=120)

            except subprocess.TimeoutExpired:
                log.warning("whisper.split.chunk.ffmpeg_timeout", chunk_idx=chunk_idx + 1)
                audio = AudioSegment.from_file(audio_path)
                chunk_audio = audio[start_ms:end_ms]
                chunk_audio.export(temp_path, format="mp3", bitrate="128k")
                del audio, chunk_audio

            except Exception as e:
                log.warning("whisper.split.chunk.ffmpeg_failed", chunk_idx=chunk_idx + 1, error=str(e))
                audio = AudioSegment.from_file(audio_path)
                chunk_audio = audio[start_ms:end_ms]
                chunk_audio.export(temp_path, format="mp3", bitrate="128k")
                del audio, chunk_audio

            chunk_files.append((temp_path, start_seconds))

        return chunk_files

    def _merge_transcription_with_diarization(
        self,
        transcription_segments: List[Dict],
        diarization_segments: List[Dict]
    ) -> str:
        """合併轉錄文字和說話者標記

        內部改為 word 級語者指派（assign_speakers_word_level）：先切到語者變換點，
        再把連續同語者子段組行——輸出格式與改動前完全一致。

        Args:
            transcription_segments: Sound Lite 轉錄結果 (帶時間戳，可能含 words)
            diarization_segments: Speaker diarization 結果

        Returns:
            合併後的文字，格式：[Speaker A] 文字內容
        """
        if not diarization_segments:
            # 沒有 diarization 結果，直接返回純文字
            return " ".join(seg.get("text", "") for seg in transcription_segments)

        assigned_segments = assign_speakers_word_level(transcription_segments, diarization_segments)

        # 把連續同 speaker 子段組行
        result_lines = []
        current_speaker = None
        current_text = []

        for seg in assigned_segments:
            text = seg.get("text", "")
            if not text.strip():
                continue

            speaker = seg.get("speaker")

            # 如果說話者改變，輸出之前的內容
            if speaker != current_speaker and current_text:
                speaker_label = f"[{current_speaker}]" if current_speaker else ""
                result_lines.append(f"{speaker_label} {''.join(current_text)}")
                current_text = []

            current_speaker = speaker
            current_text.append(text)

        # 輸出最後一段
        if current_text:
            speaker_label = f"[{current_speaker}]" if current_speaker else ""
            result_lines.append(f"{speaker_label} {''.join(current_text)}")

        return "\n\n".join(result_lines)

    def _merge_speaker_to_segments(
        self,
        transcription_segments: List[Dict],
        diarization_segments: List[Dict]
    ) -> List[Dict]:
        """將說話者資訊整合到轉錄 segments 中

        用於字幕模式：word 級語者指派 + 語者變換點切段（assign_speakers_word_level），
        輸出 segments 依語者變換點切開，不再是原 segment 逐段複製。

        Args:
            transcription_segments: Sound Lite 轉錄結果 (帶時間戳，可能含 words)
            diarization_segments: Speaker diarization 結果

        Returns:
            帶 speaker 欄位的 segments 列表（依語者變換點切分）
        """
        if not diarization_segments:
            # 沒有 diarization 結果，返回原 segments
            return transcription_segments

        # diar 非空時 assign_speakers_word_level 保證每段都有非 None speaker
        # （零重疊也會 fallback 到最近 turn），無需 UNKNOWN 保底。
        return assign_speakers_word_level(transcription_segments, diarization_segments)
