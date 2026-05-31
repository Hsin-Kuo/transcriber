# Post-mortem: Multi-worker enablement incident

> Date: 2026-05-30
> Severity: Sev-3（partial production outage, ~5 分鐘）
> Author: 重構過程中的紀錄

---

## TL;DR

啟用 `uvicorn --workers 2` 時兩度導致 production 502。每次都是 ~5 分鐘內手動 SSH 救回。Root cause 是兩個獨立 bug 疊加：
1. `cleanup_worker_processes()` 在 worker startup 跑 `pkill -9 multiprocessing.resource_tracker` → multi-worker 下殺 sibling worker
2. `ExecStartPre` 寫成 inline `sh -c '...pkill -f multiprocessing.spawn...'` → sh 進程 cmdline 含 pattern → pkill 把 parent shell 自殺

兩個都已修，systemd unit 改 repo-as-source、deploy 流程加 `is-active --quiet` 防 silent fail。

---

## Timeline（UTC）

| 時間 | 事件 |
|------|------|
| 08:28 | 第一次手動 sed 改 systemd unit 加 `--workers 2`，restart 後立刻 crash loop |
| 08:30 | 觀察到 worker 進入 defunct，立即 sed revert，prod 恢復 |
| ~12:00 | 程式碼修正：startup cleanup 改 systemd `ExecStartPre`，PR #54 merge + deploy |
| 14:30 | PR #54 deploy 失敗，prod 502 |
| 14:35 | SSH 確認 ExecStartPre 自殺，手動 sed revert，prod 恢復 |
| 14:40 | PR #55 修 ExecStartPre 改獨立 script + deploy-aws.yml 加 `is-active` 檢查 |
| 14:50 | PR #55 deploy 成功，multi-worker 真正運作 |
| 14:55 | 確認 1 master + 2 worker + resource_tracker，無 defunct |

---

## Root cause 1: worker startup pkill self-kill

`src/main.py` 原本有 `cleanup_worker_processes()`：
```python
def cleanup_worker_processes():
    subprocess.run(["pkill", "-9", "-f", "multiprocessing.spawn"])
    subprocess.run(["pkill", "-9", "-f", "multiprocessing.resource_tracker"])
```
這在 app startup hook 內被呼叫（line 222 原版）。**單 worker 模式無感**：機器上沒別人在跑 multiprocessing，pkill 沒目標。

**多 worker 下**：uvicorn `--workers 2` 用 Python multiprocessing fork workers。每個 worker 自己有 `multiprocessing.resource_tracker` 子進程。Worker A 跑 startup → `pkill` 殺**所有** worker 的 resource_tracker → workers 失去 tracker 立刻 die → master 重 spawn → 重複死循環。

**修法**：把 cleanup 移到 systemd `ExecStartPre`，只在 master 啟動「前」跑一次，跟 multi-worker 天然兼容。

---

## Root cause 2: ExecStartPre pkill 自殺

第一次修法寫成 inline：
```
ExecStartPre=/usr/bin/sh -c 'pkill -9 -f multiprocessing.spawn || true; pkill -9 -f multiprocessing.resource_tracker || true'
```

systemctl 看到：
```
Process: ExecStartPre=/usr/bin/sh -c pkill -9 -f multiprocessing.spawn ...
(code=killed, signal=KILL)
```

`pkill -f` 掃所有 process 的 cmdline 找 pattern。**那個 sh 進程的 cmdline 含字串 `multiprocessing.spawn`**（pattern 寫在 `-c` 參數內，會出現在 `/proc/<sh_pid>/cmdline`）。`pkill` 把自己的 parent shell 殺了。`pkill` 本身有 self-protect 不會殺自己，但 sh 沒有。

**修法**：抽 standalone script `deploy/pre-start-cleanup.sh`，bash 跑這個檔的 cmdline 是 `/bin/bash /opt/.../pre-start-cleanup.sh`，不含 pattern → 不會自殺。

---

## 為什麼 deploy 沒攔下來

PR #54 deploy 是這樣：
1. SCP 新 code 到 EC2 ✓
2. `pip install` ✓
3. `nginx -t && reload nginx` ✓
4. `cp transcriber.service /etc/systemd/system/` ✓
5. `systemd-analyze verify` ✓（語法正確）
6. `systemctl daemon-reload` ✓
7. `systemctl restart transcriber` ✓ exit 0
8. `curl /health` ✗ 失敗（這時才發現）

問題在 step 7：**`systemctl restart` 本身會 exit 0**，因為 systemd 把「啟動命令收到」當成功。restart 跑完後 service 進入 auto-restart 死循環，但 systemctl 已經回來了。

PR #55 補上：
```
sleep 3
sudo systemctl is-active --quiet transcriber || {
    echo "[ERROR] not active"
    sudo systemctl status transcriber --no-pager | head -30
    sudo journalctl -u transcriber -n 30 --no-pager
    exit 1
}
```
3 秒後驗證 active，沒 active 就 dump status + journal 然後讓 workflow fail。

---

## Lessons learned

### 1. `systemctl restart` exit 0 ≠ service 活著
任何 systemd 操作都要加 `is-active --quiet` 二次驗證。已加進 `deploy-aws.yml`。

### 2. `pkill -f` 在 inline `sh -c` 內會自殺
Pattern 出現在 shell 的 argv 裡，pkill 把 shell 一起殺。**永遠用 standalone script 包 pkill**。

### 3. systemd unit 應該 repo-as-source
過去手動 SSH 改 unit、deploy 不同步 unit，造成 EC2 上 unit 跟 repo drift。修法：
- systemd unit 抽成 `deploy/transcriber.service` canonical 檔
- `deploy-aws.yml` 每次 deploy 都 `cp` 過去 + `daemon-reload`
- 之後想改 unit，改 repo 檔 + PR + push aws

### 4. Worker startup hook 不該跑「機器全域」操作
任何在 worker startup 內呼叫的全域操作（pkill、清檔、port bind）都會被多 worker 各跑一份。把這類操作移到 master 範圍（systemd ExecStartPre、或 main process 前置 entry script）。

### 5. Branch protection 的價值
事件中我用 admin bypass 把幾個 commit 直接推到 `aws`（緊急救援）。事後檢視，bypass 紀錄完整留在 GitHub security log，可追溯。沒有 branch protection 的話，慌亂中可能弄掉更多東西。

---

## Action items（已完成 ✅）

- [x] PR #54: systemd unit 改 repo-as-source + `ExecStartPre`
- [x] PR #55: ExecStartPre 改獨立 script + `deploy-aws.yml` 加 `is-active` 檢查
- [x] PR #56: 每個 repo `create_indexes()` 獨立 try/except（為了讓 chunk_uploads index 不被前面的 user_repo email drift 連坐）
- [x] CONTRIBUTING.md 文件化「禁 SSH 改 systemd unit」規則
- [x] Atlas: drop `email_1`（drift 修完）

## Action items（待辦）

- [ ] Deploy 失敗時自動 restore 舊 systemd unit（縮 MTTR）— 目前只是 fail loud
- [ ] `_loop_tick_monitor` sleep 改 100ms 給更精細 stall 偵測（目前 1s → stall 觀測值在 0-1s 鋸齒，看不到小停頓）
- [ ] CloudWatch alarm 監控 `loop_stall_seconds`、`CPUCreditBalance`、memory
