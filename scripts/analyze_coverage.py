"""一次性分析:比對最近數筆 task 的「音檔長度 vs segments 實際覆蓋總長」。

用途:量 batched 相對 sequential 的掉段比例 f。在 GPU worker 上跑
(staging Atlas 需 IP allowlist + 走 SSM 拿連線字串)。

  cd /opt/transcriber
  set -a; source <(sudo cat /opt/transcriber/.env.worker); set +a
  python3.12 /tmp/analyze_coverage.py
"""
import datetime
from src.database.sync_client import get_sync_db


def union_duration(segs):
    """segments 的 [start,end] 聯集總長(合併重疊),代表實際覆蓋到的音訊秒數。"""
    iv = sorted(
        (float(s["start"]), float(s["end"]))
        for s in segs
        if s.get("start") is not None
        and s.get("end") is not None
        and float(s["end"]) > float(s["start"])
    )
    if not iv:
        return 0.0
    total = 0.0
    cs, ce = iv[0]
    for s, e in iv[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            total += ce - cs
            cs, ce = s, e
    total += ce - cs
    return total


def dump_schema(db):
    """印出最新 3 筆 task 的原始欄位(截斷長值)+ segments 文件的 metadata,
    用來確認真實欄位名(音檔長度 / 時間 / 模型設定 / 檔名)。"""
    print("=" * 70)
    print("SCHEMA DUMP — 最新 3 筆 task 原始欄位")
    print("=" * 70)
    for t in db.tasks.find().sort("_id", -1).limit(3):
        print("\n--- task ---")
        for k, v in t.items():
            sv = str(v)
            if len(sv) > 80:
                sv = sv[:80] + "…"
            print(f"  {k}: {sv}")
        tid = t.get("_id") or t.get("task_id")
        sd = db.segments.find_one({"_id": tid})
        if sd:
            print("  [segments doc keys]:", list(sd.keys()))
            segs = sd.get("segments", [])
            if segs:
                print("  [segment[0]]:", {k: segs[0].get(k) for k in list(segs[0].keys())[:6]})
    print("=" * 70)
    print()


def _dur(t):
    return (t.get("stats") or {}).get("audio_duration_seconds") or 0.0


def _created(t):
    return (t.get("timestamps") or {}).get("created_at")


def _fname(t):
    return (t.get("file") or {}).get("filename") or ""


def main():
    db = get_sync_db()
    print(f"DB = {db.name}\n")
    tasks = list(db.tasks.find().sort("timestamps.created_at", -1).limit(15))
    hdr = f"{'created(UTC)':<13}{'audio_s':>9}{'cover_s':>9}{'cover%':>8}{'segs':>6}  {'custom_name / filename'}"
    print(hdr)
    print("-" * 90)
    for t in tasks:
        tid = t.get("_id") or t.get("task_id")
        sd = db.segments.find_one({"_id": tid})
        segs = sd.get("segments", []) if sd else []
        cov = union_duration(segs)
        aud = _dur(t)
        pct = (cov / aud * 100) if aud else 0.0
        ca = _created(t)
        try:
            cas = datetime.datetime.utcfromtimestamp(int(ca)).strftime("%m-%d %H:%M")
        except Exception:
            cas = str(ca)[:13]
        label = t.get("custom_name") or _fname(t)
        label = str(label)[:40]
        print(f"{cas:<13}{aud:>9.1f}{cov:>9.1f}{pct:>7.1f}%{len(segs):>6}  {label}")

    compare_batched_vs_sequential(db)


def _merge(segs):
    iv = sorted(
        (float(s["start"]), float(s["end"]))
        for s in segs
        if s.get("start") is not None and s.get("end") is not None
        and float(s["end"]) > float(s["start"])
    )
    out = []
    for s, e in iv:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _total(iv):
    return sum(e - s for s, e in iv)


def _subtract(A, B):
    """A 區間扣掉 B 區間(兩者皆已 merge 排序)→ A 有、B 沒有的部分。"""
    res = []
    for s, e in A:
        cur = s
        for bs, be in B:
            if be <= cur:
                continue
            if bs >= e:
                break
            if bs > cur:
                res.append((cur, min(bs, e)))
            cur = max(cur, be)
            if cur >= e:
                break
        if cur < e:
            res.append((cur, e))
    return res


def _find_by_label(db, substr):
    for t in db.tasks.find().sort("timestamps.created_at", -1).limit(40):
        if substr.lower() in str(t.get("custom_name", "")).lower():
            return t
    return None


def _segs_of(db, t):
    sd = db.segments.find_one({"_id": t.get("_id") or t.get("task_id")})
    return sd.get("segments", []) if sd else []


def compare_batched_vs_sequential(db):
    bat = _find_by_label(db, "batched")
    seq = _find_by_label(db, "sequen")
    print("\n" + "=" * 70)
    print("差集分析:sequential vs batched(同檔配對)")
    print("=" * 70)
    if not bat or not seq:
        print("找不到配對(batched / sequential custom_name)")
        return
    print(f"batched   : {bat.get('custom_name')}  (audio {_dur(bat):.1f}s)")
    print(f"sequential: {seq.get('custom_name')}  (audio {_dur(seq):.1f}s)")
    B = _merge(_segs_of(db, bat))
    S = _merge(_segs_of(db, seq))
    seq_only = _subtract(S, B)   # sequential 有、batched 沒有 → batched 漏掉的
    bat_only = _subtract(B, S)   # batched 有、sequential 沒有
    aud = _dur(seq) or 1.0
    print(f"\n  batched 覆蓋    : {_total(B):8.1f}s")
    print(f"  sequential 覆蓋 : {_total(S):8.1f}s")
    print(f"  交集(都有)     : {_total(_subtract(S, _subtract(S, B))):8.1f}s")
    print(f"  ▶ seq 有但 batched 漏(hybrid 可補的量): {_total(seq_only):8.1f}s  = 音檔 {_total(seq_only)/aud*100:.1f}%")
    print(f"  ▷ batched 有但 seq 沒有             : {_total(bat_only):8.1f}s  = 音檔 {_total(bat_only)/aud*100:.1f}%")
    # 列出 batched 漏掉的較大區段(>3s),這些就是你會看到的「掉段」
    big = [(s, e) for s, e in seq_only if e - s >= 3.0]
    big.sort(key=lambda x: x[1] - x[0], reverse=True)
    print(f"\n  batched 漏掉的較大區段(>3s,共 {len(big)} 段,列前 10):")
    for s, e in big[:10]:
        print(f"    {s:7.1f}–{e:7.1f}s  ({e - s:.1f}s)")

    # 放大檢視 298–311s 缺口:兩次轉錄在 290–320s 窗口的逐段文字
    _dump_window(db, seq, bat, 290.0, 320.0)


def _segs_in_window(segs, lo, hi):
    out = []
    for s in segs:
        st, en = float(s.get("start", 0)), float(s.get("end", 0))
        if en > lo and st < hi:
            out.append((st, en, str(s.get("text", "")), s.get("speaker")))
    out.sort()
    return out


def _dump_window(db, seq, bat, lo, hi):
    print("\n" + "=" * 70)
    print(f"放大檢視:{lo:.0f}–{hi:.0f}s 窗口的逐段文字")
    print("=" * 70)
    for name, t in (("SEQUENTIAL", seq), ("BATCHED", bat)):
        print(f"\n--- {name} ---")
        rows = _segs_in_window(_segs_of(db, t), lo, hi)
        if not rows:
            print("  (此窗口無 segment)")
        for st, en, txt, spk in rows:
            sp = f"[{spk}] " if spk else ""
            print(f"  {st:7.1f}–{en:7.1f}  {sp}{txt[:60]}")


if __name__ == "__main__":
    main()
