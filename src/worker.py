"""
AI Worker — AWS SQS Consumer 入口點

啟動方式：
    DEPLOY_ENV=aws APP_ROLE=worker python -m src.worker

各模組職責：
    worker_core/config.py          — 設定常數（SQS URL、MongoDB、Whisper 模型等）
    worker_core/state.py           — 共享執行時狀態（shutdown flag、Spot 中斷標記）
    worker_core/db.py              — MongoDB 同步連線與 CRUD helpers
    worker_core/model_cache.py     — Whisper / Diarization 模型快取
    worker_core/audio_converter.py — 音檔格式轉換（MP3、WAV）
    worker_core/transcription_job.py — 轉錄主流程（下載 → 轉錄 → 標點 → 儲存）
    worker_core/spot_monitor.py    — Spot 中斷偵測與 EC2 自動關機
    worker_core/sqs_consumer.py    — SQS Long-poll 主迴圈
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.utils.sentry_init import init_sentry
init_sentry(component="worker")

from src.worker_core.sqs_consumer import main

if __name__ == "__main__":
    main()
