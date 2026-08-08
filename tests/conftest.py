"""測試全域護欄。

SENTRY_DSN 必須清空：src/main.py 在 import 時 load_dotenv() + init_sentry()，
若開發機 .env 有真實 DSN，任何 import src.main 的測試都會讓後續
capture_message/capture_exception 對真實 Sentry 專案送事件
（症狀：pytest 結束時出現「Sentry is attempting to send N pending events」）。
conftest 在所有測試模組之前載入，在這裡清掉可保證 init_sentry() no-op。
"""
import os

os.environ["SENTRY_DSN"] = ""
