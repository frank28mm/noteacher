# /grade 视觉题验证与触发规则（A‑5）— 2026‑01‑02

> 目标：在快路径固定（`AUTONOMOUS_PREPROCESS_MODE=qindex_only` + `GRADE_IMAGE_INPUT_VARIANT=url`）后，用真实“几何/示意图”样本验证视觉题的表现，并把“何时必须切到视觉证据路径”的门槛固化为可解释规则。

## 1. 输入样本

- 样本 A（几何题，图在题目旁）：`/Users/frank/Desktop/作业档案/数学/202511/1103/IMG_0699 copy.JPG`
- 样本 B（几何题，图与题目不完全相邻）：原图 `'/Users/frank/Desktop/作业档案/IMG_1100.HEIC'`
  - 备注：Demo 链路本身支持 HEIC（`/uploads` 内部可将 HEIC/HEIF 转为 JPEG，见 `homework_agent/utils/supabase_client.py`）。
    本次 bench 为了让输入资产“定型”（避免把转码成本/差异混入对比），使用预先转好的 JPEG：`tmp/bench_assets/IMG_1100.jpg`

> 备注：当前没有“函数坐标系图”样本；触发规则仍包含坐标/函数关键字，待后续补样复核。

## 2. 测试矩阵（N=5）

固定条件：
- `GRADE_IMAGE_INPUT_VARIANT=url`
- `ARK_IMAGE_PROCESS_ENABLED=1`
- bench：`scripts/bench_grade_variants_async.py`（顺序跑，减少排队污染）

输出证据（每组都有 md/json 明细）：
- A / qindex_only：`docs/reports/grade_perf_visual_img0699_qindex_only_url_n5_20260102.md`
- A / full：`docs/reports/grade_perf_visual_img0699_full_url_n5_20260102.md`
- B / qindex_only：`docs/reports/grade_perf_visual_img1100_qindex_only_url_n5_20260102.md`
- B / full：`docs/reports/grade_perf_visual_img1100_full_url_n5_20260102.md`

汇总（p50/p95，单位 ms；以 bench 的 `total_ms` 与 `grade_total_duration_ms` 为准）：

| 样本 | preprocess_mode | N | total_ms p50 | total_ms p95 | grade_total p50 | grade_total p95 |
|---|---|---:|---:|---:|---:|---:|
| A | qindex_only | 5 | 99,667 | 124,013 | 95,700 | 122,466 |
| A | full | 5 | 271,811 | 316,604 | 271,185 | 315,233 |
| B | qindex_only | 5 | 71,208 | 80,414 | 70,135 | 79,170 |
| B | full | 5 | 225,940 | 263,524 | 224,908 | 261,334 |

## 3. 关键观察（基于 N=5 数据）

### 3.1 性能结论

- 在两张几何图上，`qindex_only` 明显更快（A：~1.6–2.1min；B：~1.1–1.3min）。
- `full` 模式主要额外成本来自预处理 VLM locator + crop/upload（约 70–100s），把总耗时推到 ~3.5–5.3min。

### 3.2 质量/可用性风险（从 qbank meta 直接可见）

样本 A（`full`）出现了“预算/保守降级”类提示（节选）：
- `token_budget_exhausted_needs_review` / `needs_review`
- `Conservative Gate: Downgraded ... due to risks: ['needs_review', 'budget_exhausted']`

样本 B（`full`）更明显：多次出现“图缺失/无法验证”的叙述，同时 `ark_image_process_requested=true`：
- 这意味着：工具能力打开了，但输入给模型的“视觉证据”不稳定（切片可能没切到关键图形；且当时只喂切片、没有全页兜底）。

## 4. 根因定位（代码级解释）

### 4.1 “切片名义上有，但模型说图缺失”的根因

在 `homework_agent/services/autonomous_agent.py` 的 Aggregator 里：
- 当存在 `figure_urls` 时，旧逻辑会 **只把 slices 作为图片输入**（`image_source=slices`），不再携带原始全页图。
- 同时 `image_process` 的启用条件也偏严格：旧逻辑要求必须有 `figure_urls` 才允许开启工具。

因此当 slice 没切到“关键示意图”时：
- 模型既看不到全页，也无法自行缩放定位到图，最终只能输出“图缺失/不确定”。

### 4.2 “full 更容易 needs_review”的根因

- `AUTONOMOUS_AGENT_TOKEN_BUDGET_TOTAL` 默认 12k，旧逻辑只在 `qindex_only/off` 才把 budget 拉到 >=40k，导致 `full` 更容易提前触发 token budget 相关降级/保守门控。
- Planner/Reflector 循环（默认 `AUTONOMOUS_AGENT_MAX_ITERATIONS=3`）会显著抬高 token 消耗与不确定性。

## 5. 修复与二次验证（已落地）

相关改动：
- `homework_agent/services/autonomous_agent.py`
  - `token_budget_total` 对所有模式都抬到 `>= 40000`
  - 新增 `visual_risk`（基于 OCR 的可解释触发信号）
  - `qindex_only/off` 下：若 `visual_risk=true`，不再强制走“纯 OCR 文本聚合”，改为 **带图 + 开启 image_process**（即使没有 slices）
  - 有 slices 时：图片输入改为 `slices_plus_original`（附带压缩后的原始全页作为兜底）
- `homework_agent/utils/settings.py`
  - `AUTONOMOUS_AGENT_MAX_ITERATIONS` 默认改为 `0`（loop 默认关闭，feature flag `grade.autonomous_loop` 再开启 canary）

二次验证（smoke，N=1，用于验证触发与风险消除）：
- 样本 B / qindex_only（视觉风险触发，工具开启）：`docs/reports/grade_perf_visual_img1100_qindex_only_url_n1_after_visual_risk_fix_20260102.md`
  - `ark_image_process_requested=true`，不再出现“图缺失”，耗时约 117s
- 样本 B / full（loop 默认关闭 + slices_plus_original）：`docs/reports/grade_perf_visual_img1100_full_url_n1_after_loop_off_retry_20260102.md`
  - `ark_image_process_requested=true`，无 `needs_review`/预算降级提示（仍有 ~90s 预处理成本）
  - 注：存在 1 次瞬时 `autonomous_agent_llm_failed`（重试即恢复），属于外部调用波动

## 6. 最终建议：快路径固定 + 视觉路径触发规则

### 6.1 继续固定的默认策略（Demo/当下版本）

- 默认：`AUTONOMOUS_PREPROCESS_MODE=qindex_only` + `GRADE_IMAGE_INPUT_VARIANT=url`
- 默认 loop：`AUTONOMOUS_AGENT_MAX_ITERATIONS=0`（更快、更稳、更可解释）

### 6.2 视觉路径（轻量）触发规则（建议长期保留）

当满足以下任一条件时，不走“纯 OCR 文本聚合”，而走 “带图 + image_process”：
- 有 slices：`len(slice_urls.figure) > 0` 或 `len(slice_urls.question) > 0`
- 无 slices 但 OCR 命中 `visual_risk` 信号（可解释）：包含 `如图/下图/图中/∠/△/⊙/⟂/∥/坐标/函数/抛物线/...` 等关键字

行为：
- 图片输入：优先 `slices_plus_original`；否则用压缩后的全页图
- 工具启用：`ark_image_process_requested=true`（即使没切片，只要 `visual_risk=true`）

### 6.3 full 模式使用边界（不作为默认快路径）

- `full` 仍保留为“正确性上限/离线复核”路径：
  - 优点：可生成 slices（便于定位/辅导）
  - 缺点：稳定额外 ~70–100s 预处理成本
- 建议：只在以下场景启用：
  - 需要做“视觉证据链审计/复盘”
  - 轻量视觉路径（visual_risk + image_process）仍不足以判定时的人工/后端复核策略
