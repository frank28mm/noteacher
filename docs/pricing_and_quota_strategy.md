# 定价与配额策略（BT 精确计费 / CP 整数展示）

> 状态：已确认口径（可执行）。  
> 目标：用“真实 tokens 消耗”严格控成本；对用户只展示一个简单的“剩余 CP”。

## 1) 核心计费单位

### BT（Billable Tokens，后端真实账本）

- 定义：`BT = prompt_tokens + 10 * completion_tokens`
  - 依据：Doubao <32K 档位（输入 0.8 元/百万 tokens，输出 8 元/百万 tokens），输出≈输入的 **10×** 成本权重。
- 规则：`grade/chat/report` **全部按实际 usage 计算 BT 并扣减**（精确到整数 BT）。

### CP（Compute Points，前端展示单位）

- 取整口径（已确认）：`1 CP = 12400 BT`
- 用户侧仅展示剩余量（整数）：
  - `CP_left = floor(bt_spendable / 12400)`
  - 不展示本次扣点、不展示小数、不展示百分比。

> 备注：按我们现有样本统计，标准“单页批改”BT 的中位值≈`124000 BT`，因此可近似理解为 **1 页 ≈ 10 CP**（仅作直觉，不参与扣费判断）。

## 2) 钱包模型（3 池隔离，避免“报告券被 grade/chat 用光”）

为保证“注册送 1 次周期报告必可用”，建议后端按 3 个池维护（均为 BT 精确扣）：

1. `bt_trial`（一次性试用算力，5 天有效）
2. `bt_subscription`（订阅算力，每月发放/重置）
3. `report_coupons` + `bt_report_reserve`（报告券 + 对应 BT 预留，仅用于周期报告）

**扣费顺序（建议，已满足你要求的体验）**

- `grade/chat`：优先扣 `bt_trial`，再扣 `bt_subscription`（不动 `bt_report_reserve`）。
- 周期 `report`：
  - 先消耗 `report_coupons`（次数券）
  - 并从 `bt_report_reserve` 扣 BT（保证“即使可用 CP=0 也能用掉那张报告券”）

## 3) 免费用户策略（Trial Pack，注册即送）

适用对象：**所有注册用户（包含后续付费用户）**，首次注册赠送一次。

> 注册口径（已确认）：**强制手机号验证码登录**（注册=手机号）。因此 Trial Pack 的发放条件等价于“手机号验证通过后创建用户”。

- 试用算力：`200 CP`（= `2,480,000 BT`），**有效期 5 天**
- 周期报告券：`1 张`（有效期 5 天）
- 报告 BT 预留：`bt_report_reserve`（有效期 5 天）
- 周期报告（B）解锁条件：同科目至少 `min_distinct_days=3`（不满足则不可用，但券仍在有效期内保留）

> 注：`bt_report_reserve` 的额度应基于真实日志统计的 **周期报告 BT p95**（作为“每张券的成本上限”），避免成本不可控。

## 4) 订阅等级与权益（Monthly Pack）

> 订阅权益与 Trial Pack 叠加：用户在 Trial 有效期内付费，不回收 Trial（仍可优先消耗 Trial）。

### S1 19.9 元/月（基础）
- 月度算力：`1000 CP/月`（= `12,400,000 BT/月`）
- 月度报告券：`4 张/月`
- 错题/数据保留：`3 个月`
- 复核：风险题复核开启（有上限，避免全量烧钱）

### S2 29.9 元/月（同算力，更长数据）
- 月度算力：`1000 CP/月`
- 月度报告券：`4 张/月`
- 错题/数据保留：`12 个月`
- 复核：同上（可提高复核覆盖上限）

### S3 39.8 元/月（更高算力）
- 月度算力：`2000 CP/月`
- 月度报告券：`8 张/月`
- 错题/数据保留：`3 个月`

### S4 49.8 元/月（更高算力 + 更长数据）
- 月度算力：`2000 CP/月`
- 月度报告券：`8 张/月`
- 错题/数据保留：`12 个月`

### S5 199元/月（重度）
- 月度算力：`10000 CP/月`
- 月度报告券：`20 张/月`
- 错题/数据保留：订阅有效期内长期保留（账户静默 6 个月清理口径后续另定）

## 5) 需要固化到后端的最小能力（用于后续实现）

- 统一产出 usage：所有 LLM 调用都必须落结构化 usage（至少 `prompt_tokens/completion_tokens/total_tokens`）用于 BT 计算与审计。
- 账户/权益存储：
  - `bt_trial`、`bt_subscription`、`report_coupons`、`bt_report_reserve`
  - `trial_expires_at`
  - `data_retention_tier`
- 对外查询接口（前端只需要“剩余 CP + 报告券数”）：
  - `GET /api/v1/me/quota` → `{ cp_left, report_coupons_left, trial_expires_at? }`
