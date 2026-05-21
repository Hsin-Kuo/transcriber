"""
Sound Lite 轉錄服務 - 新應用入口
採用清晰的三層架構設計
"""

import os
import asyncio
import signal
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 結構化 logging 需要早 init，讓後續 import 的模組 print/logging 也走同一管道
from src.utils.logger import setup_logging, RequestIdMiddleware, get_logger
setup_logging()
logger = get_logger(__name__)

# Sentry 必須在其他模組 import 之前初始化才能完整 hook 例外
from src.utils.sentry_init import init_sentry
init_sentry(component="server")

# 資料庫和 Repositories
from src.database.mongodb import MongoDB
from src.database.repositories.task_repo import TaskRepository
from src.database.repositories.tag_repo import TagRepository
from src.database.repositories.audit_log_repo import AuditLogRepository

# Routers
from src.routers import auth as auth_router
from src.routers import oauth as oauth_router
from src.routers import tasks as tasks_router
from src.routers import transcriptions as transcriptions_router
from src.routers import tags as tags_router
from src.routers import audio as audio_router
from src.routers import summaries as summaries_router
from src.routers import admin as admin_router
from src.routers import uploads as uploads_router
from src.routers import shared as shared_router
from src.routers import subscriptions as subscriptions_router

# Services
from src.services.utils.diarization_processor import DiarizationProcessor

# Utils
from src.utils.audit_logger import init_audit_logger

# 共享狀態
from src.utils.shared_state import store as task_state_store
from src.utils.sentry_helpers import create_background_task
from src.services.progress_store import InMemoryProgressStore, MongoProgressStore

# 部署環境設定
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")
APP_ROLE = os.getenv("APP_ROLE", "server")

# 設定
DEFAULT_MODEL = "medium"
# OUTPUT_DIR 已移除 - 文字檔和 segments 現在存儲在 MongoDB 中

# 時區設定 (UTC+8 台北時間)
TZ_UTC8 = timezone(timedelta(hours=8))

# 全域服務實例
whisper_model = None
current_model_name = None
diarization_pipeline = None
task_repo = None
tag_repo = None
audit_log_repo = None
main_loop = None
executor = ThreadPoolExecutor(max_workers=2)  # 降低並發數避免記憶體爆炸

# 是否需要載入 ML 模型（本地開發一律載入；AWS 僅 worker 載入）
SHOULD_LOAD_MODELS = (DEPLOY_ENV == "local") or (APP_ROLE == "worker")

# 檢查 Diarization 是否可用
DIARIZATION_AVAILABLE = False
if SHOULD_LOAD_MODELS:
    try:
        from pyannote.audio import Pipeline
        DIARIZATION_AVAILABLE = True
    except ImportError:
        logger.warning("app.diarization.unavailable")
else:
    logger.info("app.models.load_skipped", deploy_env=DEPLOY_ENV, app_role=APP_ROLE)


# ========== 創建 FastAPI 應用 ==========

app = FastAPI(
    title="Sound Lite 轉錄服務",
    description="基於三層架構的音檔轉錄服務",
    version="3.0.0"
)

# Request ID middleware：注入 request_id 到所有 log + Sentry tag
app.add_middleware(RequestIdMiddleware)

# CORS 中間件
cors_origins_str = os.getenv("CORS_ORIGINS", "")

# 安全的 CORS 配置
if cors_origins_str and cors_origins_str != "*":
    # 生產環境：明確指定允許的來源
    cors_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]
    allow_credentials = True
else:
    # 開發環境：允許常見的本地開發來源，但不允許 credentials
    # 注意：CORS_ORIGINS="*" + allow_credentials=True 違反 CORS 規範
    if DEPLOY_ENV == "local":
        cors_origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
        allow_credentials = True
        logger.warning("app.cors.dev_mode", origins=cors_origins)
    else:
        # AWS 生產環境必須設定 CORS_ORIGINS
        raise RuntimeError(
            "生產環境必須設定 CORS_ORIGINS 環境變數。\n"
            "例如：CORS_ORIGINS=https://app.example.com,https://admin.example.com"
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    expose_headers=["Content-Type", "Content-Disposition"],
    max_age=3600,
)

# ========== 註冊所有路由 ==========

app.include_router(auth_router.router)
app.include_router(oauth_router.router)
app.include_router(tasks_router.router)
app.include_router(transcriptions_router.router)
app.include_router(tags_router.router)
app.include_router(audio_router.router)
app.include_router(summaries_router.router)
app.include_router(admin_router.router)
app.include_router(uploads_router.router)
app.include_router(shared_router.router)
app.include_router(subscriptions_router.router)


# ========== 進程清理工具函數 ==========

def cleanup_worker_processes():
    """清理所有 ProcessPoolExecutor worker 進程"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "multiprocessing.spawn"],
            capture_output=True,
            text=True
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            logger.info("app.worker_processes.cleanup", count=len(pids))
            subprocess.run(["pkill", "-9", "-f", "multiprocessing.spawn"], check=False)
            subprocess.run(["pkill", "-9", "-f", "multiprocessing.resource_tracker"], check=False)
            return len(pids)
        return 0
    except Exception as e:
        logger.warning("app.worker_processes.cleanup_failed", error=str(e))
        return 0


def signal_handler(signum, frame):
    """處理終止信號，確保清理所有資源"""
    logger.info("app.signal.received", signal=signal.Signals(signum).name)
    cleanup_worker_processes()
    logger.info("app.signal.cleanup_done")
    exit(0)


# 註冊信號處理器
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ========== 啟動與關閉事件 ==========

@app.on_event("startup")
async def startup_event():
    """應用啟動時的初始化"""
    global whisper_model, current_model_name, task_repo, tag_repo, audit_log_repo, main_loop, diarization_pipeline

    logger.info("app.startup.began", version="3.0.0", deploy_env=DEPLOY_ENV, app_role=APP_ROLE)

    # AWS 模式：驗證必要的環境變數
    if DEPLOY_ENV == "aws":
        from src.utils.storage_service import validate_aws_config
        validate_aws_config()
        logger.info("app.startup.aws_config_validated")

    # 清理殘留的暫存目錄（處理 crash/重啟後的孤兒檔案）
    from src.utils.config_loader import cleanup_stale_temp_dirs
    cleanup_stale_temp_dirs()

    # 清理殘留的 ProcessPoolExecutor worker 進程
    try:
        cleaned = cleanup_worker_processes()
        logger.info("app.startup.stale_processes_cleaned", count=cleaned)
    except Exception as e:
        logger.warning("app.startup.stale_processes_cleanup_failed", error=str(e))

    # 獲取主事件循環
    main_loop = asyncio.get_running_loop()
    logger.info("app.startup.event_loop_ready")

    # 1. 連接 MongoDB
    mongodb_db = os.getenv('MONGODB_DB_NAME', 'whisper_transcriber')
    logger.info("app.db.connecting", mode=DEPLOY_ENV, database=mongodb_db)
    try:
        await asyncio.wait_for(MongoDB.connect(), timeout=10.0)
        logger.info("app.db.connected", database=mongodb_db)
    except asyncio.TimeoutError:
        logger.error("app.db.connect_timeout", timeout_seconds=10.0)
        raise
    except Exception as e:
        logger.error("app.db.connect_failed", error=str(e))
        raise

    # 2. 初始化 Repositories
    logger.info("app.repositories.initializing")
    db = MongoDB.get_db()
    task_repo = TaskRepository(db)
    tag_repo = TagRepository(db)
    audit_log_repo = AuditLogRepository(db)

    # 建立索引
    try:
        await task_repo.create_indexes()
        await audit_log_repo.create_indexes()
        # 建立 Summaries 索引
        from src.database.repositories.summary_repo import SummaryRepository
        summary_repo = SummaryRepository(db)
        await summary_repo.create_indexes()
        # 建立 RateLimit 索引（用於忘記密碼等功能的速率限制）
        from src.database.repositories.rate_limit_repo import RateLimitRepository
        rate_limit_repo = RateLimitRepository(db)
        await rate_limit_repo.ensure_indexes()
        # 建立 Orders 索引
        from src.database.repositories.order_repo import OrderRepository
        order_repo_init = OrderRepository(db)
        await order_repo_init.create_indexes()
        # 建立 Reservations 索引（額度預扣）
        from src.database.repositories.reservation_repo import ReservationRepository
        reservation_repo_init = ReservationRepository(db)
        await reservation_repo_init.create_indexes()
        # 建立 Users 索引（AI 摘要預扣 partial index，供背景清掃用）
        from src.database.repositories.user_repo import UserRepository
        user_repo_init = UserRepository(db)
        await user_repo_init.create_indexes()
        # 建立 processed_webhooks 索引（webhook 冪等性 + TTL 90 天清理）
        from src.database.repositories.processed_webhook_repo import ProcessedWebhookRepository
        processed_webhook_repo_init = ProcessedWebhookRepository(db)
        await processed_webhook_repo_init.create_indexes()
        logger.info("app.db.indexes_created")
    except Exception as e:
        logger.warning("app.db.index_creation_failed", error=str(e))

    # 統計任務數量
    task_count = await db.tasks.count_documents({})
    logger.info("app.db.ready", task_count=task_count)

    # 初始化 AuditLogger
    init_audit_logger(audit_log_repo)
    logger.info("app.audit_logger.initialized")

    # 3. 初始化 ProgressStore
    # Local 模式：InMemory adapter（同進程的 LocalDispatch / Orchestrator 寫，TaskService.get_task 讀）
    # AWS 模式：Mongo adapter（GPU Worker 寫 task_progress collection，Web Server 在這裡讀）
    if DEPLOY_ENV == "aws":
        from src.worker_core.db import get_db as _get_sync_db
        progress_store = MongoProgressStore(_get_sync_db().task_progress)
        logger.info("app.progress_store.initialized", adapter="mongo", mode="aws")
    else:
        progress_store = InMemoryProgressStore()
        logger.info("app.progress_store.initialized", adapter="in_memory", mode="local")

    # 3.1. 初始化 TaskService
    from src.dependencies import init_task_service
    task_service = init_task_service(
        db, state_store=task_state_store, progress_store=progress_store
    )
    logger.info("app.task_service.initialized")

    # 4. 清理異常中斷的任務
    logger.info("app.orphaned_tasks.cleaning")
    await task_service.cleanup_orphaned_tasks()

    # 5. 啟動定期記憶體清理
    create_background_task(
        task_service.periodic_memory_cleanup(),
        name="periodic_memory_cleanup",
    )

    # 5.1. 啟動定期孤立進程清理
    create_background_task(
        task_service.periodic_orphaned_process_cleanup(),
        name="periodic_orphaned_process_cleanup",
    )

    # 5.2. 啟動定期孤兒預扣清掃（轉錄 reservations + AI 摘要計數器）
    from src.database.repositories.reservation_repo import periodic_reservation_cleanup
    create_background_task(
        periodic_reservation_cleanup(db),
        name="periodic_reservation_cleanup",
    )

    # 6. 載入 Whisper 模型（條件式）
    if SHOULD_LOAD_MODELS:
        from faster_whisper import WhisperModel
        logger.info(
            "app.whisper.loading",
            model=DEFAULT_MODEL,
            device="auto",
            compute_type="int8",
        )
        current_model_name = DEFAULT_MODEL
        whisper_model = WhisperModel(
            current_model_name,
            device="auto",
            compute_type="int8",
            cpu_threads=2,  # 優化：配合 ProcessPoolExecutor，降低單進程並行度
            num_workers=1   # 優化：避免進程內過度並行（外部已有 ProcessPoolExecutor）
        )
        logger.info("app.whisper.loaded", model=current_model_name)
    else:
        logger.info("app.whisper.load_skipped")
        whisper_model = None
        current_model_name = None

    # 8. 載入 Diarization 模型（可選）
    if SHOULD_LOAD_MODELS and DIARIZATION_AVAILABLE:
        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            diarization_pipeline = DiarizationProcessor.load_pipeline(hf_token)
        else:
            logger.warning("app.diarization.hf_token_missing")
    elif not SHOULD_LOAD_MODELS:
        logger.info("app.diarization.load_skipped")

    # 9. 初始化 Task dispatch（依部署模式建 LocalDispatch 或 WorkerDispatch）
    from src.services.task_dispatch import get_task_dispatch, init_task_dispatch

    if SHOULD_LOAD_MODELS and whisper_model is not None:
        # local 模式：LocalDispatch（in-process executor + 撿單器）
        transcriptions_router.init_local_dispatch(
            whisper_model=whisper_model,
            task_service=task_service,
            model_name=current_model_name,  # 傳遞模型名稱供 ProcessPoolExecutor 使用
            diarization_pipeline=diarization_pipeline,
            executor=executor,
            progress_store=progress_store,
        )
        logger.info("app.local_dispatch.initialized")
    else:
        # AWS 模式：WorkerDispatch（boto3 client + S3 uploader 注入）
        import boto3
        from src.services.worker_dispatch import WorkerDispatch
        from src.utils.storage_service import upload_to_handoff
        from src.utils.config_loader import get_parameter as _gp

        sqs_region = os.getenv("S3_REGION", "ap-northeast-1")
        sqs_queue_url = os.getenv("SQS_QUEUE_URL", "")
        worker_secret = _gp(
            "/transcriber/worker-secret", fallback_env="WORKER_SECRET", default=""
        )
        init_task_dispatch(WorkerDispatch(
            sqs_client=boto3.client("sqs", region_name=sqs_region),
            sqs_queue_url=sqs_queue_url,
            worker_secret=worker_secret,
            handoff_uploader=upload_to_handoff,
        ))
        logger.info("app.worker_dispatch.initialized")

    # 10. 啟動 dispatch 背景機制（LocalDispatch 起撿單器；WorkerDispatch no-op）
    get_task_dispatch().start()

    logger.info("app.startup.ready", version="3.0.0")


@app.on_event("shutdown")
async def shutdown_event():
    """應用關閉時的清理"""
    logger.info("app.shutdown.began")

    # 關閉線程池
    if executor:
        executor.shutdown(wait=True)
        logger.info("app.shutdown.executor_closed")

    # 清理所有 ProcessPoolExecutor worker 進程
    cleaned = cleanup_worker_processes()
    if cleaned > 0:
        logger.info("app.shutdown.worker_processes_cleaned", count=cleaned)

    # 斷開 MongoDB
    await MongoDB.close()
    logger.info("app.shutdown.db_closed")

    logger.info("app.shutdown.done")


# ========== 基本端點 ==========

@app.get("/")
async def root():
    """根端點"""
    return {
        "service": "Whisper 轉錄服務",
        "version": "3.0.0",
        "architecture": "三層架構",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health")
async def health_check():
    """健康檢查端點：實際 ping DB，degraded 時回 503 讓 LB / CloudWatch 抓得到"""
    db_status = "unknown"
    db_error = None
    try:
        # 強制走連線：用 1 秒 timeout，避免拖垮整個 health probe
        client = MongoDB.client
        if client is None:
            db_status = "disconnected"
        else:
            await asyncio.wait_for(client.admin.command("ping"), timeout=1.0)
            db_status = "connected"
    except asyncio.TimeoutError:
        db_status = "timeout"
        db_error = "ping > 1s"
    except Exception as e:
        db_status = "error"
        db_error = str(e)[:200]

    healthy = db_status == "connected"
    body = {
        "status": "healthy" if healthy else "degraded",
        "deploy_env": DEPLOY_ENV,
        "app_role": APP_ROLE,
        "whisper_model": current_model_name,
        "diarization_available": diarization_pipeline is not None,
        "database": db_status,
    }
    if db_error:
        body["database_error"] = db_error
    if not healthy:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=body)
    return body


@app.get("/readiness")
async def readiness_check():
    """就緒檢查：DB ok 且（若需載入模型）model 已載入。給 LB / k8s readiness probe 用"""
    # DB 必須可 ping
    try:
        client = MongoDB.client
        if client is None:
            raise RuntimeError("client is None")
        await asyncio.wait_for(client.admin.command("ping"), timeout=1.0)
    except Exception as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ready": False, "reason": f"database not ready: {str(e)[:200]}"},
        )

    # 需要載入模型的角色（local 或 worker）必須 model 就緒
    if SHOULD_LOAD_MODELS and whisper_model is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"ready": False, "reason": "whisper model not loaded"},
        )

    return {"ready": True, "deploy_env": DEPLOY_ENV, "app_role": APP_ROLE}


# ========== 主程序入口 ==========

if __name__ == "__main__":
    import uvicorn

    # 從環境變數讀取配置
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("RELOAD", "false").lower() == "true"

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
