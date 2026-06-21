"""api_error 錯誤契約 helper 的單元測試。不需 MongoDB / env。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.api_errors import api_error, ErrorCode  # noqa: E402


def test_api_error_basic_shape():
    exc = api_error("UPLOAD_DISK_FULL", "空間不足", 507)
    assert exc.status_code == 507
    assert exc.detail == {"code": "UPLOAD_DISK_FULL", "message": "空間不足"}


def test_api_error_with_params():
    exc = api_error(ErrorCode.FILE_TOO_LARGE, "檔案超過 3072MB 上限", 413, max=3072)
    assert exc.status_code == 413
    assert exc.detail["code"] == "FILE_TOO_LARGE"
    assert exc.detail["message"] == "檔案超過 3072MB 上限"
    assert exc.detail["params"] == {"max": 3072}


def test_api_error_omits_params_when_empty():
    """無 params 時不放空 dict，detail 保持精簡。"""
    exc = api_error(ErrorCode.INVALID_FILE_SIZE, "檔案大小無效", 400)
    assert "params" not in exc.detail
