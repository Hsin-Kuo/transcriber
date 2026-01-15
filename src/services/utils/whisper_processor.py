"""
WhisperProcessor - Whisper 轉錄處理器
職責：Whisper 模型的封裝（無狀態工具類）
"""

from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import subprocess
import json
import re
from pydub import AudioSegment
from faster_whisper import WhisperModel
from concurrent.futures import ProcessPoolExecutor, as_completed


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

    print(f"[Worker] 進程啟動，處理 chunk: {chunk_path}", flush=True)

    # 從文件名提取 chunk_idx（例如：_temp_input_chunk_3.wav → 3）
    chunk_idx = int(re.search(r'chunk_(\d+)', chunk_path).group(1))

    print(f"[Worker {chunk_idx}] 載入 Whisper 模型: {model_name}", flush=True)

    # 在進程內獨立創建 Whisper 模型實例
    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=num_workers
    )

    print(f"[Worker {chunk_idx}] 開始轉錄", flush=True)

    # 執行轉錄
    segments_list, info = model.transcribe(
        chunk_path,
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )

    # 收集結果
    segments = []
    text_parts = []
    for segment in segments_list:
        segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text
        })
        text_parts.append(segment.text)

    full_text = " ".join(text_parts)
    detected_language = info.language

    print(f"[Worker {chunk_idx}] 轉錄完成，文字長度: {len(full_text)}", flush=True)

    # 清理臨時文件
    try:
        Path(chunk_path).unlink()
        print(f"[Worker {chunk_idx}] 已刪除臨時文件", flush=True)
    except Exception as e:
        print(f"[Worker {chunk_idx}] 清理臨時文件失敗: {e}", flush=True)

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

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None
    ) -> Tuple[str, List[Dict], str]:
        """轉錄音檔（單次轉錄，不分段）

        Args:
            audio_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）

        Returns:
            (完整文字, segments 列表, 偵測到的語言)
        """
        segments_list, detected_language = self._transcribe_with_timestamps(
            audio_path, language
        )

        # 合併所有 segment 的文字
        full_text = " ".join(seg["text"] for seg in segments_list)

        return full_text, segments_list, detected_language

    def transcribe_in_chunks(
        self,
        audio_path: Path,
        chunk_duration_ms: int = 420000,  # 7 分鐘
        language: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> Tuple[str, List[Dict], str]:
        """將音檔分段後轉錄（提高長音檔的準確度）

        Args:
            audio_path: 音檔路徑
            chunk_duration_ms: 每段長度（毫秒）
            language: 語言代碼（None 表示自動偵測）
            progress_callback: 進度回調函數 callback(chunk_idx, total_chunks)

        Returns:
            (完整文字, segments 列表, 偵測到的語言)
        """
        # 獲取音檔總長度
        total_duration_ms = self._get_audio_duration(audio_path)
        total_minutes = total_duration_ms / 1000 / 60
        print(f"📊 音檔總長度：{total_minutes:.1f} 分鐘")

        # 如果音檔不長，直接轉錄
        if total_duration_ms <= chunk_duration_ms:
            print(f"📝 音檔長度在 {chunk_duration_ms/1000/60:.0f} 分鐘內，直接轉錄...")
            return self.transcribe(audio_path, language)

        # 長音檔：分段處理
        num_chunks = (total_duration_ms + chunk_duration_ms - 1) // chunk_duration_ms
        print(f"🔄 音檔較長，將分為 {num_chunks} 段處理（每段約 {chunk_duration_ms/1000/60:.0f} 分鐘）...")

        # 切分音檔
        chunk_files = self._split_audio_into_chunks(
            audio_path, total_duration_ms, chunk_duration_ms
        )

        # 轉錄每個 chunk
        all_text_parts = []
        all_segments = []
        detected_language = None
        chunk_duration_seconds = chunk_duration_ms / 1000.0

        for chunk_idx, chunk_path in enumerate(chunk_files, start=1):
            print(f"🎙 轉錄第 {chunk_idx}/{num_chunks} 段...")

            # 進度回調
            if progress_callback:
                progress_callback(chunk_idx, num_chunks)

            # 轉錄這個 chunk
            chunk_text, chunk_segments, chunk_lang = self.transcribe(
                chunk_path, language
            )

            all_text_parts.append(chunk_text)

            # 調整時間戳並加入 segments
            time_offset = (chunk_idx - 1) * chunk_duration_seconds
            for seg in chunk_segments:
                adjusted_segment = {
                    "start": seg["start"] + time_offset,
                    "end": seg["end"] + time_offset,
                    "text": seg["text"]
                }
                all_segments.append(adjusted_segment)

            # 記錄偵測到的語言（使用第一段的結果）
            if detected_language is None:
                detected_language = chunk_lang

            # 清理臨時檔案
            try:
                chunk_path.unlink()
            except Exception as e:
                print(f"⚠️ 清理 chunk 檔案失敗：{e}")

        # 合併所有文字
        full_text = " ".join(all_text_parts)

        print(f"✅ 順序轉錄完成！總共 {num_chunks} 段，{len(all_segments)} 個 segments（時間戳已調整）")
        return full_text, all_segments, detected_language

    def transcribe_in_chunks_parallel(
        self,
        audio_path: Path,
        chunk_duration_ms: int = 420000,  # 7 分鐘
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
        print(f"🚀 [並行轉錄] 開始並行轉錄流程（ProcessPoolExecutor）", flush=True)

        # 1. 獲取音檔長度並分割
        total_duration_ms = self._get_audio_duration(audio_path)
        total_minutes = total_duration_ms / 1000 / 60
        print(f"📊 音檔總長度：{total_minutes:.1f} 分鐘", flush=True)

        if total_duration_ms <= chunk_duration_ms:
            print(f"📝 音檔長度在 {chunk_duration_ms/1000/60:.0f} 分鐘內，直接轉錄...", flush=True)
            return self.transcribe(audio_path, language)

        num_chunks = (total_duration_ms + chunk_duration_ms - 1) // chunk_duration_ms
        print(f"🔄 音檔較長，將分為 {num_chunks} 段並行處理...", flush=True)

        chunk_files = self._split_audio_into_chunks(audio_path, total_duration_ms, chunk_duration_ms)

        # 2. 使用 ProcessPoolExecutor 並行轉錄
        results = {}
        completed_count = 0
        executor = None

        print(f"🔧 [並行轉錄] 創建進程池，max_workers={max_workers}", flush=True)

        try:
            executor = ProcessPoolExecutor(max_workers=max_workers)

            # 提交所有任務
            print(f"🔧 [並行轉錄] 準備提交 {num_chunks} 個任務...", flush=True)

            # 準備參數（從當前模型實例獲取配置）
            future_to_idx = {}
            for chunk_path in chunk_files:
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

            print(f"✅ [並行轉錄] 所有任務已提交到進程池", flush=True)

            # 計算初始正在處理中的 chunk 數量（worker 會立即拿走任務）
            processing_count = min(max_workers, num_chunks)
            # 發送初始進度（0 完成，但有 processing_count 個正在處理）
            if progress_callback:
                progress_callback(0, num_chunks, processing_count)

            # 收集結果
            for future in as_completed(future_to_idx.keys()):
                # 檢查取消
                if cancel_check and cancel_check():
                    print(f"⚠️ 用戶取消，終止所有任務", flush=True)
                    # 取消所有未完成的 future
                    for f in future_to_idx.keys():
                        f.cancel()
                    # 強制關閉 executor（不等待）
                    print(f"🛑 強制關閉進程池...", flush=True)
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

                    print(f"✅ Chunk {chunk_idx} 完成（已完成 {completed_count}/{num_chunks}，處理中 {processing_count}）", flush=True)

                    # 更新進度
                    if progress_callback:
                        progress_callback(completed_count, num_chunks, processing_count)

                except Exception as e:
                    chunk_idx = future_to_idx[future]
                    print(f"❌ Chunk {chunk_idx} 轉錄失敗：{e}", flush=True)
                    # 立即失敗：取消所有剩餘任務
                    for f in future_to_idx.keys():
                        f.cancel()
                    # 強制關閉 executor
                    print(f"🛑 轉錄失敗，強制關閉進程池...", flush=True)
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise Exception(f"並行轉錄失敗：{e}")

        except Exception as e:
            # 清理所有剩餘的 chunk 檔案
            for chunk_path in chunk_files:
                try:
                    chunk_path.unlink()
                except:
                    pass
            raise

        finally:
            # 確保 executor 被正確清理
            if executor is not None:
                print(f"🧹 [並行轉錄] 清理進程池...", flush=True)
                try:
                    # 優雅關閉，最多等待 10 秒
                    executor.shutdown(wait=True, cancel_futures=False)
                    print(f"✅ [並行轉錄] 進程池已關閉", flush=True)
                except Exception as cleanup_error:
                    print(f"⚠️ [並行轉錄] 進程池關閉失敗：{cleanup_error}", flush=True)

        # 3. 檢查並合併結果
        if len(results) != num_chunks:
            missing = set(range(1, num_chunks + 1)) - set(results.keys())
            raise Exception(f"並行轉錄不完整，缺少 chunks: {missing}")

        # 按 chunk_idx 排序
        sorted_results = [results[idx] for idx in sorted(results.keys())]

        all_text_parts = [text for text, _, _ in sorted_results]
        all_segments = []

        # 合併 segments 並調整時間戳
        chunk_duration_seconds = chunk_duration_ms / 1000.0
        for chunk_idx, (text, segments, lang) in enumerate(sorted_results, start=1):
            # 計算此 chunk 在原音檔中的時間偏移
            time_offset = (chunk_idx - 1) * chunk_duration_seconds

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

        print(f"✅ 並行轉錄完成！總共 {num_chunks} 段，{len(all_segments)} 個 segments（時間戳已調整）", flush=True)
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

    def _transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: Optional[str] = None
    ) -> Tuple[List[Dict], str]:
        """轉錄音檔並返回帶時間戳的 segments

        Args:
            audio_path: 音檔路徑
            language: 語言代碼（None 表示自動偵測）

        Returns:
            (segments 列表, 偵測到的語言)
        """
        print(f"🎯 [_transcribe_with_timestamps] 開始 Whisper 模型轉錄")
        print(f"🎯 [_transcribe_with_timestamps] 音檔路徑: {audio_path}")
        print(f"🎯 [_transcribe_with_timestamps] 語言: {language}")

        segments_list = []
        print(f"⏳ [_transcribe_with_timestamps] 調用 model.transcribe()...")
        segments, info = self.model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5
        )
        print(f"✅ [_transcribe_with_timestamps] model.transcribe() 完成！")

        # 獲取 Whisper 偵測到的語言
        detected_language = info.language if hasattr(info, 'language') else None

        for segment in segments:
            segments_list.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text
            })

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
            print(f"⚠️ ffprobe 失敗，回退到 pydub: {e}")

        # 回退到 pydub
        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)
        del audio  # 立即釋放記憶體
        return duration_ms

    def _split_audio_into_chunks(
        self,
        audio_path: Path,
        total_duration_ms: int,
        chunk_duration_ms: int
    ) -> List[Path]:
        """將音檔切分為多個 MP3 小段

        使用 ffmpeg 流式處理，避免記憶體問題

        Args:
            audio_path: 原始音檔路徑（MP3）
            total_duration_ms: 音檔總長度（毫秒）
            chunk_duration_ms: 每段長度（毫秒）

        Returns:
            chunk 檔案路徑列表（MP3 格式）
        """
        chunk_files = []
        start_ms = 0
        chunk_idx = 1

        while start_ms < total_duration_ms:
            end_ms = min(start_ms + chunk_duration_ms, total_duration_ms)

            print(f"   準備第 {chunk_idx} 段 ({start_ms/1000/60:.1f}-{end_ms/1000/60:.1f} 分鐘)...")

            # 使用 ffmpeg 直接切分為 MP3，不載入到記憶體
            temp_path = audio_path.parent / f"_temp_{audio_path.stem}_chunk_{chunk_idx}.mp3"
            start_seconds = start_ms / 1000.0
            duration_seconds = (end_ms - start_ms) / 1000.0

            try:
                # 使用 ffmpeg 切分音檔為 MP3（流式處理，不佔用記憶體）
                subprocess.run([
                    'ffmpeg', '-y', '-i', str(audio_path),
                    '-ss', str(start_seconds),
                    '-t', str(duration_seconds),
                    '-acodec', 'libmp3lame',  # MP3 編碼
                    '-b:a', '128k',  # 128kbps
                    '-ar', '16000',  # 16kHz 採樣率（Whisper 推薦）
                    '-ac', '1',  # 單聲道
                    str(temp_path)
                ], check=True, capture_output=True, timeout=60)

            except subprocess.TimeoutExpired:
                print(f"   ⚠️ 切分第 {chunk_idx} 段超時，嘗試使用 pydub")
                # 回退到 pydub（較慢但更穩定）
                audio = AudioSegment.from_file(audio_path)
                chunk_audio = audio[start_ms:end_ms]
                chunk_audio.export(temp_path, format="mp3", bitrate="128k")
                del audio, chunk_audio  # 立即釋放

            except Exception as e:
                print(f"   ⚠️ ffmpeg 切分失敗，回退到 pydub: {e}")
                # 回退到 pydub
                audio = AudioSegment.from_file(audio_path)
                chunk_audio = audio[start_ms:end_ms]
                chunk_audio.export(temp_path, format="mp3", bitrate="128k")
                del audio, chunk_audio  # 立即釋放

            chunk_files.append(temp_path)
            start_ms = end_ms
            chunk_idx += 1

        return chunk_files

    def _merge_transcription_with_diarization(
        self,
        transcription_segments: List[Dict],
        diarization_segments: List[Dict]
    ) -> str:
        """合併轉錄文字和說話者標記

        Args:
            transcription_segments: Whisper 轉錄結果 (帶時間戳)
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
            transcription_segments: Whisper 轉錄結果 (帶時間戳)
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
