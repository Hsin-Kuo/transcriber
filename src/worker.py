"""
AI Worker — AWS SQS Consumer

職責：
- 從 SQS 接收轉錄任務
- 從 S3 下載音檔
- 執行 Whisper 轉錄 + 標點處理 + 說話者辨識（轉錄與語者辨識平行處理）
- 結果寫回 MongoDB
- 更新任務進度（Web Server 透過 SSE 輪詢 MongoDB 推送給前端）

啟動方式：
    DEPLOY_ENV=aws APP_ROLE=worker python -m src.worker
"""

import os
import sys
import json
import time
import signal
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 確保能 import src 模組
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import boto3
from pymongo import MongoClient

from src.utils.storage_service import download_audio, save_audio
from src.utils.time_utils import get_utc_timestamp
from src.utils.config_loader import get_parameter


# ===== 設定 =====
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")
S3_REGION = os.getenv("S3_REGION", "ap-northeast-1")
# AWS 從 SSM 讀取，本地從環境變數
MONGODB_URL = get_parameter("/transcriber/mongodb-url", fallback_env="MONGODB_URL", default="mongodb://localhost:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "whisper_transcriber")
DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "medium")
WORKER_SECRET = get_parameter("/transcriber/worker-secret", fallback_env="WORKER_SECRET", default="")
AUTO_SHUTDOWN_IDLE_MINUTES = int(os.getenv("AUTO_SHUTDOWN_IDLE_MINUTES", "5"))

# 從 SSM 載入 API keys 並設定到環境變數（讓 PunctuationProcessor 可以讀取）
_google_api_key_1 = get_parameter("/transcriber/google-api-key-1", fallback_env="GOOGLE_API_KEY_1", default="")
_google_api_key_2 = get_parameter("/transcriber/google-api-key-2", fallback_env="GOOGLE_API_KEY_2", default="")
if _google_api_key_1:
    os.environ["GOOGLE_API_KEY_1"] = _google_api_key_1
if _google_api_key_2:
    os.environ["GOOGLE_API_KEY_2"] = _google_api_key_2

# Graceful shutdown
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    print(f"\n🛑 收到停止訊號 ({signum})，等待當前任務完成後退出...")
    _shutdown = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _verify_message_signature(body: dict) -> bool:
    """驗證 SQS 訊息簽名

    Args:
        body: 解析後的訊息內容

    Returns:
        True 如果簽名有效或未啟用簽名驗證，False 如果簽名無效
    """
    if not WORKER_SECRET:
        # 未設定密鑰時跳過驗證（向後相容，但會印警告）
        return True

    import hmac
    import hashlib

    signature = body.pop("_signature", None)
    if not signature:
        print("⚠️ SQS 訊息缺少簽名，可能來源不明")
        return False

    # 計算預期簽名
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(
        WORKER_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        print("⚠️ SQS 訊息簽名無效，拒絕處理")
        return False

    return True


# ===== MongoDB 同步 helpers =====

def _get_db():
    client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
    return client[MONGODB_DB_NAME]


def _update_task(db, task_id: str, updates: dict):
    updates["updated_at"] = get_utc_timestamp()
    db.tasks.update_one({"_id": task_id}, {"$set": updates})


def _update_progress(db, task_id: str, progress: str, extra: dict = None):
    updates = {"progress": progress}
    if extra:
        updates.update(extra)
    _update_task(db, task_id, updates)


# ===== 模型快取 =====
_cached_whisper_processor = None
_cached_diarization_pipeline = None


def _get_whisper_processor():
    """取得快取的 WhisperProcessor（首次呼叫時載入模型）"""
    global _cached_whisper_processor
    if _cached_whisper_processor is None:
        from faster_whisper import WhisperModel
        from src.services.utils.whisper_processor import WhisperProcessor

        print(f"🔄 [Worker] 載入 Whisper 模型: {DEFAULT_MODEL} (float16)...")
        whisper_model = WhisperModel(
            DEFAULT_MODEL,
            device="auto",
            compute_type="float16",
        )
        _cached_whisper_processor = WhisperProcessor(whisper_model, DEFAULT_MODEL)
        print(f"✅ [Worker] 模型載入完成")
    return _cached_whisper_processor


def _get_diarization_pipeline():
    """取得快取的 Diarization Pipeline（首次呼叫時載入模型）"""
    global _cached_diarization_pipeline
    if _cached_diarization_pipeline is None:
        from src.services.utils.diarization_processor import DiarizationProcessor
        hf_token = get_parameter("/transcriber/hf-token", fallback_env="HF_TOKEN", default="")
        if hf_token:
            print(f"🔄 [Worker] 載入 Diarization 模型...")
            _cached_diarization_pipeline = DiarizationProcessor.load_pipeline(hf_token)
            if _cached_diarization_pipeline:
                print(f"✅ [Worker] Diarization 模型載入完成")
            else:
                print(f"⚠️ [Worker] Diarization 模型載入失敗")
        else:
            print(f"⚠️ [Worker] 未設定 HF_TOKEN，Diarization 不可用")
    return _cached_diarization_pipeline


def _convert_to_wav(audio_path: Path, wav_path: Path) -> Path:
    """將音檔轉換為 WAV 格式（pyannote 需要）"""
    try:
        subprocess.run([
            'ffmpeg', '-y', '-i', str(audio_path),
            '-ar', '16000', '-ac', '1', str(wav_path)
        ], check=True, capture_output=True)
        print(f"🔄 已轉換為 WAV: {wav_path}")
        return wav_path
    except Exception as e:
        print(f"⚠️ WAV 轉換失敗: {e}，使用原始音檔")
        return audio_path


def _run_transcription(whisper_processor, audio_path: str, language: str, use_chunking: bool):
    """執行 Whisper 轉錄（用於平行處理）"""
    print(f"🎤 [平行] 開始轉錄...")
    if use_chunking:
        full_text, segments, detected_language = whisper_processor.transcribe_in_chunks(
            audio_path, language=language
        )
    else:
        full_text, segments, detected_language = whisper_processor.transcribe(
            audio_path, language=language
        )
    print(f"✅ [平行] 轉錄完成: {len(full_text) if full_text else 0} 字元")
    return full_text, segments, detected_language


def _run_diarization(diarization_pipeline, wav_path: Path, max_speakers: int):
    """執行說話者辨識（用於平行處理）"""
    from src.services.utils.diarization_processor import DiarizationProcessor
    print(f"🔊 [平行] 開始說話者辨識...")
    diarization_processor = DiarizationProcessor(diarization_pipeline)
    diarization_segments = diarization_processor.perform_diarization(
        wav_path, max_speakers=max_speakers
    )
    if diarization_segments:
        num_speakers = len(set(s['speaker'] for s in diarization_segments))
        print(f"✅ [平行] 說話者辨識完成: {num_speakers} 位說話者")
    else:
        print(f"⚠️ [平行] 說話者辨識無結果")
    return diarization_segments


# ===== 主流程 =====

def process_task(message_body: dict):
    """處理單個轉錄任務"""
    task_id = message_body["task_id"]
    language = message_body.get("language")
    use_chunking = message_body.get("use_chunking", True)
    use_punctuation = message_body.get("use_punctuation", True)
    punctuation_provider = message_body.get("punctuation_provider", "gemini")
    use_diarization = message_body.get("use_diarization", False)
    max_speakers = message_body.get("max_speakers")

    db = _get_db()

    print(f"🎬 [Worker] 開始處理任務 {task_id}")
    _update_task(db, task_id, {"status": "processing", "progress": "Worker 開始處理..."})

    temp_dir = Path(tempfile.mkdtemp())

    try:
        # 1. 從 S3 下載音檔
        _update_progress(db, task_id, "正在下載音檔...")
        audio_path = temp_dir / f"{task_id}.mp3"
        download_audio(task_id, audio_path)
        print(f"📥 已下載音檔: {audio_path} ({audio_path.stat().st_size / 1024 / 1024:.2f} MB)")

        # 2. 取得模型（快取，只在首次任務載入）
        _update_progress(db, task_id, "正在準備模型...")
        from src.services.utils.punctuation_processor import PunctuationProcessor

        whisper_processor = _get_whisper_processor()
        diarization_pipeline = _get_diarization_pipeline() if use_diarization else None

        # 3. 平行執行轉錄和說話者辨識
        full_text = None
        segments = None
        detected_language = None
        diarization_segments = None

        if use_diarization and diarization_pipeline:
            # ===== 平行處理模式 =====
            _update_progress(db, task_id, "正在轉錄音檔與說話者辨識（平行處理）...")
            print(f"🚀 [平行模式] 同時執行轉錄與說話者辨識")

            # 先轉換 WAV（這步很快，不需要平行）
            wav_path = _convert_to_wav(audio_path, temp_dir / f"{task_id}.wav")

            # 使用 ThreadPoolExecutor 平行執行
            with ThreadPoolExecutor(max_workers=2) as executor:
                # 提交兩個任務
                transcription_future = executor.submit(
                    _run_transcription,
                    whisper_processor, str(audio_path), language, use_chunking
                )
                diarization_future = executor.submit(
                    _run_diarization,
                    diarization_pipeline, wav_path, max_speakers
                )

                # 等待所有任務完成
                for future in as_completed([transcription_future, diarization_future]):
                    try:
                        future.result()  # 觸發異常（如果有）
                    except Exception as e:
                        print(f"⚠️ [平行] 任務異常: {e}")

                # 取得結果
                full_text, segments, detected_language = transcription_future.result()
                diarization_segments = diarization_future.result()

            print(f"✅ [平行模式] 兩個任務都已完成")

            # 合併說話者資訊
            if diarization_segments and segments:
                task = db.tasks.find_one({"_id": task_id})
                task_type = task.get("task_type", "paragraph") if task else "paragraph"
                num_speakers = len(set(s['speaker'] for s in diarization_segments))

                if task_type == "subtitle":
                    segments = whisper_processor._merge_speaker_to_segments(
                        segments, diarization_segments
                    )
                else:
                    full_text = whisper_processor._merge_transcription_with_diarization(
                        segments, diarization_segments
                    )

                _update_progress(db, task_id, "語者辨識完成", {
                    "stats.diarization.num_speakers": num_speakers
                })
        else:
            # ===== 僅轉錄模式 =====
            _update_progress(db, task_id, "正在轉錄音檔...")
            if use_chunking:
                full_text, segments, detected_language = whisper_processor.transcribe_in_chunks(
                    str(audio_path), language=language
                )
            else:
                full_text, segments, detected_language = whisper_processor.transcribe(
                    str(audio_path), language=language
                )
            print(f"✅ 轉錄完成: {len(full_text) if full_text else 0} 字元, 語言: {detected_language}")

        if full_text is None:
            raise ValueError("轉錄結果為空")

        # 5. 標點處理（可選）
        punctuation_model = None
        punctuation_token_usage = None
        if use_punctuation:
            _update_progress(db, task_id, "正在添加標點符號...")
            try:
                punctuation_processor = PunctuationProcessor()
                punctuated_text, punctuation_model, punctuation_token_usage = punctuation_processor.process(
                    full_text,
                    provider=punctuation_provider,
                    language=detected_language or language or "zh",
                )
                full_text = punctuated_text
                _update_progress(db, task_id, "標點處理完成")
            except Exception as e:
                print(f"⚠️ 標點處理失敗: {e}")
                _update_progress(db, task_id, f"標點處理失敗，使用原始文字")

        # 6. 轉換 segments 標點
        from src.utils.text_utils import convert_segments_punctuation
        converted_segments = convert_segments_punctuation(segments)

        # 7. 保存結果到 MongoDB
        _update_progress(db, task_id, "正在保存結果...")
        now = get_utc_timestamp()

        db.transcriptions.replace_one(
            {"_id": task_id},
            {
                "_id": task_id,
                "content": full_text,
                "text_length": len(full_text),
                "created_at": now,
                "updated_at": now,
            },
            upsert=True,
        )

        if converted_segments:
            db.segments.replace_one(
                {"_id": task_id},
                {
                    "_id": task_id,
                    "segments": converted_segments,
                    "segment_count": len(converted_segments),
                    "created_at": now,
                    "updated_at": now,
                },
                upsert=True,
            )

        # 8. 保存音檔到永久位置（已在 S3 上，更新 DB 路徑）
        _update_task(db, task_id, {
            "result.audio_file": f"s3://{os.getenv('S3_BUCKET')}/uploads/{task_id}.mp3",
            "result.audio_filename": f"{task_id}.mp3",
        })

        # 9. 標記完成
        text_length = len(full_text)
        word_count = len(full_text.split())

        complete_updates = {
            "status": "completed",
            "progress": "轉錄完成",
            "result.text_length": text_length,
            "result.word_count": word_count,
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

        _update_task(db, task_id, complete_updates)
        print(f"✅ [Worker] 任務 {task_id} 完成！({text_length} 字元)")

    except Exception as e:
        print(f"❌ [Worker] 任務 {task_id} 失敗: {e}")
        import traceback
        traceback.print_exc()
        _update_task(db, task_id, {
            "status": "failed",
            "error": {"message": str(e)},
            "progress": f"處理失敗: {str(e)[:200]}",
        })
    finally:
        # 清理臨時目錄
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def _shutdown_instance():
    """關閉當前 EC2 實例"""
    try:
        # 獲取當前實例 ID
        import urllib.request
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT"
        )
        token = urllib.request.urlopen(token_req, timeout=2).read().decode()

        instance_req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token}
        )
        instance_id = urllib.request.urlopen(instance_req, timeout=2).read().decode()

        print(f"🔌 正在關閉實例 {instance_id}...")
        ec2 = boto3.client("ec2", region_name=S3_REGION)
        ec2.stop_instances(InstanceIds=[instance_id])
        print(f"✅ 已發送關機指令")
    except Exception as e:
        print(f"⚠️ 無法自動關機: {e}")


def main():
    """SQS Consumer 主迴圈"""
    if not SQS_QUEUE_URL:
        print("❌ SQS_QUEUE_URL 未設定，無法啟動 Worker")
        sys.exit(1)

    sqs = boto3.client("sqs", region_name=S3_REGION)
    print(f"🚀 AI Worker 已啟動")
    print(f"   SQS Queue: {SQS_QUEUE_URL}")
    print(f"   Whisper Model: {DEFAULT_MODEL}")
    print(f"   MongoDB: {MONGODB_DB_NAME}")
    print(f"   Auto Shutdown: {AUTO_SHUTDOWN_IDLE_MINUTES} 分鐘空閒後")
    print(f"   平行處理: 轉錄 + 語者辨識同時執行")

    # 預先載入模型，不用等第一個任務才載入
    _get_whisper_processor()
    _get_diarization_pipeline()  # 預先載入 diarization（如果有 HF_TOKEN）

    idle_start = None  # 空閒開始時間
    idle_threshold = AUTO_SHUTDOWN_IDLE_MINUTES * 60  # 轉為秒

    while not _shutdown:
        try:
            # Long polling（最多等待 20 秒）
            resp = sqs.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=600,  # 10 分鐘處理時間
            )

            messages = resp.get("Messages", [])
            if not messages:
                # 沒有訊息，開始計算空閒時間
                if idle_start is None:
                    idle_start = time.time()
                    print(f"⏳ 佇列空閒，{AUTO_SHUTDOWN_IDLE_MINUTES} 分鐘後自動關機...")

                idle_duration = time.time() - idle_start
                if idle_duration >= idle_threshold:
                    print(f"💤 空閒超過 {AUTO_SHUTDOWN_IDLE_MINUTES} 分鐘，準備關機...")
                    _shutdown_instance()
                    break
                continue

            # 有訊息，重置空閒計時
            idle_start = None

            for msg in messages:
                body = json.loads(msg["Body"])
                receipt_handle = msg["ReceiptHandle"]

                # 驗證訊息簽名（如果有設定 WORKER_SECRET）
                if not _verify_message_signature(body):
                    # 簽名無效，刪除訊息但不處理
                    sqs.delete_message(
                        QueueUrl=SQS_QUEUE_URL,
                        ReceiptHandle=receipt_handle,
                    )
                    print(f"🚫 已丟棄無效簽名的訊息: {body.get('task_id', 'unknown')}")
                    continue

                process_task(body)

                # 處理成功，刪除訊息
                sqs.delete_message(
                    QueueUrl=SQS_QUEUE_URL,
                    ReceiptHandle=receipt_handle,
                )
                print(f"📨 已確認 SQS 訊息: {body.get('task_id')}")

        except Exception as e:
            print(f"❌ [Worker] SQS polling 錯誤: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

    print("👋 Worker 已停止")


if __name__ == "__main__":
    main()
