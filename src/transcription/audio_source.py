"""AudioSource — Orchestrator 取得 Handoff audio 的唯一變化點。

對應 CONTEXT.md「AudioSource」。Web Server 與 Worker 共用同一個 Orchestrator,
兩進程之間唯一不同的點——「音檔從哪來」——由此 seam 抽掉:

- LocalFileSource: Web Server 同進程模式,router 已把音檔放在 disk 上。
- S3Source: AWS Worker,從 handoff/{task_id}.{ext} 下載;成功時刪除 handoff 物件。

只負責 acquire() + cleanup()——格式轉換歸 audio_converter、永久儲存歸
storage_service,都不在此。
"""
from pathlib import Path
from typing import Optional, Protocol

from src.utils.storage_service import (
    delete_handoff,
    download_audio,
    download_from_handoff,
)


class AudioSource(Protocol):
    """取得單一 Task 的 Handoff audio 到本機檔案系統。"""

    def acquire(self, dest_dir: Path) -> Path:
        """下載/定位音檔,回傳本機可讀路徑。dest_dir 由 Orchestrator 提供。"""
        ...

    def cleanup(self, succeeded: bool) -> None:
        """釋放 acquire 取得的遠端資源。

        Orchestrator 三條 exit path(成功/取消/失敗)都會呼叫;succeeded 用來
        區分——handoff 物件只在成功時刪,失敗時保留供重試。
        """
        ...


class LocalFileSource:
    """Web Server 同進程模式:router 已把音檔放在 temp_dir,直接回傳路徑。"""

    def __init__(self, path: Path):
        self._path = path

    def acquire(self, dest_dir: Path) -> Path:
        return self._path

    def cleanup(self, succeeded: bool) -> None:
        # router 為每個 task 建獨立 temp_dir 放輸入音檔(path 的父目錄);
        # 轉錄結束後整個清掉。Compact audio 此時已被 save_audio 搬到永久區。
        import shutil
        shutil.rmtree(self._path.parent, ignore_errors=True)


class S3Source:
    """AWS Worker 模式:從 S3 handoff 區下載 Handoff audio。

    handoff_ext 為 None 代表來自舊版 Server(Layer 2 前),fallback 到
    uploads/{tier}/{task_id} 下載——SQS 排空後可拔。
    """

    def __init__(self, task_id: str, handoff_ext: Optional[str], user_tier: str):
        self._task_id = task_id
        self._handoff_ext = handoff_ext
        self._user_tier = user_tier

    def acquire(self, dest_dir: Path) -> Path:
        # boto3 download_file / shutil.copy2 都不會自動建父目錄,adapter 自己確保
        dest_dir.mkdir(parents=True, exist_ok=True)
        if self._handoff_ext:
            dest = dest_dir / f"{self._task_id}.{self._handoff_ext}"
            download_from_handoff(self._task_id, self._handoff_ext, dest)
        else:
            dest = dest_dir / f"{self._task_id}.original"
            download_audio(self._task_id, dest, tier=self._user_tier)
        return dest

    def cleanup(self, succeeded: bool) -> None:
        # handoff 只是 Web Server → Worker 的傳遞暫態;成功落地 Compact audio 後即可刪。
        # 失敗/取消時保留,讓任務可從 handoff 重試;殘留由 orphan sweep 收。
        if succeeded and self._handoff_ext:
            try:
                delete_handoff(self._task_id, self._handoff_ext)
            except Exception as e:
                print(f"⚠️ 刪除 handoff 失敗（將由 sweep 處理）：{e}")
