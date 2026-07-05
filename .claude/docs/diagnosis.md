# Harness 診斷報告（2026-07-04，由 Fable 5 撰寫）

> 本檔是後面所有制度檔的依據。三個問題按傷害排序，每個附具體證據與修法。
> 修法落地位置：CLAUDE.md（路由）、model-dispatch.md、judgment-rubrics.md、maintenance-protocol.md。

---

## 問題 #1：每個 session 的固定 context 稅——重複、過時、互相矛盾的常駐文件

**現象**：CLAUDE.md（239 行）+ MEMORY.md（166 行）每個 session 全量載入，約 5k tokens，其中大量內容重複或已過時。

**具體證據（2026-07-04 盤點）**：
- 「安全措施」清單在 CLAUDE.md 和 MEMORY.md 各出現一次，逐字幾乎相同。
- AWS 資源表、部署指令、費用估算在兩邊重複；MEMORY.md 塞了大段 inline 內容（AWS 部署狀態、架構設計節），違反它自己開頭定義的「index only」規則。
- MEMORYの「待完成」checklist 全部已勾選——純死重量。
- 表述矛盾：CLAUDE.md 寫「GPU Worker 空閒 5 分鐘後自行呼叫 shutdown（無 Lambda）」，MEMORY.md 寫「Lambda 啟動 GPU」。兩者其實相容（Lambda 負責**啟動**、worker 自己負責**關機**），但弱模型讀到「無 Lambda」很容易誤判成整條鏈路沒有 Lambda。
- **Memory 與現實漂移（最危險）**：memory 記載 `feat/onboarding-tour`、`feat/task-settings-modal`、`feat/pro-priority-queue`「已實作未 push/未 PR」，但 git 顯示三者分別已在 PR #169、#207、#166 合併，本地分支只剩 `aws/main/staging`。弱模型若照 memory 行動，會去找不存在的分支、或重做已完成的工作。

**傷害**：開場就燒 token 是小事；大事是弱模型分不出「現況」和「歷史」，會把過時敘述當作待辦去執行。

**修法（已在本次 session 執行）**：
1. CLAUDE.md 重寫成「精簡事實 + 路由表」（見新版 CLAUDE.md）。
2. MEMORY.md 瘦身回純 index；AWS 資源表移入獨立 memory 檔。
3. 過時的三筆分支 memory 更新為「已合併」。
4. 立規則（judgment-rubrics.md §6）：**引用 memory 中的 branch / 檔案 / 資源 ID 前，先用一條指令驗證它存在**（`git branch -a | grep X`、`ls`），驗不到就把 memory 當歷史線索而非現況。

---

## 問題 #2：主模型下場做粗活——context 汙染導致中途摘要失憶

**現象**：主對話直接 grep / Read 十幾個檔案、貼整段 log（repo 根目錄的 backend.log 有 343KB）、跑輸出上百行的指令。這些原始內容全部進入主對話 context，長 session 觸發自動摘要（summarization）時，**最先被壓掉的是開場的使用者決策與驗收條件**，導致後半段 session 忘記目標、重問已答過的問題、或偏離已定案的方案。

**傷害鏈**：粗活進主對話 → context 膨脹 → 中途摘要 → 早期決策遺失 → 後半段品質崩、來回返工 → 燒掉的 token 反而更多。

**修法（落地於 model-dispatch.md）**：
- 硬判準：**預估要讀 >3 個檔案、或指令輸出 >200 行、或任何「掃 repo 找 X」** → 一律派 Explore/general-purpose agent，主對話只收「結論 + `檔案:行號`」。
- 回報合約：subagent 禁止回貼大段原始碼；長產物落檔、回傳路徑。
- log 分析：先 `grep -c` 估行數，超標就 `tail`/`grep` 取窗口或派 agent，禁止整檔 Read 進主對話。

---

## 問題 #3：「完成」定義鬆散 + 自我驗證

**現象**：
- 工作經常停在中間態（實作了沒 commit、commit 了沒 PR、merge 了沒 deploy），且狀態只記在 memory 的一句話裡，下個 session 無法可靠接手（見問題 #1 的漂移實證——同一批 memory 三筆全部過期）。
- 弱模型傾向「改完就宣告完成」：沒跑測試、沒實跑 smoke、自己寫的東西自己讀一遍就當驗證。

**傷害**：使用者拿到「說完成但沒完成」的回報，信任成本最高的錯誤型態。

**修法（落地於 judgment-rubrics.md §2/§8、model-dispatch.md §7）**：
1. **完成階梯**：任何工作回報必須標註停在哪一階——
   `設計定案 → 實作完 → 單元測試過 → 實機 smoke 過 → commit → PR 開了 → merged → deployed`。
   「完成」只能指使用者要求的那一階；沒到就寫「停在第 N 階，下一步是 X」。
2. **驗證不自驗**：驗收一律派 fresh-context agent——檔案用 read-back 核對驗收條件、程式碼用測試或 /verify 實跑、高風險判斷加第二意見。
3. **session 收尾義務**：有未完成工作就必須在結束前寫 memory，格式含：分支名、停在階梯第幾階、一條可驗證現況的指令。正式規則見 judgment-rubrics.md §8。
