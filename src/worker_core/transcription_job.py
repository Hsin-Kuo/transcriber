"""
轉錄任務主流程

從 S3 下載音檔 → 格式轉換 → 平行執行 Whisper 轉錄 + Diarization
→ 繁簡清洗 → 標點處理 → 結果寫入 MongoDB。
"""

import os
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import boto3

from src.utils.storage_service import download_audio
from src.utils.time_utils import get_utc_timestamp
from src.utils.text_utils import convert_segments_punctuation
from src.utils.config_loader import get_temp_dir
from src.services.progress_store import Phase, ProgressStore
from src.worker_core.config import S3_REGION, S3_BUCKET
from src.worker_core.db import get_db, update_task
from src.worker_core.model_cache import get_whisper_processor, get_diarization_pipeline
from src.worker_core.audio_converter import convert_to_mp3, convert_to_wav


# Cancel 信號跨進程靠 DB status：Web Server cancel endpoint 寫 status="canceling/cancelled"，
# Worker 在 segment / punctuation chunk callback 內 poll 並 raise 此 exception 中斷迭代。
class TaskCancelled(Exception):
    pass


_CANCEL_STATUSES = {"canceling", "cancelled"}


def _is_task_cancelled(db, task_id: str) -> bool:
    doc = db.tasks.find_one({"_id": task_id}, {"status": 1})
    return bool(doc and doc.get("status") in _CANCEL_STATUSES)


def _resolve_punct_language(
    language: Optional[str],
    detected_language: Optional[str],
    ui_language: Optional[str],
) -> str:
    """決定標點處理語言：明確指定繁/簡 > zh 時依 UI 語言 > 其他語言"""
    if language in ("zh-TW", "zh-CN"):
        return language
    if detected_language == "zh":
        return "zh-CN" if ui_language == "zh-CN" else "zh-TW"
    return detected_language or language or "zh"


def _run_transcription(
    whisper_processor,
    audio_path: str,
    language: str,
    use_chunking: bool,
    progress_callback=None,
):
    print("🎤 [平行] 開始轉錄...")
    try:
        if use_chunking:
            result = whisper_processor.transcribe_in_chunks(
                audio_path, language=language, progress_callback=progress_callback,
            )
        else:
            result = whisper_processor.transcribe(
                audio_path, language=language, progress_callback=progress_callback,
            )
    except Exception as e:
        if not getattr(e, "error_code", None):
            err = RuntimeError(f"Whisper 轉錄失敗: {e}")
            err.error_code = "TRANSCRIPTION_FAILED"
            raise err from e
        raise
    full_text, segments, detected_language = result
    print(f"✅ [平行] 轉錄完成: {len(full_text) if full_text else 0} 字元")
    return full_text, segments, detected_language


def _run_diarization(diarization_pipeline, wav_path: Path, max_speakers: Optional[int]):
    from src.services.utils.diarization_processor import DiarizationProcessor
    print("🔊 [平行] 開始說話者辨識...")
    processor = DiarizationProcessor(diarization_pipeline)
    segments = processor.perform_diarization(wav_path, max_speakers=max_speakers)
    if segments:
        num_speakers = len(set(s["speaker"] for s in segments))
        print(f"✅ [平行] 說話者辨識完成: {num_speakers} 位說話者")
    else:
        print("⚠️ [平行] 說話者辨識無結果")
    return segments


def process_task(message_body: dict, progress_store: ProgressStore) -> None:
    """處理單個轉錄任務（由 SQS consumer 呼叫）"""
    task_id = message_body["task_id"]
    language = message_body.get("language")
    use_chunking = message_body.get("use_chunking", True)
    use_punctuation = message_body.get("use_punctuation", True)
    punctuation_provider = message_body.get("punctuation_provider", "gemini")
    use_diarization = message_body.get("use_diarization", False)
    max_speakers = message_body.get("max_speakers")

    db = get_db()

    # 防止重複處理（Spot 中斷恢復後可能收到相同 SQS 訊息）
    # 也包含「在 SQS 排隊期間被使用者取消」的情境 — 直接跳過
    task_doc = db.tasks.find_one({"_id": task_id}, {"status": 1})
    if task_doc and task_doc.get("status") in ("completed", *_CANCEL_STATUSES):
        print(f"⏭️ [Worker] 任務 {task_id} 狀態 {task_doc.get('status')}，跳過處理")
        progress_store.clear(task_id)
        return

    print(f"🎬 [Worker] 開始處理任務 {task_id}")
    update_task(db, task_id, {"status": "processing"})
    progress_store.set_phase(
        task_id, Phase.PREPARATION, 0.0, message="Worker 開始處理..."
    )

    task_doc = db.tasks.find_one({"_id": task_id})
    user_tier = task_doc.get("user", {}).get("tier", "free") if task_doc else "free"
    ui_language = task_doc.get("config", {}).get("ui_language") if task_doc else None

    temp_dir = get_temp_dir()

    try:
        # 1. 下載音檔（副檔名 .original 不預設格式）
        progress_store.set_phase(task_id, Phase.PREPARATION, 0.2, message="正在下載音檔...")
        audio_path = temp_dir / f"{task_id}.original"
        download_audio(task_id, audio_path, tier=user_tier)
        print(f"📥 已下載音檔: {audio_path} ({audio_path.stat().st_size / 1024 / 1024:.2f} MB)")

        # 2. 統一轉為 MP3
        progress_store.set_phase(task_id, Phase.PREPARATION, 0.5, message="正在轉換音檔格式...")
        audio_path, transcoded = convert_to_mp3(audio_path)
        if transcoded:
            progress_store.set_phase(
                task_id, Phase.PREPARATION, 0.7, message="正在上傳轉碼後的音檔..."
            )
            s3_key = f"uploads/{user_tier}/{task_id}.mp3"
            boto3.client("s3", region_name=S3_REGION).upload_file(
                str(audio_path), S3_BUCKET, s3_key
            )
            print(f"☁️ 已上傳轉碼後的音檔到 S3: {s3_key}")

        # 3. 取得模型（快取，只在首次任務載入）
        progress_store.set_phase(task_id, Phase.PREPARATION, 1.0, message="正在準備模型...")
        from src.services.utils.punctuation_processor import PunctuationProcessor

        whisper_processor = get_whisper_processor()
        diarization_pipeline = get_diarization_pipeline() if use_diarization else None

        # 4. 平行執行轉錄 + 說話者辨識
        full_text = segments = detected_language = diarization_segments = None

        # 進度回報 callback：whisper 每完成一個 segment 就推進 TRANSCRIPTION phase。
        # 順便檢查使用者是否已取消 — 是的話 raise 中斷 segment 迭代。
        # phase_progress 上限 0.99 留給後續的合併/收尾步驟。
        def _on_transcription_segment(elapsed_s, total_s, _tid=task_id, _db=db):
            if _is_task_cancelled(_db, _tid):
                raise TaskCancelled(f"task {_tid} cancelled during transcription")
            if total_s <= 0:
                return
            pp = min(0.99, elapsed_s / total_s)
            progress_store.set_phase(
                _tid,
                Phase.TRANSCRIPTION,
                pp,
                message=f"轉錄中（{int(elapsed_s)}s / {int(total_s)}s）...",
            )

        if use_diarization and diarization_pipeline:
            progress_store.set_phase(
                task_id,
                Phase.TRANSCRIPTION,
                0.0,
                message="正在轉錄音檔與說話者辨識（平行處理）...",
                details={"diarization_started": True},
            )
            wav_path = convert_to_wav(audio_path, temp_dir / f"{task_id}.wav")

            with ThreadPoolExecutor(max_workers=2) as executor:
                transcription_future = executor.submit(
                    _run_transcription,
                    whisper_processor,
                    str(audio_path),
                    language,
                    use_chunking,
                    _on_transcription_segment,
                )
                diarization_future = executor.submit(
                    _run_diarization, diarization_pipeline, wav_path, max_speakers
                )
                # 等待兩個任務都結束（不在此處理異常，避免提前中斷）
                for future in as_completed([transcription_future, diarization_future]):
                    pass

            # 轉錄失敗 → 整個任務失敗（無可用結果）
            full_text, segments, detected_language = transcription_future.result()

            # Diarization 失敗 → 降級為純轉錄（與本地模式行為一致）
            try:
                diarization_segments = diarization_future.result()
            except Exception as e:
                print(f"⚠️ 說話者辨識失敗，使用純轉錄結果: {e}")
                diarization_segments = None
                progress_store.set_phase(
                    task_id,
                    Phase.TRANSCRIPTION,
                    1.0,
                    message="語者辨識失敗，使用純轉錄結果",
                    details={"diarization_failed": True},
                )

            if diarization_segments and segments:
                task = db.tasks.find_one({"_id": task_id})
                task_type = task.get("task_type", "paragraph") if task else "paragraph"
                num_speakers = len(set(s["speaker"] for s in diarization_segments))

                if task_type == "subtitle":
                    segments = whisper_processor._merge_speaker_to_segments(
                        segments, diarization_segments
                    )
                else:
                    full_text = whisper_processor._merge_transcription_with_diarization(
                        segments, diarization_segments
                    )

                # 寫入永久 stat（保留 update_task 路徑）
                update_task(db, task_id, {"stats.diarization.num_speakers": num_speakers})
                progress_store.set_phase(
                    task_id,
                    Phase.TRANSCRIPTION,
                    1.0,
                    message="語者辨識完成",
                    details={"diarization_completed": True, "num_speakers": num_speakers},
                )
        else:
            progress_store.set_phase(
                task_id, Phase.TRANSCRIPTION, 0.0, message="正在轉錄音檔..."
            )
            try:
                if use_chunking:
                    full_text, segments, detected_language = whisper_processor.transcribe_in_chunks(
                        str(audio_path), language=language,
                        progress_callback=_on_transcription_segment,
                    )
                else:
                    full_text, segments, detected_language = whisper_processor.transcribe(
                        str(audio_path), language=language,
                        progress_callback=_on_transcription_segment,
                    )
            except Exception as e:
                if not getattr(e, "error_code", None):
                    err = RuntimeError(f"Whisper 轉錄失敗: {e}")
                    err.error_code = "TRANSCRIPTION_FAILED"
                    raise err from e
                raise
            print(f"✅ 轉錄完成: {len(full_text) if full_text else 0} 字元, 語言: {detected_language}")

        if full_text is None:
            raise ValueError("轉錄結果為空")

        # 5. 中文繁簡清洗
        punct_language = _resolve_punct_language(language, detected_language, ui_language)
        if punct_language in ("zh-TW", "zh-CN"):
            from src.services.utils.whisper_processor import _convert_chinese_script
            full_text = _convert_chinese_script(full_text, punct_language)
            segments = [
                {**seg, "text": _convert_chinese_script(seg["text"], punct_language)}
                for seg in segments
            ]

        # 6. 標點處理
        punctuation_model = punctuation_token_usage = None
        if use_punctuation:
            progress_store.set_phase(
                task_id, Phase.PUNCTUATION, 0.0, message="正在添加標點符號...",
                details={"punctuation_started": True},
            )

            def _on_punctuation_chunk(i, n, _tid=task_id, _db=db):
                if _is_task_cancelled(_db, _tid):
                    raise TaskCancelled(f"task {_tid} cancelled during punctuation")
                if n <= 0:
                    return
                pp = min(0.99, i / n)
                progress_store.set_phase(
                    _tid,
                    Phase.PUNCTUATION,
                    pp,
                    message=f"添加標點（{i}/{n} 段）...",
                    details={"punctuation_current_chunk": i, "punctuation_total_chunks": n},
                )

            try:
                punctuation_processor = PunctuationProcessor()
                punctuated_text, punctuation_model, punctuation_token_usage = punctuation_processor.process(
                    full_text, provider=punctuation_provider, language=punct_language,
                    progress_callback=_on_punctuation_chunk,
                )
                full_text = punctuated_text
                progress_store.set_phase(
                    task_id, Phase.PUNCTUATION, 0.99, message="標點處理完成",
                    details={"punctuation_completed": True, "punctuation_model": punctuation_model},
                )
            except Exception as e:
                print(f"⚠️ 標點處理失敗: {e}")
                progress_store.set_phase(
                    task_id, Phase.PUNCTUATION, 0.99, message="標點處理失敗，使用原始文字",
                    details={"punctuation_failed": True, "punctuation_error": str(e)[:200]},
                )

        # 7. Segment 標點轉換
        converted_segments = convert_segments_punctuation(segments)

        # 8. 儲存到 MongoDB
        progress_store.set_phase(
            task_id, Phase.PUNCTUATION, 1.0, message="正在保存結果..."
        )
        now = get_utc_timestamp()
        db.transcriptions.replace_one(
            {"_id": task_id},
            {"_id": task_id, "content": full_text, "text_length": len(full_text),
             "created_at": now, "updated_at": now},
            upsert=True,
        )
        if converted_segments:
            db.segments.replace_one(
                {"_id": task_id},
                {"_id": task_id, "segments": converted_segments,
                 "segment_count": len(converted_segments), "created_at": now, "updated_at": now},
                upsert=True,
            )

        # 9. 更新音檔路徑
        update_task(db, task_id, {
            "result.audio_file": f"s3://{S3_BUCKET}/uploads/{user_tier}/{task_id}.mp3",
            "result.audio_filename": f"{task_id}.mp3",
        })

        # 10. 標記完成
        complete_updates = {
            "status": "completed",
            "result.text_length": len(full_text),
            "result.word_count": len(full_text.split()),
            "config.language": detected_language or language,
            "timestamps.completed_at": get_utc_timestamp(),
        }
        if punctuation_model:
            complete_updates["models.punctuation"] = punctuation_model
        if punctuation_token_usage:
            complete_updates["stats.token_usage"] = {
                "total": punctuation_token_usage.get("total", 0),
                "prompt": punctuation_token_usage.get("prompt", 0),
                "completion": punctuation_token_usage.get("completion", 0),
                "model": punctuation_model or "unknown",
            }
        # 順便 unset error：如果 Web Server cleanup_orphaned_tasks 在 Worker
        # 跑到一半時誤標 SERVER_RESTART error，這裡完成後要把那個殘留清掉。
        update_task(db, task_id, complete_updates, unset_fields=["error"])
        progress_store.clear(task_id)
        print(f"✅ [Worker] 任務 {task_id} 完成！({len(full_text)} 字元)")

        # 扣除配額（兩步式：先刪預扣、再套用 pipeline）
        #
        # 設計決定：刻意不用 transaction 包覆這兩步，以節省每次扣款多一個 commit round-trip。
        # 風險：若 step 2 失敗（極罕見的網路/DB 故障），預扣已刪、扣款未套用，會漏算一次。
        # 監控：若觀察到下方 [QUOTA_LEAK] 標記出現，代表發生此 race，應視頻率決定是否補回 transaction。
        from bson import ObjectId
        from src.database.repositories.reservation_repo import consume_reservation_sync
        from src.auth.quota import build_transcription_consumption_pipeline

        user_id = task_doc.get("user", {}).get("user_id") if task_doc else None
        audio_duration_seconds = (task_doc.get("stats") or {}).get("audio_duration_seconds", 0) if task_doc else 0
        if user_id and audio_duration_seconds > 0:
            # Step 1：原子刪除預扣
            try:
                reservation = consume_reservation_sync(db, task_id)
            except Exception as e:
                print(f"⚠️ [Worker] 刪除預扣失敗（沒影響資料，會留下殘留預扣）：task={task_id} err={e}")
                reservation = None

            if reservation is None:
                print(f"ℹ️  [Worker] 任務 {task_id} 無預扣記錄，跳過配額扣除")
            else:
                # Step 2：套用 pipeline 原子扣款
                try:
                    duration_minutes = audio_duration_seconds / 60
                    pipeline = build_transcription_consumption_pipeline(
                        duration_minutes=duration_minutes,
                        now_ts=get_utc_timestamp(),
                    )
                    db.users.update_one({"_id": ObjectId(user_id)}, pipeline)
                    print(f"✅ [Worker] 已扣除配額：用戶 {user_id}，時長 {audio_duration_seconds:.2f} 秒")
                except Exception as e:
                    # ⚠️ QUOTA_LEAK：預扣已刪、扣款未套用 = 漏算一次
                    # 監控訊號：grep [QUOTA_LEAK] 出現次數，超過閾值告警
                    print(
                        f"⚠️ [QUOTA_LEAK] [Worker] 扣款失敗（漏算一次）："
                        f"user_id={user_id} task_id={task_id} "
                        f"duration_minutes={duration_minutes:.2f} "
                        f"reservation_minutes={reservation.get('duration_minutes')} "
                        f"err={e}"
                    )

    except TaskCancelled as e:
        # 使用者已經透過 Web Server cancel endpoint 把 DB status 設為 cancelled，
        # Web Server 也已釋放預扣。Worker 這邊：
        # - 不要再 update_task 寫 status（會覆蓋 cancelled）
        # - 清掉 progress_store snapshot 讓 SSE 立刻收尾
        # - reservation release 是 idempotent，保險再呼叫一次
        # - 正常 return（讓 sqs_consumer 把訊息刪掉，不重發）
        print(f"🛑 [Worker] 任務 {task_id} 被使用者取消，中止處理: {e}")
        progress_store.clear(task_id)
        try:
            from src.database.repositories.reservation_repo import release_reservation_sync
            release_reservation_sync(db, task_id)
        except Exception as release_err:
            print(f"⚠️ [Worker] 釋放預扣失敗（cancel path）：{release_err}")

    except Exception as e:
        print(f"❌ [Worker] 任務 {task_id} 失敗: {e}")
        import traceback
        traceback.print_exc()
        error_code = getattr(e, "error_code", None) or "SYSTEM_ERROR"
        update_task(db, task_id, {
            "status": "failed",
            "error": {"code": error_code, "message": str(e)},
        })
        progress_store.clear(task_id)

        # 釋放預扣（任務失敗）
        try:
            from src.database.repositories.reservation_repo import release_reservation_sync
            released = release_reservation_sync(db, task_id)
            if released:
                print(f"♻️  [Worker] 已釋放任務 {task_id} 的預扣配額")
        except Exception as release_err:
            print(f"⚠️ [Worker] 釋放預扣失敗：{release_err}")
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
