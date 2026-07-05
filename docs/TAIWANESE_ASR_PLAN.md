# 台語 ASR 模型（Breeze-ASR-26）加掛計畫

> 狀態：程式碼已實作（feat/taiwanese-asr-routing，語言代碼定案 `nan-TW`）。
> 待辦：模型檔部署路徑決策 + staging 端到端驗證（見「驗收方式」與「待決事項」）。
> 模型：[MediaTek-Research/Breeze-ASR-26](https://huggingface.co/MediaTek-Research/Breeze-ASR-26)

## 背景

使用者若選擇「台語」轉錄，現有 `large-v3-turbo` 辨識效果不佳，考慮加掛一顆專門微調過的台語 ASR 模型，依語言參數路由到對應模型。

## 模型規格

- 基礎架構：Whisper large-v2 微調，2B 參數，F32 權重
- 授權：Apache 2.0（可商用）
- 訓練資料：~10,000 小時台語合成語音
- 輸出：**漢字轉錄**，非台語羅馬字/教會羅馬拼音 —— 前端文案/使用者預期需對齊這點
- 官方僅提供 HuggingFace Transformers 範例，**無官方 CTranslate2 支援**

## Staging 可行性實測結果（2026-07-04，g4dn.xlarge / T4 16GB）

| 項目 | 結果 |
|---|---|
| CTranslate2 轉檔 | ✅ 成功，但需額外步驟：官方 repo 只有舊式 slow tokenizer（`vocab.json`+`merges.txt`等），沒有 `tokenizer.json`。修法：`snapshot_download` 到本地目錄 + `AutoTokenizer.from_pretrained().save_pretrained()` 生成 `tokenizer.json`，再對本地目錄跑 `ct2-transformers-converter --quantization float16` |
| 顯存（T4 16GB，第一輪粗測，用 `large-v3-turbo`）| baseline 0 → +large-v3-turbo 2185 MiB → +Breeze-ASR-26（累加）5769 MiB；兩模型同時常駐+跑 transcribe 峰值 7167 MiB |
| **顯存（T4 16GB，第二輪精測，2026-07-05，用正式配置 `large-v3` + diarization + Breeze，系統 python 環境）** | baseline 0 → +`large-v3` 3849 MiB → +diarization（pyannote 3.1）3823 MiB（增量在量測雜訊範圍內，本身很輕）→ +Breeze-ASR-26 7503 MiB → 三顆常駐+依序真實推論（transcribe×2+diarization×1）峰值 **7791 MiB（僅佔 T4 總量 51%）** |
| 真實 transcribe | 三顆模型同時常駐時各自跑通（10 秒測試音檔，僅驗證可執行，非準確度測試）|
| 磁碟 | 轉檔後模型檔（float16 `model.bin`）3.08GB；測試目錄 `~/breeze-test/` 共 14GB；staging worker 根磁碟一度剩 11GB（90% used），已排查清理至 47%（見「磁碟空間」章節），2026-07-05 複測維持 47% |
| 結論 | **技術可行，且現有 T4 16GB 資源足夠（用正式 `large-v3` 配置精測峰值僅 51%），不需升級 GPU instance** |

轉檔後產物留在 staging worker `i-01a34a514d56269db` 的 `~/breeze-test/breeze-asr-26-ct2/`。

## 架構改動：`model_cache.py` 多模型路由

現況：`src/worker_core/model_cache.py` 是全域單例，只快取一顆 Whisper 模型，語言參數完全不影響模型選擇（`whisper_processor.py` 的 `_normalize_language()` 只把語言當 decode 提示詞）。

### 改動 1：`src/worker_core/config.py`

```python
# 特定語言的專用模型（例：台語）。key 用 job.language 的值，value 是模型路徑或 HF/CT2 model id。
# 沒設定對應 env var 時該語言不會有 override，退回 DEFAULT_MODEL。
LANGUAGE_MODEL_OVERRIDES: dict[str, str] = {
    lang: path
    for lang, path in {
        "nan-TW": os.getenv("WHISPER_MODEL_NAN_TW", ""),  # 例：/opt/models/breeze-asr-26-ct2
    }.items()
    if path
}
```

### 改動 2：`src/worker_core/model_cache.py`

單例改成 dict 快取，依「解析後的模型路徑」為 key（同一路徑不重複載入）：

```python
_cached_whisper_processors: dict[str, "WhisperProcessor"] = {}

def _resolve_model_path(language: str | None) -> str:
    if language and language in LANGUAGE_MODEL_OVERRIDES:
        return LANGUAGE_MODEL_OVERRIDES[language]
    return DEFAULT_MODEL

def get_whisper_processor(language: str | None = None):
    model_path = _resolve_model_path(language)
    if model_path not in _cached_whisper_processors:
        from faster_whisper import WhisperModel
        from src.services.utils.whisper_processor import WhisperProcessor

        log.info("whisper.model.loading", model=model_path, language=language, compute_type="float16")
        whisper_model = WhisperModel(model_path, device="auto", compute_type="float16")
        _cached_whisper_processors[model_path] = WhisperProcessor(whisper_model, model_path)
        log.info("whisper.model.loaded", model=model_path)
    return _cached_whisper_processors[model_path]
```

### 改動 3：`src/worker_core/transcription_job.py:76`

```python
whisper=get_whisper_processor(job.language),
```

開機預熱（`sqs_consumer.py:173`）維持 `get_whisper_processor()` 不帶參數 → 只預熱 `DEFAULT_MODEL`。

### 設計取捨

- **Lazy load，不 eager 預熱 Breeze**：顯存夠，但沒必要讓每台 worker 開機都多背 3.5GB+等待時間，除非台語任務量大到值得預熱。
- **不做 LRU/卸載機制**：目前只會新增一顆語言模型，dict 最多兩個 entry。
- **不用鎖**：worker 本來就單執行緒依序處理任務（`sqs_consumer.py` `MaxNumberOfMessages=1`），無 race condition。

### 已驗證安全的細節

`WhisperProcessor` 內部把 `model_name` 原封不動傳給子進程重新 `WhisperModel(model_name, ...)`（`whisper_processor.py:238-244, 455`），沒有任何依字串內容做的特殊判斷（沒有 `if "turbo" in model_name` 這類邏輯），所以 `model_name` 換成本地 CTranslate2 目錄路徑完全安全，不會破壞現有 CPU 平行處理路徑。

## 已定案決策（2026-07-05）

1. **語言代碼 = `nan-TW`**（BCP-47：nan 閩南語 + TW 地區，與 zh-TW/zh-CN 命名風格一致）。已同步落在：前端兩個選單、`ALLOWED_LANGUAGES` 白名單、`LANGUAGE_MODEL_OVERRIDES` key、env 變數 `WHISPER_MODEL_NAN_TW`。
2. **前端文案 =「台語（輸出為漢字）」**（i18n key `transcription.langTaiwanese`；en：Taiwanese (output in Chinese characters)），在選單上就把漢字輸出的預期講清楚。

## 實作內容（feat/taiwanese-asr-routing）

| 檔案 | 改動 |
|---|---|
| `src/worker_core/config.py` | 新增 `LANGUAGE_MODEL_OVERRIDES`（`nan-TW` ← env `WHISPER_MODEL_NAN_TW`，未設不進表）|
| `src/worker_core/model_cache.py` | 單例改 dict 快取（key = 解析後模型路徑）；`get_whisper_processor(language=None)` + `_resolve_model_path()`；lazy load、常駐不卸載 |
| `src/worker_core/transcription_job.py` | `get_whisper_processor(job.language)` |
| `src/services/utils/whisper_processor.py` | `_normalize_language` 加 `nan-TW → zh`（faster-whisper 只認 zh；未配置專用模型時也是最接近的退路）|
| `src/transcription/orchestrator.py` | `_resolve_punct_language` 加 `nan-TW → zh-TW`（輸出為繁體漢字，標點/繁簡下游鏈零改動沿用）|
| `src/routers/transcriptions.py` | `ALLOWED_LANGUAGES` 加 `nan-TW` |
| 前端 | TaskSettingsModal / BatchUploadModal 加選項；zh-TW/en locale 加 `langTaiwanese` |
| 測試 | `tests/unit/test_language_model_routing.py`（路由/env 解析/normalize）+ `test_orchestrator_unit.py` 補 nan-TW 案例 |

**行為備註**：worker 未設 `WHISPER_MODEL_NAN_TW` 時，台語任務安全退回 `DEFAULT_MODEL`（以 zh 解碼），不會報錯——所以程式碼可先上，模型檔後補。本地模式（DEPLOY_ENV=local，`src/main.py` 單一模型）不做路由，同樣走退回行為。

## 待決事項

1. **模型部署路徑**：轉檔後模型檔（2.9GB，現在 staging worker `~/breeze-test/breeze-asr-26-ct2/`）要放哪裡（S3 讓 worker 開機時下載，或 bake 進 worker AMI）尚未決定。**決定後才把 `WHISPER_MODEL_NAN_TW=<路徑>` 加進 `deploy/deploy-gpu-worker.sh` 的 `.env.worker` 模板**——env 要跟模型檔一起到位，只設 env 沒有檔案會讓台語任務載入失敗。
2. **台語辨識品質驗證**：staging 實測只驗了「跑得通」，未用真實台語語音驗證辨識品質；上線前建議用真實台語音檔做一輪人工聽測。

## 磁碟空間（已排查，2026-07-04）

Staging worker 根磁碟（100GB）測試後一度剩 11GB（90% used）。已排查組成並清理，目前剩 **54GB（47% used）**。

### 排查結果

- **音檔暫存清理**：不是問題。`src/transcription/audio_source.py:29-34` 的 `AudioSource.cleanup()` 有文件化合約，Orchestrator 三條 exit path（成功/取消/失敗）都會呼叫，`shutil.rmtree(ignore_errors=True)`。
- **系統套件（torch/CUDA 依賴）**：`requirements-worker.lock` 裝完整 CUDA 12.4 pip 套件（cublas/cudnn/nccl 等）+ pyannote 全家桶，這是跑 GPU 轉錄必要的重量，不可清。
- **`/usr/local/cuda-12.6 / 12.8 / 12.9 / 13.0` 四套完整 CUDA toolkit（原共 41GB）**：AWS Deep Learning AMI 內建多版本供選擇（`/usr/local/cuda` symlink 指向 12.9），**但正式服務完全不依賴系統 CUDA**——`deploy/transcriber-worker.service:23` 的 `Environment=PATH=...` 不含任何 cuda 路徑，`/etc/profile.d/dlami.sh` 設的 CUDA PATH 只在互動式登入 shell 生效，systemd 服務不會讀取。torch/ctranslate2 靠 pip 自帶的 `nvidia-cublas-cu12` 等套件自帶 CUDA runtime。已刪除 3 個非作用中版本（12.6/12.8/13.0），保留 12.9（symlink 指向的作用中版本，保守起見不動），回收 **~29GB**。**已驗證**：刪除後重啟 `transcriber-worker.service`，`whisper.model.loaded` + `diarization.model.loaded`（device: cuda）皆正常，GPU 推論不受影響。
- **HuggingFace 模型快取**：查到 staging 的 `.env.worker` 實際設定是 `WHISPER_MODEL=large-v3`（**不是** `.env.example` 文件預設的 `large-v3-turbo`——這個落差本身可能值得另外確認是否為刻意決定）。因此：
  - `models--Systran--faster-whisper-large-v3`（2.9G）是**正在使用**的快取，保留
  - `models--mobiuslabsgmbh--faster-whisper-large-v3-turbo`（1.6G）、`models--Systran--faster-whisper-medium`（1.5G）不符合目前設定，已刪除
  - `models--MediaTek-Research--Breeze-ASR-26`（5.8G）+ `~/breeze-test/breeze-src/`（5.8G）為本次測試留下的孤兒快取/中間產物（轉檔完成後即不需要），已刪除

### 未處理（不影響台語模型上線，可另外排）

- staging `WHISPER_MODEL=large-v3` vs 文件預設 `large-v3-turbo` 的落差原因未確認
- 決定 Breeze 模型正式部署後的磁碟需求（`~/breeze-test/breeze-asr-26-ct2/` 2.9G + `~/breeze-test/venv/` 5.2G 目前留在 staging worker 上，供下次測試沿用）

## 驗收方式（staging 端到端，程式碼 merge 後執行）

在 staging worker 的 `.env.worker` 加 `WHISPER_MODEL_NAN_TW=/home/ec2-user/breeze-test/breeze-asr-26-ct2`，從前端選「台語（輸出為漢字）」上傳真實台語音檔跑一個任務，確認：
1. worker log 印出 `whisper.model.loading` 且 model = breeze 路徑、language = `nan-TW`
2. 轉錄結果非空且為繁體漢字（標點/繁簡鏈走 zh-TW）
3. 開機預熱 log 只載入 `DEFAULT_MODEL`，Breeze 等首個台語任務才 lazy load
4. 對照組：一般 zh-TW 任務仍走 `DEFAULT_MODEL`，不受影響
