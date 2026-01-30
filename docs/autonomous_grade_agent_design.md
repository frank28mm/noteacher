# Autonomous Grade Agent 设计说明（真源）

> 目的：把“/grade 的统一阅卷 Agent”核心设计口径写清楚，避免只看代码导致的误读。
>
> 适用范围：`/api/v1/grade` 主链路，以及与其强相关的 qindex/复核卡/报告事实表。

## 1. 设计目标（Why）

- **可解释**：输出必须包含可审计的 `vision_raw_text` 与 `judgment_basis`（中文短句），证据不足要明确降级（`uncertain/needs_review` + `warnings`）。
- **可控**：有明确的成本/时延护栏（timeout/token budget/并发上限），并可在日志与 qbank meta 中追溯运行版本与耗时拆解。
- **可扩展**：把重任务（bbox/切片/复核/报告）通过 Redis 队列与 worker 解耦，避免 API 主进程被拖慢。

## 2. 核心闭环（What）

Autonomous Grade Agent 采用“规划→工具→反思→汇总”的闭环：

1) **Planner（规划）**：决定本轮要调用哪些工具（例如 qindex_fetch / ocr_fallback / math_verify 等）。
2) **Tools（执行）**：按计划执行工具并收集证据（OCR 文本、切片 refs、校验结果等），工具输出统一为 `ToolResult`。
3) **Reflector（反思）**：判断证据是否足够、是否触发风险；不足则给出下一轮建议或直接降级。
4) **Aggregator（汇总）**：产出结构化判定结果（questions + wrong_items + summary + warnings），并补齐 `judgment_basis` 最小长度。

## 3. 关键产品化决策（How）

### 3.1 快路径默认策略（稳定优先）

- 默认优先走 **qindex_only + url** 的快路径：复用已有切片/缓存；未命中时不强行做重预处理。
- VLM locator / OpenCV 预处理等“高成本路径”只在需要时触发（例如视觉风险/复核），避免拖慢整体 TTV。

### 3.2 证据不足时的降级策略（Fail-closed）

- 允许输出 `uncertain`，但必须：
  - 在 `warnings` 明确“依据不足/切片不可用/图像不清”等原因；
  - 在 `judgment_basis` 写明“依据来源”与可复盘的依据描述；
  - **禁止编造 bbox/slice**。

### 3.3 版本与审计（Run Versions）

为了可回放/可回归，必须把关键版本信息写入：

- 日志事件：`run_versions`（prompt_id/version/variant/provider/model 等）。
- qbank meta：`timings_ms`（预处理/工具/LLM/DB 等分项耗时）与必要的 experiment 决策信息。

## 4. 代码与模块对应关系（Where）

- 入口（/grade）：`homework_agent/api/grade.py`
- Agent 闭环实现：`homework_agent/services/autonomous_agent.py`
- Prompt 真源：`homework_agent/core/prompts_autonomous.py`
- 工具注册与执行：`homework_agent/services/autonomous_tools.py`
- qindex 队列：`homework_agent/services/qindex_queue.py` / `homework_agent/workers/qindex_worker.py`
- grade 队列：`homework_agent/services/grade_queue.py` / `homework_agent/workers/grade_worker.py`
- Schema 真源：`homework_agent/models/schemas.py`

## 5. 与其它真源文档的关系（Alignment）

- 需求边界：`product_requirements.md`
- 接口契约：`homework_agent/API_CONTRACT.md`
- 执行流程与 SOP：`agent_sop.md`
- 工程约束与门禁：`docs/engineering_guidelines.md`、`docs/development_rules.md`

