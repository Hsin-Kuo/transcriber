"""測試全域護欄。

SENTRY_DSN 必須清空：src/main.py 在 import 時 load_dotenv() + init_sentry()，
若開發機 .env 有真實 DSN，任何 import src.main 的測試都會讓後續
capture_message/capture_exception 對真實 Sentry 專案送事件
（症狀：pytest 結束時出現「Sentry is attempting to send N pending events」）。
conftest 在所有測試模組之前載入，在這裡清掉可保證 init_sentry() no-op。

CARD_TOKEN_KEK（P2-10，金流體檢）：card_token_cipher.encrypt/decrypt 需要一把
有效的 32-byte base64 KEK 才能運作（get_parameter(required=True)，缺值直接
RuntimeError）。用 setdefault 給全測試套件一個固定的公開測試值——沒有特別
覆寫 env 的既有測試（不碰加密路徑）完全不受影響；需要驗證「KEK 錯誤/缺值」
行為的測試（tests/utils/test_card_token_cipher.py）自行用 monkeypatch 覆寫。
"""
import base64
import os

os.environ["SENTRY_DSN"] = ""
os.environ.setdefault(
    "CARD_TOKEN_KEK",
    base64.b64encode(b"test-card-token-kek-32-bytes!!!!").decode(),
)
