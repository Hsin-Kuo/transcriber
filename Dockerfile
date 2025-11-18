# Whisper 轉錄服務 - Docker 映像
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# 複製 requirements.txt 並安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式檔案
COPY src/ ./src/

# 建立模型快取目錄（避免每次啟動都重新下載）
RUN mkdir -p /root/.cache/whisper

# 預先下載 Whisper 模型（可選，可加快首次啟動）
# RUN python -c "import whisper; whisper.load_model('medium')"

# 暴露端口
EXPOSE 8000

# 設定環境變數
ENV PYTHONUNBUFFERED=1

# 啟動服務
# 預設使用 medium 模型，可透過環境變數覆蓋
CMD ["python", "src/whisper_server.py", "--host", "0.0.0.0", "--port", "8000", "--model", "medium"]
