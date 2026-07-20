# 帳號刪除的資料處理決策（GDPR × 統計一致性 × 儲存）

> 狀態：Accepted（2026-07-20）
> 影響路徑：`DELETE /api/auth/account`（高風險，動到 auth + 資料刪除 + 合規）
> 相關程式：`src/routers/auth.py:delete_account`、`src/database/repositories/task_repo.py`、
> `src/services/admin_analytics.py`、`src/utils/user_display.py`

## 背景與目標

使用者刪除帳號時，需同時滿足三個常互相拉扯的需求：

1. **GDPR / 個資法**：刪除權（right to erasure）——個人資料必須被清除。
2. **用量統計與歷史查詢一致性**：過往月份的統計、AI 成本、任務數不應因某帳號刪除而憑空下降。
3. **不留無謂儲存**：不需要的東西（尤其大檔）就不要留。

三者看似衝突，實際上**同向**：體積大又屬個資的「內容」剛好該刪（同時滿足 1 + 3）；
體積小又非個資的「統計 metric」剛好該留（滿足 2）。本文件把這條界線定死。

## 決策原則：三軸分類

對每筆與任務相關的資料問三個問題：**(A) 是否個資？(B) 統計/歷史是否需要？(C) 是否佔可觀儲存？**

| 資料 | (A) 個資 | (B) 統計需要 | (C) 儲存 | 處置 |
|------|:--:|:--:|:--:|------|
| 音檔（原始語音，高敏感個資） | 是 | ✗ | 大 | **硬刪** |
| `transcriptions` / `segments`（逐字內容） | 是 | ✗ | 中大 | **硬刪** |
| `summaries`（摘要全文） | 是 | ✗ | 中 | **硬刪** |
| task `user.user_email` / `custom_name` / `file.filename` / `tags` | 是 | ✗ | 微 | **清空（null/[]）** |
| task `status` / `task_type` / `models` / `stats` / `timestamps` / `result.text_length`·`word_count` | 否* | ✓ | 微 | **保留（匿名化）** |
| task `user.user_id`（假名鍵） | 假名 | ✓ | 微 | **保留** |
| `summary_logs`（model / token / duration，無內容） | 假名 | ✓ | 小 | **保留** |
| `orders`（金流紀錄） | 是 | ✓ | 小 | **保留（稅務法定義務，GDPR Art.17(3)(b)）** |

\* 識別欄位（email/自訂名/檔名/標籤）清除後，這些欄位本身不含個資。

## 決策明細

### D1. 內容硬刪、metadata 匿名化保留
- **硬刪**：音檔 + `transcriptions` + `segments` + `summaries`（皆為實際內容，屬 PII 且佔儲存）。
- **匿名化保留**：task 文件本體不刪（`task_repo.anonymize_all_for_user`）——清 PII/內容參照
  （`user_email`、`custom_name`、`file.filename`、`tags`、`result.audio_file`·`audio_filename`），
  保留統計欄位並記 `anonymized_at`。字數統計（`text_length`/`word_count`）已反正規化在 task 上，
  故刪 transcriptions 不會損失這些計數。

### D2. 統計來源一律指向「會存活」的 collection
歷史一致性的前提是：**統計不能從會被刪的 collection 算**。
- 摘要相關統計（dashboard 模型分布、top_users 摘要 token、每日摘要）**改讀 `summary_logs`**
  （append-only、保留、且記「每次生成」更貼近實際 API 用量/成本），**不再讀 `db.summaries`**（會被刪）。
- 標點/轉錄/辨識統計、處理時長、punctuation token 皆來自 `tasks`（保留），本就存活。
- AI 成本頁（`monthly_cost`）已讀 `summary_logs` + `tasks`，天生一致。

### D3. 刪除事件不記原始 email
`audit_logs` 有 365 天 TTL，但刪除事件原本把 `email` 寫進 message，形成
`user_id → audit_logs → email` 的反查鏈，使保留的 task 實質上仍是**可反查的假名化**資料。
→ 刪除事件**只記 `user_id`**（不記 email），切斷反查鏈。稽核仍可用 user_id 追蹤「誰刪了帳號」。

### D4. 顯示層統一去識別假名
已刪帳號 email=None 會造成後台空白，影響瀏覽。統一以
`user_display.deleted_user_label` →「已刪除用戶#<內部id後6碼>」呈現：由內部 id 衍生、
穩定可辨（同帳號同標籤，可辨別關聯）、不含 PII、不可逆推。套用於使用者列表/詳情、
任務列表/詳情、營收近期訂單。

## GDPR 合規姿態（誠實聲明）

- 保留 `user_id` 做統計分組 + 保留 orders（法定），本質是**假名化（pseudonymisation）**而非
  **匿名化（anonymisation）**；假名化資料技術上仍屬個資，保留依據為「統計目的之正當利益」+
  「金流之法定義務」。
- 執行 D1+D3 後，可用來反查真人的 PII（email/姓名/語音/內容）皆已銷毀、且切斷 audit 反查鏈，
  實務上無合理的再識別路徑，此姿態業界普遍可接受。
- 若未來需「純匿名、完全脫離 GDPR」的統計，需改採**預先聚合計數器**（月統計只存數字、不掛
  user_id）。屬較大架構改動，目前判定非必要，暫不採用。

## 後果（Consequences）

- ✅ 內容與音檔刪除 → 滿足刪除權與省儲存。
- ✅ 統計/AI 成本/歷史數字在帳號刪除後維持一致（來源皆為存活的 metric collection）。
- ⚠️ **統計會包含已刪帳號的匿名任務**——這是刻意保留的結果，帳面總量會比「硬刪」舊邏輯高，
  且已刪帳號在 top_users 以假名出現。此為預期行為。
- ⚠️ orders 仍保留可連 user_id 的金流紀錄（法定），非完全匿名；到法定保存期滿另行清理。

## 實作檢查清單

- [x] `task_repo.anonymize_all_for_user`（D1）
- [x] `delete_account` 內容硬刪 + 任務匿名化保留（D1）
- [x] 顯示假名 `user_display` + 套用各後台畫面（D4）
- [ ] **D2**：`admin_analytics.full_report` 摘要統計（`summary_models` / `user_summaries` /
      `daily_summaries`）改讀 `summary_logs`
- [ ] **D3**：`delete_account` 的 audit message 移除 email，只記 user_id
- [ ] 上 staging 用測試帳號實跑：確認內容清除、假名顯示、統計含匿名任務且不掉數

## 備註：既有已刪帳號

本決策生效前刪除的帳號，其 tasks 當時已被**硬刪**（無法復原，也本應刪除），故沒有匿名化保留的
task；其 user email 已是 None，套用 D4 後會正確顯示假名。只有生效後新刪除的帳號才享有 D1 的
匿名化保留。
