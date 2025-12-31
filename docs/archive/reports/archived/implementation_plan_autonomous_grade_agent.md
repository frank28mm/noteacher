# Implementation Plan (Autonomous Grade Agent)

Scope: full replacement of the grade pipeline with AutonomousAgent.
Reference:
- docs/autonomous_grade_agent_design.md
- docs/autonomous_agent_implementation.md
- docs/autonomous_agent_prompts.md

## Phase 0: Setup
- Create SessionState class and storage contract
- Create AutonomousAgent class skeleton
- Add observability events (plan/tool/reflect/finalize)
- Define output_key mapping (plan/tool/reflection/final)

## Phase 1: Core Loop
- Implement Planner/Executor/Reflector/Aggregator
- Add Loop control:
  - pass=true && confidence>=0.90 → exit
  - max_iterations=3 → force exit + warning
- Planner 输入需包含上一轮 reflection_result（issues/suggestion），避免重复 plan
- Aggregator 仅取最相关图片（figure+question 各 1 张，最多 2 张）

**Timeout policy (early validation)**:
- 先放宽 `AUTONOMOUS_AGENT_TIMEOUT_SECONDS`（建议 300-600s）确保 Loop 跑通
- 通过 smoke test 后再逐步收紧

## Phase 2: Tools
- Implement Function Tools (4 only):
  - diagram_slice
  - qindex_fetch
  - math_verify
  - ocr_fallback
- Centralize retry/timeout in Executor（1-2 次 + 简单退避）

## Phase 3: Integration (Direct Replace)
- Replace `/grade` pipeline with AutonomousAgent
- Remove legacy pipeline code (no fallback)
- Map full results -> wrong_items for compatibility

## Phase 4: Tests & Verification
- Unit tests for each sub-agent
- Tool-level tests
- End-to-end run with fixed image set
- Record P50/P95 latency + accuracy/uncertain rates

## Phase 5: Demo UI Validation
- Ensure demo UI shows: summary, wrong items, judgment_basis, vision_raw_text
- Verify streaming progress messages

## Decision Gates

### Gate 0 → 1
- [ ] SessionState 可序列化/反序列化
- [ ] output_key mapping 已配置
- [ ] 关键日志事件可见（plan/tool/reflect/finalize）

### Gate 1 → 2
- [ ] Loop 可正常退出（pass / max_iterations 两种路径）
- [ ] Reflector pass=true 且 confidence>=0.90 时终止

### Gate 2 → 3
- [ ] 4 个工具单测通过
- [ ] math_verify 沙箱安全验证通过

### Gate 3 → 4
- [ ] /grade 返回格式正确
- [ ] wrong_items mapping 正确

## Risks
- Latency increase (Loop) → mitigate with async job default + progress SSE
- JSON output failures → Aggregator repair + retry
- Tool failures → Executor retry + downgrade
