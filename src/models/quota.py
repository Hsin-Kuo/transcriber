"""配額等級定義"""
from enum import Enum


class QuotaTier(str, Enum):
    """配額等級"""
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# 配額等級詳細定義
QUOTA_TIERS = {
    QuotaTier.FREE: {
        "name": "免費版",
        "max_transcriptions": 999999,         # 不限次數
        "max_duration_minutes": 180,        # 每月 180 分鐘
        "max_concurrent_tasks": 1,         # 同時 1 個任務
        "audio_retention_days": 3,         # 音檔保留天數（S3 Lifecycle）
        "max_keep_audio": 0,               # 手動保留音檔額度
        "features": {
            "speaker_diarization": False,
            "punctuation": True,
            "batch_operations": False,
            "priority_processing": False
        },
        "price": 0
    },
    QuotaTier.BASIC: {
        "name": "基礎版",
        "max_transcriptions": 999999,         # 不限次數
        "max_duration_minutes": 600,       # 每月 600 分鐘 (10 小時)
        "max_concurrent_tasks": 2,
        "audio_retention_days": 7,         # 音檔保留天數（S3 Lifecycle）
        "max_keep_audio": 10,              # 手動保留音檔額度
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": True,
            "priority_processing": False
        },
        "price": 9.99  # USD/月
    },
    QuotaTier.PRO: {
        "name": "專業版",
        "max_transcriptions": 999999,         # 不限次數
        "max_duration_minutes": 3000,      # 每月 3000 分鐘 (50 小時)
        "max_concurrent_tasks": 5,
        "audio_retention_days": 7,         # 音檔保留天數（S3 Lifecycle）
        "max_keep_audio": 30,              # 手動保留音檔額度
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": True,
            "priority_processing": True
        },
        "price": 29.99  # USD/月
    },
    QuotaTier.ENTERPRISE: {
        "name": "企業版",
        "max_transcriptions": 999999,      # 無限制
        "max_duration_minutes": 999999,
        "max_concurrent_tasks": 10,
        "audio_retention_days": 7,         # 音檔保留天數（S3 Lifecycle）
        "max_keep_audio": 999999,          # 無限制手動保留
        "features": {
            "speaker_diarization": True,
            "punctuation": True,
            "batch_operations": True,
            "priority_processing": True
        },
        "price": 99.99  # USD/月
    }
}
