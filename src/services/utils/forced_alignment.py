"""TimestampRefiner — 用強制對齊修正語者交界處的 word 時間戳。

背景（2026-09-21 POC，見 memory word-level-diarization）：whisper decoder 的
word start 系統性前漂（實測中位 0.15-0.19s、P90 0.4-0.5s、29-45% 的字 >0.2s），
交界字因此被指派給前一位講者（「会」「因为」案）。torchaudio 內建 MMS_FA
（1.2GB、zero 新增 torch 依賴）+ uroman 中文羅馬化可精確重算：POC 兩個
ground-truth 字都修正落進正確 turn。

設計：
- 只做「定向交界窗」對齊：語者交界 ±REFINE_WINDOW_PAD_SEC 的窗（POC 全檔
  對齊 ~2-3 分鐘，交界窗省 ~10x）。
- 保守合併：|位移| > REFINE_MAX_SHIFT_SEC 時放棄該字（防對齊自身出錯爆走）、
  修正後強制單調（不得穿越鄰字）。
- 任何失敗回傳原 segments——本步驟是精修，不可影響轉錄主流程。
- 模型 lazy load、CUDA-only（CPU 太慢、MPS 未驗證）；uroman 需 Python 3.10+
  （本地 dev venv 3.9 → 不可在 module level import）。
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

log = get_logger(__name__)

# 交界窗：語者變換點前後各取這麼多秒
REFINE_WINDOW_PAD_SEC = 2.0
# 相鄰窗間距小於此值就合併成一個窗（減少模型呼叫次數）
REFINE_WINDOW_MERGE_GAP_SEC = 1.0
# 單字位移超過此值視為對齊不可信，保留 whisper 原值
REFINE_MAX_SHIFT_SEC = 1.0


def speaker_change_windows(
    diar_turns: List[Dict],
    pad: float = REFINE_WINDOW_PAD_SEC,
    merge_gap: float = REFINE_WINDOW_MERGE_GAP_SEC,
) -> List[Tuple[float, float]]:
    """從 diar turns 找出「語者變換點」並展開成合併後的時間窗。

    變換點 = 排序後相鄰 turn 的交接（不同語者），取兩 turn 的邊界時刻；
    巢狀插話（短 turn 疊在長 turn 內）的 start 與 end 都是變換點。
    """
    if len(diar_turns) < 2:
        return []
    turns = sorted(diar_turns, key=lambda t: (t["start"], t["end"]))
    points: List[float] = []
    # 不用 zip(strict=)：本地 dev venv 仍是 3.9（strict= 需 3.10+），與 repo 慣例一致
    for i in range(1, len(turns)):
        prev, cur = turns[i - 1], turns[i]
        if prev["speaker"] != cur["speaker"]:
            points.append(cur["start"])
            points.append(min(prev["end"], cur["end"]))
    if not points:
        return []
    points.sort()
    windows: List[List[float]] = []
    for p in points:
        a, b = p - pad, p + pad
        if windows and a - windows[-1][1] <= merge_gap:
            windows[-1][1] = max(windows[-1][1], b)
        else:
            windows.append([a, b])
    return [(max(0.0, a), b) for a, b in windows]


def apply_refined_times(
    words: List[Dict],
    refined: List[Optional[Tuple[float, float]]],
    max_shift: float = REFINE_MAX_SHIFT_SEC,
) -> int:
    """把對齊結果保守地寫回 words（就地修改），回傳實際修正的字數。

    守門：|start 位移| > max_shift 或新時間非正長度 → 放棄該字；
    寫回後強制不早於前一字的 start（保序，容許相接）。
    """
    applied = 0
    prev_start = 0.0
    for idx, w in enumerate(words):
        r = refined[idx] if idx < len(refined) else None
        if r is not None:
            new_start, new_end = r
            if (
                abs(new_start - w["start"]) <= max_shift
                and new_end > new_start
            ):
                w["start"] = max(round(new_start, 3), prev_start)
                w["end"] = max(round(new_end, 3), w["start"] + 0.01)
                applied += 1
        prev_start = w["start"]
    return applied


class TimestampRefiner:
    """MMS_FA 強制對齊器（worker 端 CUDA 單例；載入失敗即永久停用）。"""

    def __init__(self):
        self._bundle = None
        self._model = None
        self._dict = None
        self._uroman = None
        self._disabled = False

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._disabled:
            return False
        try:
            import torch
            import torchaudio
            import uroman as ur

            if not torch.cuda.is_available():
                raise RuntimeError("timestamp refine 需要 CUDA")
            self._bundle = torchaudio.pipelines.MMS_FA
            self._model = self._bundle.get_model(with_star=False).to("cuda")
            self._dict = self._bundle.get_dict(star=None)
            self._uroman = ur.Uroman()
            log.info("timestamp_refine.model.loaded")
            return True
        except Exception as e:
            self._disabled = True
            log.warning("timestamp_refine.unavailable", error=str(e))
            return False

    def refine_segments(
        self, wav_path: Path, segments: List[Dict], diar_turns: List[Dict]
    ) -> Dict[str, int]:
        """就地精修 segments[].words 在語者交界窗內的時間戳。

        回傳統計 {"windows": n, "words_considered": n, "words_refined": n}
        供呼叫端 log；失敗回零統計、segments 不動。
        """
        stats = {"windows": 0, "words_considered": 0, "words_refined": 0}
        try:
            if not self._ensure_loaded():
                return stats
            windows = speaker_change_windows(diar_turns)
            if not windows:
                return stats
            import soundfile as sf

            data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
            if sr != 16000:
                log.warning("timestamp_refine.skip", reason=f"sr={sr}!=16000")
                return stats
            all_words = [
                w
                for seg in segments
                for w in (seg.get("words") or [])
            ]
            all_words.sort(key=lambda w: w["start"])
            stats["windows"] = len(windows)
            for a, b in windows:
                in_win = [
                    w for w in all_words if w["start"] >= a and w["end"] <= b
                ]
                if len(in_win) < 2:
                    continue
                stats["words_considered"] += len(in_win)
                refined = self._align_window(data, a, b, in_win)
                stats["words_refined"] += apply_refined_times(in_win, refined)
            if stats["words_refined"]:
                log.info("timestamp_refine.applied", **stats)
        except Exception as e:
            log.warning("timestamp_refine.failed", error=str(e))
        return stats

    def _align_window(
        self, data, a: float, b: float, words: List[Dict]
    ) -> List[Optional[Tuple[float, float]]]:
        """對單一窗做強制對齊，回傳與 words 等長的 (start,end)|None 列表。"""
        import re

        import torch
        from torchaudio.functional import forced_align, merge_tokens

        wave = torch.from_numpy(
            data[int(a * 16000):int(b * 16000)].T
        ).to("cuda")
        tokenized: List[int] = []
        spans: List[Optional[Tuple[int, int]]] = []
        for w in words:
            content = re.sub(r"[^\w]", "", w["word"], flags=re.UNICODE)
            roman = re.sub(
                r"[^a-z]", "", str(self._uroman.romanize_string(content)).lower()
            )
            ids = [self._dict[c] for c in roman if c in self._dict]
            if not ids:
                spans.append(None)
                continue
            spans.append((len(tokenized), len(tokenized) + len(ids)))
            tokenized.extend(ids)
        if not tokenized:
            return [None] * len(words)
        with torch.inference_mode():
            emission, _ = self._model(wave)
            targets = torch.tensor([tokenized], dtype=torch.int32, device="cuda")
            aligned, scores = forced_align(emission, targets, blank=0)
        token_spans = merge_tokens(aligned[0], scores[0].exp())
        frame_dur = (b - a) / emission.size(1)
        out: List[Optional[Tuple[float, float]]] = []
        for span in spans:
            if span is None:
                out.append(None)
                continue
            toks = token_spans[span[0]:span[1]]
            if not toks:
                out.append(None)
                continue
            out.append(
                (a + toks[0].start * frame_dur, a + toks[-1].end * frame_dur)
            )
        return out
