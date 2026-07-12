"""跨測試檔共用的 Response header 檢查小工具。

只放純函式（無 fixture、無狀態）——這個 repo 沒有 conftest.py 慣例
（tests/routers/test_batch_gating.py 等既有測試都是 per-file inline
fake，是刻意的既定風格），這裡不引入新的 fixture 機制，只是把重複
三次的 Set-Cookie 檢查邏輯收斂成一個共用函式。
"""
from fastapi import Response


def get_set_cookie_headers(response: Response) -> list[str]:
    """回傳 response 裡所有 Set-Cookie header 的原始字串列表。"""
    return [v.decode() for k, v in response.raw_headers if k.lower() == b"set-cookie"]
