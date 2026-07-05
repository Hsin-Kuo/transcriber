# 給未來 session 的信

> 寫於 2026-07-04，Fable 5 的唯一一次 session。之後的你是 Sonnet / Opus / Haiku。
> 這封信講三件使用者沒問、但我認為對這個環境最重要的事，以及這套制度會怎麼壞掉。

---

## 0. 本次 session 的假設（使用者未拍板，如有異議請他直說）

- 制度檔放在 repo 的 `.claude/docs/`（會被 git 追蹤；好處是 CLAUDE.md 的相對路徑引用永遠有效、換機器不丟）。**尚未 commit**——要不要 commit、要不要進 PR，由使用者決定。
- 舊版 CLAUDE.md / MEMORY.md 備份在 `.claude/docs/backups/`。
- 語言沿用「繁中 + 英文技術詞」。

## 1. 三件最重要的事

### ① Memory 漂移是這個環境的頭號隱形殺手（有實證）

2026-07-04 盤點時，memory 裡三筆「已實作未 push」的工作（onboarding-tour、task-settings-modal、pro-priority-queue）**實際上早已合併**（PR #169 / #207 / #166）。這不是個案，是結構性問題：這個專案迭代快、單人維運、session 之間只靠 memory 接力。所以：
- **引用 memory 前先驗證**（judgment-rubrics.md §6），驗證失敗就當場更新該 memory 檔——這是義務。
- **session 收尾**：有未完成工作，落檔 memory 時必附「一條可驗證現況的指令」。
- 不確定專案現在到哪了？`git log --oneline -15` 比任何 memory 都新鮮。

### ② 歷史決策有血淚，推翻前先查為什麼

這個 repo 有幾條看起來「可以優化」的怪規則，全是事故換來的，**不要好心去修**：
- **只用 merge commit（禁 squash/rebase）**：squash 曾斷掉三層分支的 lineage（issue #151），導致 2026-06 兩次 force-reset 收斂。
- **三層分支 feature→main→staging→aws + Promotion Guard**：prod 曾落後 44 個 PR 加分歧，就是繞過這個流程的後果。
- **free tier 刻意開放說話者辨識**：不是 bug，是產品決策，別「修」回 False。
- **EC2 上的 systemd/nginx/.env 全部 sync from repo**：SSH 手改造成過 drift，禁止。
通則：想改一條奇怪的既有規則時，先搜 memory 和 `docs/`（含 postmortem），找到原因再提議，找不到就問使用者。

### ③ 資安主動性是使用者明示的偏好，別讓它失傳

使用者（資安背景）明確要求：看到資安風險就主動講，順手能修就一起修。已知未處理項在 memory `project_prod_findings.md`（admin 弱密碼、Sentry 未啟用等）。凡 diff 碰到 auth/payment/IAM/webhook，走 judgment-rubrics.md §5 第 4 條的高風險驗收。這是這個環境裡「多做會被感謝」的少數安全方向。

## 2. 這套制度最可能的退化方式（與預防）

1. **路由表沒被讀**——session 直接開工，制度檔形同虛設。預防：CLAUDE.md 把紀律放最前面；使用者若發現 session 行為走樣，說一句「讀路由表」即可矯正。
2. **例外慢慢架空規則**——每次都「這次情況特殊」。預防：maintenance-protocol.md §2 規定例外必須明說；同類例外第二次出現就得提議修規則。
3. **制度檔膨脹到沒人讀**——教訓越記越多，變成第二個要瘦身的 CLAUDE.md。預防：§4 行數上限與精簡義務。
4. **文件與現實漂移**——工具 schema 變了、模型名單變了，文件還在講舊的。預防：maintenance-protocol.md §5「以現實為準 + 當場修文件」；環境事實都標了盤點日期，過期就重驗。

## 3. 誠實條款：這套制度補不了什麼

- **模糊題與品味**（產品方向、UX 文案、架構長期取捨）：rubric 只能逼你「給選項問使用者」，不能替你長出品味。遇到就照 judgment-rubrics.md §3/§7 辦，不要硬答。
- **真正的難 bug**：升級到 opus + 完整失敗軌跡是上限；如果 opus 也兩輪不行，誠實告訴使用者「這題超出目前配置」，附上已排除的假設清單，比假裝有進展有價值。
- 本制度所有機制（委派、read-back、多答案評審、完成階梯）都只需要 Sonnet 等級就能執行——這是設計目標，我沒有依賴任何 Fable 專屬能力。

## 4. 交接區（本次 session 未完成項目）

- 制度檔已 commit 於分支 `docs/claude-agent-institution` 並開 PR（2026-07-05），merge 由使用者決定。驗證：`gh pr list --head docs/claude-agent-institution`。merged 後本條目可刪。
- `.claude/docs/backups/` 是本地安全副本，已加入 `.gitignore` 不進 repo。
