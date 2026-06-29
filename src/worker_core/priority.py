"""優先佇列的取用順序決策（純函數，無副作用，可單元測試）。

兩條實體 SQS 佇列：priority（pro+enterprise）與 normal（其餘）。
worker 一次只處理一顆任務；本模組決定「這一輪先抽哪條」與「抽完後 streak 怎麼變」，
達成「優先但防餓死」的 N:1 比例：

- streak < ratio  → 先抽 priority，空了再抽 normal（偏好優先）
- streak >= ratio → 先抽 normal，空了再抽 priority（保留給一般佇列的時隙）
                    且**無論這一輪抽到哪條，streak 一律歸 0**——
                    保證每處理 ratio 顆 priority 就一定有一個「讓 normal 先選」的時隙，
                    一般任務等待上界 = 最多 ratio 顆 priority 的處理時間。

streak 只在 worker 記憶體（state）中維護，重啟歸零（短暫偏好優先，無害）。
"""

PRIORITY = "priority"
NORMAL = "normal"


def poll_order(streak: int, ratio: int) -> tuple:
    """回傳這一輪的 (第一順位, 第二順位, 強制歸零旗標)。

    第一順位用 short-poll（WaitTimeSeconds=0）快速探，沒有再對第二順位 long-poll。
    reset_after=True 代表本輪屬「讓 normal 先選」的時隙，處理後 streak 必須歸 0。
    """
    if ratio >= 1 and streak >= ratio:
        return (NORMAL, PRIORITY, True)
    return (PRIORITY, NORMAL, False)


def build_poll_sequence(first: str, second: str, available, long_poll_seconds: int) -> list:
    """把 (first, second) 偏好順序 + 已配置佇列，組成 [(name, wait_seconds), ...]。

    略過未配置的佇列；除最後一條外都用 short-poll(0s)，最後一條用 long-poll，
    讓「所有佇列皆空」的這一輪被 long-poll 自然 pacing（不 busy-spin）。
    只有單一佇列時 → 單條 long-poll，行為與舊版單佇列 worker 一致。
    """
    seq = [name for name in (first, second) if name in available]
    return [
        (name, long_poll_seconds if i == len(seq) - 1 else 0)
        for i, name in enumerate(seq)
    ]


def next_streak(streak: int, reset_after: bool, processed_from: str) -> int:
    """依本輪結果更新 streak。

    - reset_after（normal-first 時隙）：一律歸 0
    - 抽到 priority：streak + 1
    - 抽到 normal：歸 0
    """
    if reset_after:
        return 0
    if processed_from == PRIORITY:
        return streak + 1
    return 0
