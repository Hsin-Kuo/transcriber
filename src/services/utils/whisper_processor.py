"""
WhisperProcessor - Whisper 轉錄處理器
職責：Whisper 模型的封裝（無狀態工具類）
"""

from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, TYPE_CHECKING
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


def _normalize_language(language: Optional[str]) -> Optional[str]:
    """Map zh-TW/zh-CN to zh for Whisper (which only supports 'zh')."""
    if language in ("zh-TW", "zh-CN"):
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


def _resegment_by_words(segments: List[Dict]) -> List[Dict]:
    """把(可能很長的) whisper segments 依字間停頓 / 長度切成較短碎片。

    輸入：含 `words`（faster-whisper Word list，或 None）的 segment dict。
    輸出：純 {start, end, text} 的 segment dict（words 用完即丟，不外流）。

    切點：逐字累積，遇到任一即斷段——
      - 累積長度 ≥ RESEG_MAX_SEGMENT_SEC（硬上限），或
      - 與下一字的停頓 > RESEG_GAP_THRESHOLD_SEC 且累積已達 RESEG_MIN_SEGMENT_SEC
    `words` 為空（無語音段等）→ 原樣保留不切。
    """
    out: List[Dict] = []

    def _flush(words_run: list, end: float) -> None:
        text = "".join(w.word for w in words_run).strip()
        if text:
            out.append({"start": round(words_run[0].start, 3), "end": round(end, 3), "text": text})

    for seg in segments:
        words = seg.get("words")
        if not words:
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
        initial_prompt="以下是繁體中文的逐字稿。" if normalized_lang == "zh" else None,
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

    # 壓縮重複幻覺 → 依 word timestamps 重切長段 → 重建 full_text
    segments = _collapse_repeated_segments(segments)
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

            # 調整每個 segment 的時間戳
            for seg in segments:
                adjusted_segment = {
                    "start": seg["start"] + time_offset,
                    "end": seg["end"] + time_offset,
                    "text": seg["text"]
                }
                all_segments.append(adjusted_segment)

        full_text = " ".join(all_text_parts)
        detected_language = sorted_results[0][2] if sorted_results else None

        log.info(
            "transcribe.parallel.completed",
            num_chunks=num_chunks,
            segment_count=len(all_segments),
        )
        return full_text, all_segments, detected_language

    def transcribe_with_diarization(
        self,
        audio_path: Path,
        diarization_segments: List[Dict],
        language: Optional[str] = None
    ) -> Tuple[str, List[Dict], str]:
        """轉錄音檔並合併說話者辨識結果

        Args:
            audio_path: 音檔路徑
            diarization_segments: 說話者辨識結果
            language: 語言代碼

        Returns:
            (帶說話者標記的文字, segments 列表, 偵測到的語言)
        """
        # 先轉錄
        _, segments_list, detected_language = self.transcribe(audio_path, language)

        # 合併 diarization 結果
        merged_text = self._merge_transcription_with_diarization(
            segments_list, diarization_segments
        )

        return merged_text, segments_list, detected_language

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
            initial_prompt="以下是繁體中文的逐字稿。" if normalized_lang == "zh" else None,
        )
        if self._has_gpu():
            # GPU：batched 把 VAD 視窗批次餵 GPU，吞吐遠高於逐段序列。
            # segments 仍是 lazy generator、info.duration 仍有值 → 進度/取消照舊運作。
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

        # 壓縮重複幻覺 → 依 word timestamps 重切長段（batched 的 VAD 長段 → 碎片）
        segments_list = _collapse_repeated_segments(segments_list)
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

        Args:
            transcription_segments: Sound Lite 轉錄結果 (帶時間戳)
            diarization_segments: Speaker diarization 結果

        Returns:
            合併後的文字，格式：[Speaker A] 文字內容
        """
        if not diarization_segments:
            # 沒有 diarization 結果，直接返回純文字
            return " ".join(seg.get("text", "") for seg in transcription_segments)

        # 為每個轉錄片段分配說話者
        result_lines = []
        current_speaker = None
        current_text = []

        for trans_seg in transcription_segments:
            trans_start = trans_seg.get("start", 0)
            trans_end = trans_seg.get("end", 0)
            trans_text = trans_seg.get("text", "")

            if not trans_text.strip():
                continue

            # 找到與此轉錄片段重疊最多的說話者
            best_speaker = None
            max_overlap = 0

            for dia_seg in diarization_segments:
                dia_start = dia_seg["start"]
                dia_end = dia_seg["end"]

                # 計算重疊時間
                overlap_start = max(trans_start, dia_start)
                overlap_end = min(trans_end, dia_end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = dia_seg["speaker"]

            # 如果說話者改變，輸出之前的內容
            if best_speaker != current_speaker and current_text:
                speaker_label = f"[{current_speaker}]" if current_speaker else ""
                result_lines.append(f"{speaker_label} {''.join(current_text)}")
                current_text = []

            current_speaker = best_speaker
            current_text.append(trans_text)

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

        用於字幕模式：不改變文字內容，而是在 segments 中添加 speaker 欄位

        Args:
            transcription_segments: Sound Lite 轉錄結果 (帶時間戳)
            diarization_segments: Speaker diarization 結果

        Returns:
            帶 speaker 欄位的 segments 列表
        """
        if not diarization_segments:
            # 沒有 diarization 結果，返回原 segments
            return transcription_segments

        enriched_segments = []

        for trans_seg in transcription_segments:
            trans_start = trans_seg.get("start", 0)
            trans_end = trans_seg.get("end", 0)

            # 找到與此轉錄片段重疊最多的說話者
            best_speaker = None
            max_overlap = 0

            for dia_seg in diarization_segments:
                dia_start = dia_seg["start"]
                dia_end = dia_seg["end"]

                # 計算重疊時間
                overlap_start = max(trans_start, dia_start)
                overlap_end = min(trans_end, dia_end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = dia_seg["speaker"]

            # 複製 segment 並添加 speaker 欄位
            enriched_seg = trans_seg.copy()
            enriched_seg["speaker"] = best_speaker if best_speaker else "UNKNOWN"
            enriched_segments.append(enriched_seg)

        return enriched_segments
