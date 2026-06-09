"""
Worker heartbeat 寫入。

Web Server 可查詢 `worker_heartbeats` collection 判斷 worker 是否健在。
CloudWatch alarm 應該基於「最近 heartbeat > N 分鐘」觸發。
"""
import os
import socket
import time
import threading
from datetime import datetime, timezone
from typing import Optional

import urllib.request

from src.worker_core.db import get_db
from src.utils.logger import get_logger

log = get_logger(__name__)


_HEARTBEAT_INTERVAL_SECONDS = 60
_worker_id_cache: Optional[str] = None
_lifecycle_cache: Optional[str] = None
_heartbeat_thread_started = False
_heartbeat_lock = threading.Lock()


def _fetch_imds(path: str) -> Optional[str]:
    """從 EC2 IMDSv2 取得指定 metadata path，失敗回 None（本地開發用）。

    path 例如 "instance-id" / "instance-life-cycle"。
    """
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(token_req, timeout=1) as resp:
            token = resp.read().decode()

        meta_req = urllib.request.Request(
            f"http://169.254.169.254/latest/meta-data/{path}",
            headers={"X-aws-ec2-metadata-token": token},
        )
        with urllib.request.urlopen(meta_req, timeout=1) as resp:
            return resp.read().decode()
    except Exception:
        return None


def get_worker_id() -> str:
    """worker_id 優先序：環境變數 > EC2 instance-id > hostname"""
    global _worker_id_cache
    if _worker_id_cache is not None:
        return _worker_id_cache

    env_id = os.getenv("WORKER_ID")
    if env_id:
        _worker_id_cache = env_id
    else:
        _worker_id_cache = _fetch_imds("instance-id") or socket.gethostname()
    return _worker_id_cache


def get_worker_lifecycle() -> str:
    """實例計費型態："spot" / "on-demand"；非 EC2（本地開發）為 "unknown"。

    供 Web Server / 後台統計 Spot 命中率，不必再翻 Lambda CloudWatch log。
    """
    global _lifecycle_cache
    if _lifecycle_cache is not None:
        return _lifecycle_cache

    _lifecycle_cache = _fetch_imds("instance-life-cycle") or "unknown"
    return _lifecycle_cache


def write_heartbeat(
    status: str,
    last_task_id: Optional[str] = None,
    task_completed: bool = False,
) -> None:
    """寫入單筆 heartbeat（upsert by worker_id）。失敗只記 log，不中斷主流程。"""
    try:
        now = datetime.now(timezone.utc)
        update = {
            "$set": {
                "worker_id": get_worker_id(),
                "lifecycle": get_worker_lifecycle(),
                "status": status,
                "last_heartbeat_at": now,
            }
        }
        if last_task_id is not None:
            update["$set"]["last_task_id"] = last_task_id
        if task_completed:
            update["$set"]["last_task_completed_at"] = now

        get_db().worker_heartbeats.update_one(
            {"worker_id": get_worker_id()},
            update,
            upsert=True,
        )
    except Exception as e:
        log.warning("heartbeat.write_failed", error=str(e))


def start_background_heartbeat() -> None:
    """啟動背景執行緒，每 60 秒寫一次 heartbeat（維持 alive 信號，即使閒置）"""
    global _heartbeat_thread_started
    with _heartbeat_lock:
        if _heartbeat_thread_started:
            return
        _heartbeat_thread_started = True

    def _loop():
        while True:
            time.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            # 不覆蓋 status：呼叫者在狀態變化時自行寫
            try:
                get_db().worker_heartbeats.update_one(
                    {"worker_id": get_worker_id()},
                    {"$set": {"last_heartbeat_at": datetime.now(timezone.utc)}},
                    upsert=True,
                )
            except Exception as e:
                log.warning("heartbeat.background_write_failed", error=str(e))

    threading.Thread(target=_loop, daemon=True, name="HeartbeatLoop").start()
