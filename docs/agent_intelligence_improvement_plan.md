# Agent 智能提升路线图（与门禁/约束对齐）

> **文档定位**：这是“智能提升”的路线图与 Backlog 归口，用于提升仓库文档质量与执行一致性。  
> **近期执行主计划（真源）**：`docs/agent/next_development_worklist_and_pseudocode.md`（P0/P1/P2 + 迭代模板 + 伪代码）。  
> **本路线图的原则**：任何“变聪明”的改动，必须先满足 **可回归（replay+metrics）/可观测（request_id+usage）/可控成本（budget+timeout）/可回滚（版本可追溯）**。

---

## 1. 决策依据（已对齐的需求与目标）

本计划以以下文档为约束与验收口径（优先级从高到低）：

1. `product_requirements.md`：产品边界与行为要求。
2. `API_CONTRACT.md`：接口契约（字段、幂等、错误码、SSE 等）。
3. `agent_sop.md`：执行流程与关键约束（尤其是**记忆边界**与降级策略）。
4. `docs/engineering_guidelines.md`：工程约束与真源入口。
5. `docs/development_rules.md` + `docs/development_rules_quickref.md`：团队开发规则（门禁、日志、回滚、安全、可观测性）。

并以 5 份白皮书的对照分析作为“为什么要做/先做什么”的依据：
- `docs/agent/agent_architecture_analysis.md`
- `docs/agent/agent_context_analysis.md`
- `docs/agent/agent_mcp_analysis.md`（已决定现阶段不做 MCP 接入）
- `docs/agent/agent_quality_analysis.md`
- `docs/agent/prototype_to_production_analysis.md`

---

## 2. “修路阶段”现状复盘（按真实仓库校准）

你们已经具备“修路”的关键组件，但属于 **soft gate（链路已在、还未硬阻断）**：

- ✅ 工具链已具备：`scripts/check_observability.py`、`scripts/check_baseline.py`、`scripts/generate_metrics_report.py`
- ✅ replay 入口已具备：`homework_agent/tests/test_replay.py`（默认 schema/lint，不会误触发真实外部调用）
- ✅ 开发规则已归口：`docs/development_rules.md`（主规则）+ `docs/development_rules_quickref.md`（速查卡）
- ✅ CI 已接入骨架：`.github/workflows/ci.yml`（有数据则跑 replay+metrics+baseline）

仍需补齐（否则“智能升级”无法被验证）：

- ⏳ `homework_agent/tests/replay_data/` 需要补齐到 Golden Set v0（至少 20 个）才能让门禁常态化。
- ⏳ baseline 文件（例如 `.github/baselines/metrics_baseline.json`）需要生成并提交后，才能从 `--allow-missing-baseline` 过渡到“硬阻断”。
- ⏳ 关键路径的 `request_id/session_id/iteration/stage` 贯通仍需系统性代码改造（目前可观测性脚本已指出缺口）。

---

## 3. 6 周路线图（融合后版本）

> 说明：这不是瀑布式“大块开发”。每个阶段内部仍按 `docs/agent/next_development_worklist_and_pseudocode.md` 的 **3–5 天迭代模板**推进：一次只改一个变量 → 补 replay case → 跑 metrics → 对比 baseline → 复盘回收。

### Week 1–2：P0（把“变聪明”变成可回归、可控、可解释）

#### P0‑A：Golden Set v0（评估先行）

**交付物**
- `homework_agent/tests/replay_data/` 扩充到 20–30 个样本，覆盖：
  - 清晰/模糊、单题/多题、几何含图、OCR 低质量、缺答/空白、跨学科干扰
- 每个样本有可回放的输入与最小可验证“结构/不确定性处理/降级”期望

**验收**
- PR 改动（prompt/策略）后，CI 能稳定产出 `qa_metrics/metrics_summary.json`
- replay 不再因为“空数据集”而跳过

**伪代码参考**
- 样本 schema / 门禁流程：见 `docs/agent/next_development_worklist_and_pseudocode.md` 的 `WL‑P0‑001`、`WL‑P0‑002`

---

#### P0‑B：关联字段 + usage 成本口径贯通

**交付物**
- FastAPI 层生成/传播 `request_id`（header 优先）
- 关键 `log_event` 与 tool 调用都带：`request_id/session_id/stage/iteration`
- 每次 LLM 调用记录：`provider/model/prompt_id/prompt_version/usage/duration_ms`

**验收**
- 任意线上/离线运行都可按 `request_id` 复盘关键事件链路
- 能从日志/metrics 汇总 tokens 与延迟趋势

**伪代码参考**
- middleware + budget wrapper：见 `WL‑P0‑003`、`WL‑P0‑004`

---

#### P0‑C：工具层契约（ToolResult）+ 安全左移（PII/Injection/HITL）

**交付物**
- 统一 ToolResult（成功/失败一致结构），包含错误恢复字段与 `needs_review/warning_code`
- 输出净化默认启用：token/签名/URL 参数脱敏；PII 探测触发 `needs_review`
- Prompt injection 仅作为“风险信号”（warning_code），走保守降级与 HITL，不改变核心 action 语义

**验收**
- 工具异常不导致 agent 崩溃；产生可统计的错误类型/降级原因
- `needs_review` 可回归评估（样本中能覆盖触发与不触发）

**伪代码参考**
- ToolResult + run_tool 包装：见 `WL‑P0‑005`

---

#### P0‑D：智能提升的“低风险快赢”（在门禁下迭代）

> 目标：不用引入新基础设施，就让效果变好。

**候选改动（每次只做 1 个）**
- Prompt：更严格的输出 schema、自检提示（避免漏题/自相矛盾）
- Parser/Validator：对 LLM 输出做结构校验，失败走“重试/降级/needs_review”
- Tool routing：对工具失败引入稳定 fallback（whole page / skip tool / 降级 OCR）
- 不确定性处理：明确 `uncertain` 的触发条件与可统计原因

**验收**
- 每次改动必须附 replay case + metrics 对比（通过 P0 门禁）

---

### Week 3–4：P1（把“智能提升”变成可治理、可周报驱动）

#### P1‑A：Baseline 阈值治理（soft gate → hard gate）

**交付物**
- 提交 baseline 文件（如 `.github/baselines/metrics_baseline.json`）
- baseline 更新流程：何时允许更新、需要哪些证据（replay+metrics 报告 + 变更说明）

**验收**
- success/uncertain/latency/tokens 任一显著回归能被阻断（或触发明确审批）

---

#### P1‑B：离线周报（Observe→Act→Evolve 的 Observe）

**交付物**
- 每周产出：`metrics_summary.json` + `report.html`
- 报告包含：趋势、Top 回归 case、Top 成本 case、Top needs_review case

**验收**
- 周报可直接指导下一轮迭代（新增 replay case / 修复回归 / 调整阈值）

---

#### P1‑C：（可选增强）LLM-as-a-Judge（仅评“过程/结构/安全”）

**定位**
- Judge 不评 correctness（correctness 以 Golden Set/可验证规则锚定）
- Judge 的输入必须脱敏且摘要化（避免 PII 泄漏与成本失控）

**交付物**
- `judge` 只做抽样（例如每次 20 个样本），输出稳定 JSON 评分与理由
- 记录 judge 自身的 usage/tokens（成本可见）

**验收**
- judge 的评分稳定性可接受（重复评估波动可控）
- 能捕捉“结构/一致性/不确定性处理/安全”退化

---

### Week 5–6：P2（在不破坏约束的前提下引入“上下文增益”）

#### P2‑A：Session Memory（结构化摘要 + 可回放上下文）

**明确边界（对齐 `agent_sop.md`）**
- 辅导链默认：只读当前 Submission 上下文；不读取跨会话画像
- 允许：session 内摘要、近期 turns 压缩、OCR/中间产物缓存、可回放 trace

**交付物**
- SessionMemory：TTL + 上限（turns/tokens）+ 摘要策略
- 可回放上下文：用于定位“为什么这次变差了/变好了”

**验收**
- 带来稳定收益但不引入隐私风险与不可控成本
- 发生回归时能被 replay 捕捉并快速定位

**伪代码参考**
- SessionMemory：见 `docs/agent/next_development_worklist_and_pseudocode.md` 的 `WL‑P1‑003`

---

## 4. 远期扩展（P3+：只作为参考，不进入近期主计划）

这些内容来自旧版计划中“有价值但目前不合适立即落地”的部分：

### P3‑A：跨会话长期记忆/画像（Declarative/Procedural）

**前置条件（必须满足才允许启动）**
- 产品策略允许读取跨会话画像（合规/隐私/用户授权明确）
- 有稳定的评估门禁与回滚机制（hard gate 已启用）
- 有成本预算与隔离（避免记忆系统与 judge 双重把成本打爆）

**建议形态**
- 默认“只写不读”（先做沉淀），灰度打开“可读”并 A/B 评估收益
- storage 不提前锁死：从最小可行存储开始，逐步演进到 Redis/PG 混合

---

## 5. DoD（完成定义）

### P0 DoD
- replay Golden Set v0 已存在且 CI 默认可跑
- request_id/session_id/stage/iteration 全链路贯通到关键日志与 tool 调用
- LLM usage/tokens 有口径、可统计、有 budget/timeout/退避/降级
- 输出净化 + `needs_review/warning_code` 可回归

### P1 DoD
- baseline hard gate 启用（或有明确审批流）
- 每周离线报告能驱动“新增 replay case + 修复回归”
- （可选）Judge 能稳定评估结构/一致性/安全/不确定性处理

### P2 DoD
- Session Memory 带来可衡量收益且不破坏 `agent_sop.md` 记忆边界
- 回归可被评估捕捉，问题可被快速止血与回滚

---

## 6. 与主计划的关系（避免文档分叉）

- 近期执行与伪代码真源：`docs/agent/next_development_worklist_and_pseudocode.md`
- 本文仅维护：
  - “为什么做”（智能提升目标与风险）
  - “何时做”（6 周节奏与阶段边界）
  - “哪些后置”（P3+ 的能力库）

