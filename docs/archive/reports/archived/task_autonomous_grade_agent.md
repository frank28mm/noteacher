# Task List (Autonomous Grade Agent)

Reference:
- docs/autonomous_grade_agent_design.md
- docs/autonomous_agent_implementation.md
- docs/autonomous_agent_prompts.md

## Dependencies
- P0 complete before P1
- math_verify sandbox ready before Executor integration
- Aggregator mapping validated before /grade integration

## Rollback Triggers
- Error rate > 10%
- P95 latency > 90s
- JSON repair success rate < 80%

## Success Criteria
- Error rate < 5%
- P50 latency < 30s, P95 < 60s
- JSON repair success rate > 95%
- judgment_basis 合格率 > 90%（2-5 句中文，包含“依据来源”）
- Loop 平均迭代次数 < 2
- Unit test coverage > 80%

## P0
- [x] Create `SessionState` skeleton (`services/session_state.py`)
- [x] Create `AutonomousAgent` skeleton (`services/autonomous_agent.py`)
- [x] Define `output_key` mapping table in code
- [x] Add logging: `agent_plan_start`, `agent_tool_call`, `agent_reflect_pass`, `agent_finalize_done`
- [x] Implement Loop exit logic (pass + confidence + max_iterations)
- [x] Create Prompt templates (`core/prompts/autonomous_agent_prompts.py`)

## P1
- [x] Implement `PlannerAgent`
- [x] Implement `ExecutorAgent` (no LLM call)
- [x] Implement `ReflectorAgent`
- [x] Implement `AggregatorAgent`
- [x] Implement Tool: `diagram_slice`
- [x] Implement Tool: `qindex_fetch`
- [x] Implement Tool: `math_verify` (sympy sandbox)
- [x] Implement Tool: `ocr_fallback`
- [x] Aggregator: `results -> wrong_items` mapping
- [x] Planner 输入包含上一轮 `reflection_result`（issues/suggestion）
- [x] Executor 统一重试（1-2 次 + 简单退避）
- [x] Aggregator 限制图片数量（figure+question 各 1 张，最多 2 张）
- [x] diagram_slice 失败自动降级到 ocr_fallback（写死链条）
- [x] 429/TPM 限流退避策略（1s→2s→4s）
- [x] SessionState variable naming规范（plan/evidence/tool_results/result）
- [x] Hierarchical logger names (autonomous.planner/executor/reflector/aggregator)

## P2
- [x] Replace `/grade` to use `AutonomousAgent.run()`
- [x] Remove legacy pipeline
- [x] Add unit tests for each agent
- [x] Add E2E test (`test_autonomous_agent_e2e.py`)
- [x] SSE 事件补全 `duration_ms` 字段（全事件）
- [x] Planner/Reflector 输入字段精简（token 优化）
- [ ] confidence 阈值校准（采样 telemetry）
- [x] 异常测试覆盖（超时/坏 JSON/限流）

## QA
- [x] Prepare local replay dataset (10-20 samples)
- [x] Record accuracy/uncertain/error metrics (telemetry.py)
- [x] Record P50/P95 latency (telemetry.py)
- [x] Test loop exit conditions (pass / max iterations)
- [x] Smoke test：放宽超时（>=300s）验证 Loop 能完整跑通
- [ ] confidence 阈值校准（采样 telemetry）- 需要实际运行数据

## QA 测试套件
- [x] `test_autonomous_agent.py` - 10 passed
- [x] `test_autonomous_agent_e2e.py` - 1 passed
- [x] `test_autonomous_smoke.py` - 4 passed (loop exit validation)
- [x] `test_telemetry.py` - 4 passed (metrics calculation)
- [ ] `test_replay.py` - 待创建（需要实际图片样本）

## QA 工具
- [x] `utils/telemetry.py` - 遥测收集与分析
- [x] `tests/replay_data/` - 回放数据集结构
- [x] `docs/qa_replay_dataset.md` - 回放数据集文档
