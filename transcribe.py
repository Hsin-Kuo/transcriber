import os
import sys
import argparse
from pathlib import Path
import whisper
from pydub import AudioSegment

# —— 可調參數 —— #
DEFAULT_MODEL = "small"          # tiny | base | small | medium
USE_WAV = True
OPENAI_MODEL = "gpt-4o-mini"     # 用來加標點（OpenAI）
GEMINI_MODEL = "gemini-1.5-flash" # 用來加標點（Gemini）


# export GOOGLE_API_KEY="AIzaSyB_neVEjgqk-8a7OL2V6DXPASnEUmpLmQI"
# python3 transcribe.py -i 574181344843137331.mp4 -m small --punct-provider gemini

# ---------- Punctuation Providers ----------

def punctuate_with_openai(text: str) -> str:
    """用 OpenAI 幫逐字稿加標點與分段"""
    from openai import OpenAI
    client = OpenAI()  # 讀 OPENAI_API_KEY
    prompt = (
        請將以下『中文逐字稿』加上適當標點符號並合理分段。"
        "不要省略或添加內容，不要意譯，保留固有名詞與數字。"
        "輸出純文字即可：\n\n"
        f"{text}"
    )
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "你是嚴謹的逐字稿潤飾助手，只做標點與分段。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

def punctuate_with_gemini(text: str) -> str:
    """用 Google Gemini 幫逐字稿加標點與分段"""
    import google.generativeai as genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("未設定 GOOGLE_API_KEY")
    genai.configure(api_key=api_key)

    system_msg = (
        "你是嚴謹的逐字稿潤飾助手。只做『中文標點補全與合理分段』，"
        "不要省略或添加內容，不要意譯，非必要不要用刪節號，保留固有名詞與數字： "
    )
    user_msg = (
        "請為以下中文逐字稿加上適當標點並分段：\n\n" + text
    )

    model = genai.GenerativeModel(GEMINI_MODEL)
    resp = model.generate_content(
        [{"role": "user", "parts": [system_msg + "\n\n" + user_msg]}],
        generation_config={"temperature": 0.2}
    )
    # 可能回傳多段，取合併純文字
    return (resp.text or "").strip()

# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(
        description="Whisper 轉逐字稿 →（OpenAI/Gemini）自動加中文標點與分段"
    )"
    parser.add_argument("-i", "--input", required=True, help="輸入音檔路徑（m4a/mp3/mp3/wav 等）")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Whisper 模型（tiny/base/small/medium/large-v2）")
    parser.add_argument("--no-wav", action="store_true", help="直接用原檔，不轉成 wav")
    parser.add_argument("--punct-provider", choices=["openai", "gemini", "none"],
                        default="openai", help="選擇加標點提供者（openai|gemini|none）")
    args = parser.parse_args()

    audio_path = Path(args.input).expanduser().resolve()
    if not audio_path.exists():
        print(f"❌ 找不到音檔：{audio_path}")
        sys.exit(1)

    raw_txt_path = audio_path.with_suffix(".raw.txt")
    pretty_txt_path = audio_path.with_suffix(".txt")

    # 若已有最終 txt，直接略過
    if pretty_txt_path.exists():
        print(f"📂 偵測到已存在帶標點逐字稿：{pretty_txt_path.name}，跳過處理。")
        return

    # 若已有 raw.txt，就直接進入標點階段
    if raw_txt_path.exists():
        print(f"📂 偵測到已存在原始逐字稿：{raw_txt_path.name}，跳過轉錄。")
        raw_text = raw_txt_path.read_text(encoding="utf-8")
    else:
        # 需要轉錄
        use_wav = not args.no_wav and USE_WAV
        to_transcribe = audio_path
        if use_wav:
            wav_path = audio_path.with_suffix(".wav")
            if wav_path.exists():
                print(f"📂 偵測到已存在 WAV 檔，直接使用：{wav_path.name}")
            else:
                print(f"🔄 轉檔為 WAV：{wav_path.name}")
                AudioSegment.from_file(audio_path).export(wav_path, format="wav")
            to_transcribe = wav_path

        print(f"🎙 載入 Whisper 模型：{args.model}")
        model = whisper.load_model(args.model)

        print(f"📝 開始轉逐字稿：{to_transcribe.name}")
        result = model.transcribe(str(to_transcribe), language="zh", fp16=False)

        raw_text = (result.get("text") or "").strip()
        raw_txt_path.write_text(raw_text, encoding="utf-8")
        print(f"✅ 已儲存原始逐字稿：{raw_txt_path.name}")

    # 是否加標點
    if args.punct_provider == "none":
        print("ℹ️ 未選擇標點提供者（--punct-provider none），僅輸出原始逐字稿。")
        return

    try:
        if args.punct_provider == "gemini":
            print("✨ 使用 Gemini 加標點與分段 ...")
            pretty = punctuate_with_gemini(raw_text)
        else:
            # 預設 openai
            if not os.getenv("OPENAI_API_KEY"):
                print("⚠️ 未設定 OPENAI_API_KEY，無法使用 OpenAI 標點。你可改用 --punct-provider gemini。")
                return
            print("✨ 使用 OpenAI 加標點與分段 ...")
            pretty = punctuate_with_openai(raw_text)

        pretty_txt_path.write_text(pretty, encoding="utf-8")
        print(f"🎉 已輸出帶標點逐字稿：{pretty_txt_path.name}")
    except Exception as e:
        print(f"⚠️ 加標點失敗（{e}），已保留原始逐字稿：{raw_txt_path.name}")

if __name__ == "__main__":
    main()
