"""Debug dump 儲存 — DIAR_DEBUG_DUMP 開啟時的 word 級語者對齊除錯 JSON。

非使用者資料的暫時性除錯產物（staging 驗證 word timestamp / 對齊行為用），
與 Compact / Handoff audio 無語意關聯，獨立一個薄模組。
AWS 模式上傳 S3 `debug/diar/{task_id}.json`；local 模式落在
`uploads/debug/diar/{task_id}.json`（比照 compact 的 local 慣例）。
"""
import json
from pathlib import Path

from .backend import (
    S3_BUCKET,
    get_s3,
    is_aws,
    validate_task_id,
)


def _debug_diar_key(task_id: str) -> str:
    """產生除錯 JSON 的 S3 key（task_id 過 UUID 驗證，防 path injection）。"""
    validate_task_id(task_id)
    return f"debug/diar/{task_id}.json"


def save_diar_debug_dump(task_id: str, payload: dict) -> str:
    """儲存 diar 對齊除錯 JSON，回傳儲存位置（s3:// URI 或本地路徑）。

    呼叫端（orchestrator）自行 try/except——dump 失敗只該 log warning，
    絕不影響任務本體。
    """
    validate_task_id(task_id)  # 入口守門，比照 compact/handoff 公開儲存函數慣例
    key = _debug_diar_key(task_id)
    body = json.dumps(payload, ensure_ascii=False)
    if is_aws():
        get_s3().put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )
        return f"s3://{S3_BUCKET}/{key}"
    dest = Path("uploads") / "debug" / "diar" / f"{task_id}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return str(dest)
