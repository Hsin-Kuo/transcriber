"""
Whisper 轉錄服務 - 新應用入口
採用清晰的三層架構設計
"""

import os
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
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
from src.routers import tasks as tasks_router
from src.routers import transcriptions as transcriptions_router
from src.routers import tags as tags_router
from src.routers import audio as audio_router

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

# 設定
DEFAULT_MODEL = "medium"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

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
executor = ThreadPoolExecutor(max_workers=3)

# 檢查 Diarization 是否可用
try:
    from pyannote.audio import Pipeline
    DIARIZATION_AVAILABLE = True
except ImportError:
    DIARIZATION_AVAILABLE = False
    print("⚠️  pyannote.audio 未安裝，speaker diarization 功能不可用")


# ========== 創建 FastAPI 應用 ==========

app = FastAPI(
    title="Whisper 轉錄服務",
    description="基於三層架構的音檔轉錄服務",
    version="3.0.0"
)

# CORS 中間件
cors_origins_str = os.getenv("CORS_ORIGINS", "*")
cors_origins = [origin.strip() for origin in cors_origins_str.split(",")] if cors_origins_str != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# ========== 註冊所有路由 ==========

app.include_router(auth_router.router)
app.include_router(tasks_router.router)
app.include_router(transcriptions_router.router)
app.include_router(tags_router.router)
app.include_router(audio_router.router)


# ========== 啟動與關閉事件 ==========

@app.on_event("startup")
async def startup_event():
    """應用啟動時的初始化"""
    global whisper_model, current_model_name, task_repo, tag_repo, audit_log_repo, main_loop, diarization_pipeline

    print("🚀 啟動 Whisper 轉錄服務 v3.0.0")
    print("=" * 50)

    # 獲取主事件循環
    main_loop = asyncio.get_running_loop()

    # 1. 連接 MongoDB
    print(f"🔌 正在連接 MongoDB...")
    try:
        await MongoDB.connect()
        print(f"✅ 已連接到 MongoDB: {os.getenv('MONGODB_DB_NAME', 'whisper_transcriber')}")
    except Exception as e:
        print(f"❌ MongoDB 連接失敗: {e}")
        print(f"   請確保 MongoDB 正在運行並檢查 .env 配置")
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

    # 6. 載入 Whisper 模型
    print(f"🎙 正在載入 Whisper 模型：{DEFAULT_MODEL}...")
    print(f"🔧 配置：device=auto, compute_type=int8")
    current_model_name = DEFAULT_MODEL
    whisper_model = WhisperModel(
        current_model_name,
        device="auto",
        compute_type="int8",
        cpu_threads=1,
        num_workers=4
    )
    print(f"✅ Whisper 模型載入完成！")

    # 8. 載入 Diarization 模型（可選）
    if DIARIZATION_AVAILABLE:
        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            diarization_pipeline = DiarizationProcessor.load_pipeline(hf_token)
        else:
            print("ℹ️  未設定 HF_TOKEN，speaker diarization 功能不可用")

    # 9. 初始化 TranscriptionService
    print(f"🔧 正在初始化 TranscriptionService...")
    transcriptions_router.init_transcription_service(
        whisper_model=whisper_model,
        task_service=task_service,
        diarization_pipeline=diarization_pipeline,
        executor=executor,
        output_dir=OUTPUT_DIR
    )
    print(f"✅ TranscriptionService 初始化完成")

    print("=" * 50)
    print(f"✨ 服務已就緒！")
    print(f"📚 API 文檔：http://localhost:8000/docs")
    print(f"🔗 健康檢查：http://localhost:8000/health")
    print("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """應用關閉時的清理"""
    print(f"👋 正在關閉服務...")

    # 關閉線程池
    if executor:
        executor.shutdown(wait=True)
        print(f"✅ 線程池已關閉")

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
        "whisper_model": current_model_name,
        "diarization_available": diarization_pipeline is not None,
        "database": "connected" if MongoDB.get_db() is not None else "disconnected"
    }


@app.get("/api/admin/statistics")
async def get_admin_statistics():
    """獲取後台統計資料（暫時無需認證）"""
    try:
        db = MongoDB.get_db()

        # 1. 總體統計
        total_tasks = await db.tasks.count_documents({})
        completed_tasks = await db.tasks.count_documents({"status": "completed"})
        processing_tasks = await db.tasks.count_documents({"status": "processing"})
        failed_tasks = await db.tasks.count_documents({"status": "failed"})

        # 2. Token 使用統計
        token_pipeline = [
            {
                "$match": {
                    "stats.token_usage.total": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$stats.token_usage.total"},
                    "total_prompt_tokens": {"$sum": "$stats.token_usage.prompt"},
                    "total_completion_tokens": {"$sum": "$stats.token_usage.completion"},
                    "tasks_with_tokens": {"$sum": 1}
                }
            }
        ]
        token_stats_cursor = db.tasks.aggregate(token_pipeline)
        token_stats_list = await token_stats_cursor.to_list(length=1)
        token_stats = token_stats_list[0] if token_stats_list else {
            "total_tokens": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "tasks_with_tokens": 0
        }

        # 3. 模型使用統計
        model_pipeline = [
            {
                "$match": {
                    "stats.token_usage.model": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": "$stats.token_usage.model",
                    "count": {"$sum": 1},
                    "total_tokens": {"$sum": "$stats.token_usage.total"}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ]
        model_stats_cursor = db.tasks.aggregate(model_pipeline)
        model_stats = await model_stats_cursor.to_list(length=None)

        # 4. 每日統計（最近 30 天）
        thirty_days_ago = (datetime.now(TZ_UTC8) - timedelta(days=30)).strftime("%Y-%m-%d")

        daily_pipeline = [
            {
                "$match": {
                    "timestamps.created_at": {"$gte": thirty_days_ago}
                }
            },
            {
                "$group": {
                    "_id": {"$substr": ["$timestamps.created_at", 0, 10]},
                    "tasks_count": {"$sum": 1},
                    "tokens_used": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}}
                }
            },
            {
                "$sort": {"_id": 1}
            }
        ]
        daily_stats_cursor = db.tasks.aggregate(daily_pipeline)
        daily_stats = await daily_stats_cursor.to_list(length=None)

        # 5. 使用者統計
        user_stats_pipeline = [
            {
                "$group": {
                    "_id": "$user.user_id",
                    "tasks_count": {"$sum": 1},
                    "tokens_used": {"$sum": {"$ifNull": ["$stats.token_usage.total", 0]}}
                }
            },
            {
                "$sort": {"tasks_count": -1}
            },
            {
                "$limit": 10
            }
        ]
        user_stats_cursor = db.tasks.aggregate(user_stats_pipeline)
        top_users = await user_stats_cursor.to_list(length=None)

        # 6. 平均處理時間
        avg_duration_pipeline = [
            {
                "$match": {
                    "status": "completed",
                    "stats.duration_seconds": {"$exists": True, "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "avg_duration": {"$avg": "$stats.duration_seconds"},
                    "min_duration": {"$min": "$stats.duration_seconds"},
                    "max_duration": {"$max": "$stats.duration_seconds"}
                }
            }
        ]
        duration_stats_cursor = db.tasks.aggregate(avg_duration_pipeline)
        duration_stats_list = await duration_stats_cursor.to_list(length=1)
        duration_stats = duration_stats_list[0] if duration_stats_list else {
            "avg_duration": 0,
            "min_duration": 0,
            "max_duration": 0
        }

        # 7. 標點符號服務使用統計
        punct_pipeline = [
            {
                "$group": {
                    "_id": "$config.punct_provider",
                    "count": {"$sum": 1}
                }
            },
            {
                "$sort": {"count": -1}
            }
        ]
        punct_stats_cursor = db.tasks.aggregate(punct_pipeline)
        punct_stats = await punct_stats_cursor.to_list(length=None)

        return {
            "overview": {
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "processing_tasks": processing_tasks,
                "failed_tasks": failed_tasks,
                "success_rate": round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0
            },
            "token_usage": {
                "total_tokens": token_stats.get("total_tokens", 0),
                "prompt_tokens": token_stats.get("total_prompt_tokens", 0),
                "completion_tokens": token_stats.get("total_completion_tokens", 0),
                "tasks_with_tokens": token_stats.get("tasks_with_tokens", 0),
                "avg_tokens_per_task": round(token_stats.get("total_tokens", 0) / token_stats.get("tasks_with_tokens", 1), 2) if token_stats.get("tasks_with_tokens", 0) > 0 else 0
            },
            "model_usage": [
                {
                    "model": stat["_id"] or "未知",
                    "count": stat["count"],
                    "total_tokens": stat.get("total_tokens", 0)
                }
                for stat in model_stats
            ],
            "daily_stats": [
                {
                    "date": stat["_id"],
                    "tasks_count": stat["tasks_count"],
                    "tokens_used": stat["tokens_used"]
                }
                for stat in daily_stats
            ],
            "top_users": [
                {
                    "user_id": stat["_id"],
                    "tasks_count": stat["tasks_count"],
                    "tokens_used": stat["tokens_used"]
                }
                for stat in top_users
            ],
            "performance": {
                "avg_duration_seconds": round(duration_stats.get("avg_duration", 0), 2),
                "min_duration_seconds": round(duration_stats.get("min_duration", 0), 2),
                "max_duration_seconds": round(duration_stats.get("max_duration", 0), 2)
            },
            "punct_provider_usage": [
                {
                    "provider": stat["_id"] or "none",
                    "count": stat["count"]
                }
                for stat in punct_stats
            ]
        }

    except Exception as e:
        print(f"❌ 獲取統計資料失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取統計資料失敗：{str(e)}"
        )


@app.get("/api/admin/audit-logs")
async def get_audit_logs(
    limit: int = 100,
    skip: int = 0,
    log_type: str = None,
    user_id: str = None
):
    """獲取操作記錄（管理員）

    Args:
        limit: 限制數量（預設 100）
        skip: 跳過數量（預設 0）
        log_type: 過濾日誌類型（可選）
        user_id: 過濾用戶 ID（可選）

    Returns:
        操作記錄列表
    """
    try:
        if user_id:
            logs = await audit_log_repo.get_by_user(user_id, limit=limit, skip=skip, log_type=log_type)
        else:
            logs = await audit_log_repo.get_recent(limit=limit, skip=skip, log_type=log_type)

        # 轉換 ObjectId 為字串
        for log in logs:
            if "_id" in log:
                log["_id"] = str(log["_id"])

        return {
            "logs": logs,
            "total": len(logs),
            "limit": limit,
            "skip": skip
        }
    except Exception as e:
        print(f"❌ 獲取操作記錄失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取操作記錄失敗：{str(e)}"
        )


@app.get("/api/admin/audit-logs/failed")
async def get_failed_audit_logs(
    days: int = 7,
    limit: int = 100
):
    """獲取失敗的操作記錄（管理員）

    Args:
        days: 最近幾天（預設 7）
        limit: 限制數量（預設 100）

    Returns:
        失敗操作記錄列表
    """
    try:
        logs = await audit_log_repo.get_failed_operations(days=days, limit=limit)

        return {
            "failed_logs": logs,
            "total": len(logs),
            "days": days
        }
    except Exception as e:
        print(f"❌ 獲取失敗操作記錄失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取失敗操作記錄失敗：{str(e)}"
        )


@app.get("/api/admin/audit-logs/statistics")
async def get_audit_statistics(
    days: int = 30
):
    """獲取操作記錄統計（管理員）

    Args:
        days: 最近幾天（預設 30）

    Returns:
        操作統計
    """
    try:
        stats = await audit_log_repo.get_statistics(days=days)

        return {
            "statistics": stats,
            "days": days
        }
    except Exception as e:
        print(f"❌ 獲取操作統計失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取操作統計失敗：{str(e)}"
        )


@app.get("/api/admin/audit-logs/resource/{resource_id}")
async def get_resource_audit_logs(
    resource_id: str,
    limit: int = 50
):
    """獲取特定資源的操作記錄（管理員）

    Args:
        resource_id: 資源 ID（如 task_id）
        limit: 限制數量（預設 50）

    Returns:
        資源操作記錄列表
    """
    try:
        logs = await audit_log_repo.get_by_resource(resource_id, limit=limit)

        return {
            "resource_id": resource_id,
            "logs": logs,
            "total": len(logs)
        }
    except Exception as e:
        print(f"❌ 獲取資源操作記錄失敗：{e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取資源操作記錄失敗：{str(e)}"
        )


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
