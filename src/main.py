"""
Whisper 轉錄服務 - 新應用入口
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

# Services
from src.services.utils.diarization_processor import DiarizationProcessor

# Utils
from src.utils.audit_logger import init_audit_logger

# 共享狀態
from src.utils.shared_state import (
    transcription_tasks,
    task_cancelled,
    task_temp_dirs,
    task_diarization_processes,
    tasks_lock
)

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
        print("⚠️  pyannote.audio 未安裝，speaker diarization 功能不可用")
else:
    print(f"ℹ️  DEPLOY_ENV={DEPLOY_ENV}, APP_ROLE={APP_ROLE}：跳過 ML 模型載入")


# ========== 創建 FastAPI 應用 ==========

app = FastAPI(
    title="Whisper 轉錄服務",
    description="基於三層架構的音檔轉錄服務",
    version="3.0.0"
)

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
        print("⚠️  CORS: 開發模式，允許本地來源", flush=True)
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
            print(f"🧹 清理 {len(pids)} 個 worker 進程...")
            subprocess.run(["pkill", "-9", "-f", "multiprocessing.spawn"], check=False)
            subprocess.run(["pkill", "-9", "-f", "multiprocessing.resource_tracker"], check=False)
            return len(pids)
        return 0
    except Exception as e:
        print(f"⚠️  清理 worker 進程時發生錯誤: {e}")
        return 0


def signal_handler(signum, frame):
    """處理終止信號，確保清理所有資源"""
    print(f"\n⚠️  收到終止信號 ({signal.Signals(signum).name})，正在清理...")
    cleanup_worker_processes()
    print(f"✅ 清理完成，退出程序")
    exit(0)


# 註冊信號處理器
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ========== 啟動與關閉事件 ==========

@app.on_event("startup")
async def startup_event():
    """應用啟動時的初始化"""
    global whisper_model, current_model_name, task_repo, tag_repo, audit_log_repo, main_loop, diarization_pipeline

    print("🚀 啟動 Whisper 轉錄服務 v3.0.0", flush=True)
    print("=" * 50, flush=True)

    # AWS 模式：驗證必要的環境變數
    if DEPLOY_ENV == "aws":
        from src.utils.storage_service import validate_aws_config
        validate_aws_config()
        print("✅ AWS 設定驗證通過", flush=True)

    # 清理殘留的 ProcessPoolExecutor worker 進程
    print("🧹 清理殘留的 worker 進程...", flush=True)
    try:
        cleaned = cleanup_worker_processes()
        if cleaned > 0:
            print(f"   ✅ 已清理 {cleaned} 個殘留進程", flush=True)
        else:
            print("   ✅ 沒有發現殘留的 worker 進程", flush=True)
    except Exception as e:
        print(f"   ⚠️  清理進程時出錯: {e}", flush=True)

    # 獲取主事件循環
    print("📡 獲取事件循環...", flush=True)
    main_loop = asyncio.get_running_loop()
    print("✅ 事件循環已就緒", flush=True)

    # 1. 連接 MongoDB
    mongodb_db = os.getenv('MONGODB_DB_NAME', 'whisper_transcriber')
    print(f"🔌 正在連接 MongoDB...", flush=True)
    print(f"   Mode: {DEPLOY_ENV}", flush=True)
    print(f"   Database: {mongodb_db}", flush=True)
    try:
        await asyncio.wait_for(MongoDB.connect(), timeout=10.0)
        print(f"✅ 已連接到 MongoDB: {mongodb_db}", flush=True)
    except asyncio.TimeoutError:
        print(f"❌ MongoDB 連接超時（10秒）", flush=True)
        print(f"   請確保 MongoDB 正在運行", flush=True)
        raise
    except Exception as e:
        print(f"❌ MongoDB 連接失敗: {e}", flush=True)
        print(f"   請確保 MongoDB 正在運行並檢查配置", flush=True)
        raise

    # 2. 初始化 Repositories
    print(f"📂 正在初始化 Repositories...")
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
        print(f"✅ 資料庫索引建立完成")
    except Exception as e:
        print(f"⚠️  索引建立失敗: {e}")

    # 統計任務數量
    task_count = await db.tasks.count_documents({})
    print(f"✅ 資料庫已就緒（共 {task_count} 個任務）")

    # 初始化 AuditLogger
    print(f"📝 正在初始化 AuditLogger...")
    init_audit_logger(audit_log_repo)
    print(f"✅ AuditLogger 初始化完成")

    # 3. 初始化 TaskService（使用共享的全域字典）
    print(f"🔧 正在初始化 TaskService...")
    task_service = tasks_router.init_task_service(
        db,
        memory_tasks=transcription_tasks,
        cancelled_tasks=task_cancelled,
        temp_dirs=task_temp_dirs,
        diarization_processes=task_diarization_processes,
        lock=tasks_lock
    )
    print(f"✅ TaskService 初始化完成")

    # 4. 清理異常中斷的任務
    print(f"🧹 清理異常中斷的任務...")
    await task_service.cleanup_orphaned_tasks()

    # 5. 啟動定期記憶體清理
    asyncio.create_task(task_service.periodic_memory_cleanup())

    # 5.1. 啟動定期孤立進程清理
    asyncio.create_task(task_service.periodic_orphaned_process_cleanup())

    # 5.5. 啟動任務隊列處理器（在 TranscriptionService 初始化後）
    # 注意：這裡暫時先創建任務，稍後在 TranscriptionService 初始化後會實際啟動
    queue_processor_task = None

    # 6. 載入 Whisper 模型（條件式）
    if SHOULD_LOAD_MODELS:
        from faster_whisper import WhisperModel
        print(f"🎙 正在載入 Whisper 模型：{DEFAULT_MODEL}...")
        print(f"🔧 配置：device=auto, compute_type=int8")
        current_model_name = DEFAULT_MODEL
        whisper_model = WhisperModel(
            current_model_name,
            device="auto",
            compute_type="int8",
            cpu_threads=2,  # 優化：配合 ProcessPoolExecutor，降低單進程並行度
            num_workers=1   # 優化：避免進程內過度並行（外部已有 ProcessPoolExecutor）
        )
        print(f"✅ Whisper 模型載入完成！")
    else:
        print(f"ℹ️  AWS Web Server 模式：跳過 Whisper 模型載入")
        whisper_model = None
        current_model_name = None

    # 8. 載入 Diarization 模型（可選）
    if SHOULD_LOAD_MODELS and DIARIZATION_AVAILABLE:
        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            diarization_pipeline = DiarizationProcessor.load_pipeline(hf_token)
        else:
            print("ℹ️  未設定 HF_TOKEN，speaker diarization 功能不可用")
    elif not SHOULD_LOAD_MODELS:
        print(f"ℹ️  AWS Web Server 模式：跳過 Diarization 模型載入")

    # 9. 初始化 TranscriptionService（僅在有 Whisper 模型時）
    transcription_service = None
    if SHOULD_LOAD_MODELS and whisper_model is not None:
        print(f"🔧 正在初始化 TranscriptionService...")
        transcription_service = transcriptions_router.init_transcription_service(
            whisper_model=whisper_model,
            task_service=task_service,
            model_name=current_model_name,  # 傳遞模型名稱供 ProcessPoolExecutor 使用
            diarization_pipeline=diarization_pipeline,
            executor=executor
        )
        print(f"✅ TranscriptionService 初始化完成")

        # 10. 啟動任務隊列處理器
        print(f"🚀 正在啟動任務隊列處理器...")
        asyncio.create_task(task_service.process_pending_queue(transcription_service, max_concurrent=2))
        print(f"✅ 任務隊列處理器已啟動")
    else:
        print(f"ℹ️  AWS Web Server 模式：跳過 TranscriptionService 初始化和任務隊列")

    print("=" * 50)
    print(f"✨ 服務已就緒！")
    print(f"📚 API 文檔：http://localhost:8000/docs")
    print(f"🔗 健康檢查：http://localhost:8000/health")
    print(f"📋 任務隊列：最多 2 個並發任務")
    print("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """應用關閉時的清理"""
    print(f"👋 正在關閉服務...")

    # 關閉線程池
    if executor:
        executor.shutdown(wait=True)
        print(f"✅ 線程池已關閉")

    # 清理所有 ProcessPoolExecutor worker 進程
    cleaned = cleanup_worker_processes()
    if cleaned > 0:
        print(f"✅ 已清理 {cleaned} 個 worker 進程")

    # 斷開 MongoDB
    await MongoDB.close()
    print(f"✅ MongoDB 連接已關閉")

    print(f"👋 服務已關閉")


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
    """健康檢查端點"""
    return {
        "status": "healthy",
        "deploy_env": DEPLOY_ENV,
        "app_role": APP_ROLE,
        "whisper_model": current_model_name,
        "diarization_available": diarization_pipeline is not None,
        "database": "connected" if MongoDB.get_db() is not None else "disconnected"
    }


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
