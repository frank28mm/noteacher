# 文档导航（唯一入口）

> 目的：减少“多份计划/多份报告”带来的混淆，明确每份文档的职责边界与优先级。  
> 规则：阅读与执行时，以“真源/契约/路线图/Backlog”四类为主；其余文档都视为“阶段性报告/分析材料”，不直接作为交付承诺。

## 0) 公告（行动项）

- Profile 子账号（家庭-子女）方案：文档对齐与行动项（2026-01-17）：`docs/announcements/profile_management_alignment_20260117.md`

## 1) 真源（必须对齐）

- 需求边界：`product_requirements.md`
- 定价与配额（BT→CP + 报告券）：`docs/pricing_and_quota_strategy.md`
- 接口契约：`homework_agent/API_CONTRACT.md`
- 架构总览：`system_architecture.md`
- 前端真源（Stitch UI 对齐）：`docs/frontend_design_spec_v2.md`
- 数学知识点口径（知识图谱/命名规范）：`docs/math_knowledge_graph.md`
- 工程对齐与约束：`docs/engineering_guidelines.md`
- 开发规则（门禁/日志/安全/回滚）：`docs/development_rules.md`
- 数据库 Schema 真源（当前以实际 DB 为准）：`supabase/schema.sql`

## 2) 路线图（只保留 1 份）

- CTO 90 天路线图（当前主计划）：`docs/cto_90_day_plan.md`

## 3) Backlog（只保留 1 份可执行清单）

- Agent 工程/质量 Backlog（P0/P1/P2 工作清单 + 伪代码）：`docs/agent/next_development_worklist_and_pseudocode.md`
- 当前执行计划（可跟踪清单）：`docs/tasks/development_plan_grade_reports_security_20260101.md`

> 说明：Backlog 是“候选任务池”，不是承诺；每个 sprint 只从这里挑选少量条目，并落到 issue/看板。
>
> 约定：性能实验默认用 **N=5** 作为迭代样本量（看 `p50 + max + 失败率/needs_review率`）；需要做默认策略/验收结论时再补一轮 N=5（两轮合并≈N=10 后看 `p50/p95`）。

## 4) 归档计划/实验（不要当执行计划读）

- Autonomous Grade Agent 实施计划（已归档）：`docs/archive/reports/archived/implementation_plan_autonomous_grade_agent.md`
- Autonomous Grade Agent 任务清单（已归档）：`docs/archive/reports/archived/task_autonomous_grade_agent.md`
- 性能/优化实验（已归档）：`docs/archive/reports/archived/optimization_plan_v2.md`
- 智能提升路线图（已归档）：`docs/archive/reports/archived/agent_intelligence_improvement_plan.md`

## 5) 报告/分析（只作为参考，不当计划执行）

- 接手调研（阶段性快照）：`docs/archive/cto_onboarding_report.md`
- 接手结论（阶段性快照）：`docs/archive/reports/cto_takeover_report_20251229.md`
- 合规性自检：`docs/archive/code_compliance_analysis.md`
- 项目评估报告：`docs/archive/project_evaluation_report.md`
- 外部“体检报告”代码核对与口径对齐：`docs/reports/healthcheck_report_code_alignment_20260103.md`
- /grade 快路径复盘（URL-only + qindex_only）：`docs/reports/grade_perf_fast_path_summary_20260102.md`
- 性能/优化实验：`docs/archive/reports/archived/optimization_plan_v2.md`
- 智能提升路线图（已被 Backlog 吸收）：`docs/archive/reports/archived/agent_intelligence_improvement_plan.md`

## 5.1) 设计文档（Design Docs，支撑落地，不替代路线图/Backlog）

- 错题双存储 + 学情分析报告 Subagent（实施方案）：`docs/archive/design/mistakes_reports_learning_analyst_design.md`
- 家庭-子女（Profile）账户切换（技术方案与开发计划）：`docs/profile_management_plan.md`

## 6) “不再当计划读”的约定

- 任意时间点，只允许存在 **1 份路线图**（当前为 `docs/cto_90_day_plan.md`）。
- 任意时间点，只允许存在 **1 份可执行 Backlog**（当前为 `docs/agent/next_development_worklist_and_pseudocode.md`）。
- 其他“计划/路线图/改进方案”必须：
  - 要么并入上述两份文档
  - 要么移动到 `docs/archive/reports/` 并标注“归档/仅供参考”
