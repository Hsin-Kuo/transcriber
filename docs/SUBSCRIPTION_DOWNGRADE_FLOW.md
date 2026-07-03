# 訂閱降級流程（排程降級 / 期末生效）

> 對應程式：`src/routers/subscriptions.py`（checkout）、`src/services/order_settlement.py`
> （webhook 結算）、`src/database/repositories/order_repo.py`（pending 單清掃）。
> 藍新定期定額欄位定義見 [`NEWEBPAY_PERIOD_API.md`](./NEWEBPAY_PERIOD_API.md)。

## 設計原則

使用者降級應**維持舊方案到目前計費週期結束，期末才切到新的低方案**（不立即生效）。
實作方式：checkout 端立即終止舊委託、建立一張**首扣日 = 期末**的新定期定額委託
（藍新 `PeriodType=D + PeriodStartType=3`），並在 user 上記 `pending_plan_change`；
**tier / quota 到期末真正首扣才變更**。

判別「是否已到期末」以 **首扣日（`scheduled_date`，台灣時區）vs 今日** 為準，
**不依賴藍新 Notify 的欄位格式**（`AuthTimes` / `AlreadyTimes`）——因為藍新 NPA-N050
（帶 `AlreadyTimes`）依手冊是「第二期含之後」才發，期末真正首扣（第 1 期）可能是無
`AlreadyTimes` 的建立完成格式，用欄位判別會誤擋。

---

## 情境 A：排程降級（目前週期剩餘 ≥ 2 天）— 期末生效

```mermaid
sequenceDiagram
    autonumber
    actor U as 使用者
    participant R as change_plan()<br/>(subscriptions.py)
    participant NP as 藍新定期定額
    participant W as period_notify()<br/>(webhook)
    participant S as OrderSettlement.settle()
    participant DB as Mongo<br/>(users / orders)

    Note over U,DB: ── Checkout（今日，距期末 ≥ 2 天）──
    U->>R: POST /subscriptions/change（降到 basic）
    R->>NP: terminate_period_contract(舊 Pro 委託)
    Note right of R: 立即終止舊委託，防到期前再扣款
    R->>DB: open_pending(downgrade 單)<br/>scheduled_date=期末日<br/>expires_at=首扣日+3天
    R->>DB: users.pending_plan_change = {tier:basic, 首扣日, order_no}
    Note right of DB: tier / quota 不變，使用者仍是 Pro
    R->>NP: create_period_form_scheduled(PeriodFirstdate=期末日)
    R-->>U: 導向藍新付款頁
    U->>NP: 完成委託建立（type=3，不立即扣款）

    Note over NP,DB: ── 建約當下：建立完成 Notify（可能即時到達）──
    NP-->>W: Notify（first_payment，今日 < 首扣日）
    W->>S: settle(PaymentNotification)
    S->>DB: order 記 period_no / trade_no
    Note right of S: _should_defer_scheduled_downgrade()<br/>今日 < 首扣日 → 延後
    S-->>W: SettleResult(SCHEDULED)
    Note right of S: 不動 tier/quota，pending_plan_change 保留，<br/>order status 維持 pending（絕不設 paid）

    Note over NP,DB: ── 期末當天：真正首扣 ──
    NP-->>W: Notify（first_payment，今日 = 首扣日）
    W->>S: settle(PaymentNotification)
    Note right of S: 今日 ≥ 首扣日 → 真正套用降級
    S->>NP: _terminate_prev（舊委託已終止，冪等略過）
    S->>DB: users.subscription = {tier:basic, pending_plan_change:null, ...}
    S->>DB: update_quota(basic) + reset_monthly_usage
    S->>DB: order status = paid
    S->>DB: _reconcile_pinned_audio(basic)（釘選超額 → 寬限期）
    S-->>W: SettleResult(ACTIVATED)
    Note right of DB: 此時才真正降為 basic
```

**關鍵不變式**

| 步驟 | 保證 |
|------|------|
| Checkout | 只記 `pending_plan_change`，**tier / quota 不變** |
| 建約 Notify（首扣日之前） | 回 `SCHEDULED`，status **維持 pending**（設 paid 會讓期末首扣被 `already_paid` 短路） |
| pending 單存活 | `expires_at = 首扣日 + 3 天`，不被 `periodic_order_cleanup` 提早掃成 expired |
| 期末首扣 Notify | 今日 ≥ 首扣日 → 真正套用，與 Notify 欄位格式無關 |

---

## 情境 B：立即降級（目前週期剩餘 < 2 天）— 即時生效

剩餘不足 2 天不值得排程，直接用 `PeriodStartType=2` 立即建約首扣，`scheduled_date=None`。

```mermaid
sequenceDiagram
    autonumber
    actor U as 使用者
    participant R as change_plan()
    participant NP as 藍新定期定額
    participant W as period_notify()
    participant S as OrderSettlement.settle()
    participant DB as Mongo

    U->>R: POST /subscriptions/change（剩餘 < 2 天）
    R->>NP: terminate_period_contract(舊委託)
    R->>DB: open_pending(downgrade 單，scheduled_date=None)
    R->>NP: create_period_form(PeriodStartType=2，立即首扣)
    R-->>U: 導向藍新付款頁
    U->>NP: 完成付款（立即扣款）
    NP-->>W: Notify（first_payment）
    W->>S: settle(...)
    Note right of S: scheduled_date=None → 不延後，立即套用
    S->>DB: subscription=basic + update_quota(basic) + status=paid
    S-->>W: SettleResult(ACTIVATED)
```

---

## SettleOutcome 對照

| Outcome | 情境 |
|---------|------|
| `SCHEDULED` | 排程降級的 Notify 在首扣日之前到達 → 延後，尚未生效 |
| `ACTIVATED` | 首期成功、真正套用方案（含期末首扣 / 立即降級 / 新訂閱 / 升級） |
| `RENEWED` | 續扣成功、展期 |
| `EXPIRED` | 續扣失敗 → 降為 free |
| `ALREADY_PAID` | order 已 paid，重發短路 |

---

## webhook natural_id 冪等鍵（已防禦 type-3 碰撞）

webhook 依 Notify 型態選冪等鍵：

| Notify 型態 | natural_id | 理由 |
|-------------|-----------|------|
| 每期授權（有 `AlreadyTimes`） | `{order}:{already_times}` | per-period 唯一；**不併入 TradeNo**，否則藍新換號重送會重複滾 period_end / 重置用量 |
| 建立完成類（無 `AlreadyTimes`） | `{order}:init:{trade_no}` | 同一 order 的建約當下與 type-3 期末首扣可能都是此格式，靠 `TradeNo`（各次授權唯一）區分，避免後到那封被冪等擋掉 |

**背景**：若只用 `{order}:init`，當藍新對 `PeriodStartType=3` 在**建約當下**與**期末首扣**
都送建立完成格式（無 `AlreadyTimes`），兩封會碰撞、期末那封被 `ProcessedWebhookRepository.claim`
當重複擋掉 → 降級卡住不生效。改併入 `TradeNo` 後：不同授權事件 → 不同鍵 → 都能處理；
藍新重送同一封仍帶同 `TradeNo` → 照樣去重。`settle()` 另有 order 生命週期短路（已 paid），
雙重保險。

> 本地 `scripts/sim_downgrade_webhook.py` 已重現此碰撞並驗證防禦（S4）。

**Level 2 sandbox 仍建議確認**（非阻擋部署，屬最終驗證）：撈 `subscription.webhook.received`
的 log 看藍新 type-3 (a) 建約當下有無 Notify、(b) 期末首扣的 `AlreadyTimes` 有無 —
只是確認實際型態，正確性已由日期 gate + TradeNo natural_id 兩層保住。
