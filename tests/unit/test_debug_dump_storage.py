"""debug_dump 儲存模組：local 模式落檔路徑/內容、task_id 驗證（防 path injection）。"""
import json
import uuid

import pytest

from src.utils.storage.debug_dump import save_diar_debug_dump


def test_local_mode_writes_json_under_uploads_debug_diar(tmp_path, monkeypatch):
    # local 模式（DEPLOY_ENV != aws）→ 寫到 cwd 下 uploads/debug/diar/{task_id}.json
    monkeypatch.chdir(tmp_path)
    task_id = str(uuid.uuid4())
    payload = {"task_id": task_id, "diar_turns": [], "segments_words": [], "final_segments": []}

    dest = save_diar_debug_dump(task_id, payload)

    expected = tmp_path / "uploads" / "debug" / "diar" / f"{task_id}.json"
    assert dest == str(expected.relative_to(tmp_path))
    assert json.loads(expected.read_text(encoding="utf-8")) == payload


def test_invalid_task_id_rejected(tmp_path, monkeypatch):
    # task_id 過 UUID 驗證——防 path injection（../../ 之類直接炸 ValueError）
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        save_diar_debug_dump("../evil", {"x": 1})
