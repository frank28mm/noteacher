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
- Agent Skills（业务 Agent）真源：`docs/agent_skills_ssot.md`
- 前端真源（Stitch UI 对齐）：`docs/frontend_design_spec_v2.md`
- 数学知识点口径（知识图谱/命名规范）：`docs/math_knowledge_graph.md`
- 工程对齐与约束：`docs/engineering_guidelines.md`
- 开发规则（门禁/日志/安全/回滚）：`docs/development_rules.md`
- 运行环境约定与上线清单（真源）：`docs/runtime_env_contract.md`
- 部署实施（ACK+ECI+ECS 常驻，生产落地清单）：`docs/deployment_plan_ack_eci_ecs_baseline.md`
- Autonomous Grade Agent 结构设计：`docs/autonomous_grade_agent_design.md`
- **安全审计发现（SSOT）**：`docs/CROSS_AUDIT_REVIEW_CONSOLIDATED_20260129.md`
  - 包含 P0 级安全漏洞验证、修复方案、验收标准、任务清单
- **执行指导（简化版）**：`docs/CROSS_REPORT_REVIEW_ACTIONS_20260129.md`
  - 高密度行动清单，用于任务分配
- 数据库 Schema 真源（以代码仓库为准）：
  - `migrations/*.up.sql`（可回滚迁移，结构主干）
  - `supabase/patches/*.sql`（增量补丁：补字段/补锁/补 RLS 等）
  - `supabase/harden_rls_complete.sql`（生产收紧 RLS：覆盖 facts/report_jobs 等 dev-time anon 策略）
  - `supabase/harden_rls_production.sql`（历史最小脚本：仅 feedback_messages，对照/兼容用）
  - 说明：`supabase/schema.sql` 仅保留少量独立表的 SQL（如 feedback），不再作为全库 schema 真源

## 2) 路线图（只保留 1 份）

- CTO 90 天路线图（当前主计划）：`docs/cto_90_day_plan.md`

## 3) Backlog（只保留 1 份可执行清单）

- 当前执行计划（可跟踪清单）：`docs/tasks/development_plan_grade_reports_security_20260101.md`
- Agent 工程/质量 Backlog（已归档）：`../archive_作业检查大师/agent/next_development_worklist_and_pseudocode.md`

> 说明：Backlog 是“候选任务池”，不是承诺；每个 sprint 只从这里挑选少量条目，并落到 issue/看板。
>
> 约定：性能实验默认用 **N=5** 作为迭代样本量（看 `p50 + max + 失败率/needs_review率`）；需要做默认策略/验收结论时再补一轮 N=5（两轮合并≈N=10 后看 `p50/p95`）。

## 4) 归档计划/实验（不要当执行计划读）

> 注：归档文档已移至项目外 `../archive_作业检查大师/`，此处仅保留索引引用。

- Autonomous Grade Agent 实施计划：`../archive_作业检查大师/archive/reports/archived/implementation_plan_autonomous_grade_agent.md`
- Autonomous Grade Agent 任务清单：`../archive_作业检查大师/archive/reports/archived/task_autonomous_grade_agent.md`
- 性能/优化实验：`../archive_作业检查大师/archive/reports/archived/optimization_plan_v2.md`
- 智能提升路线图：`../archive_作业检查大师/archive/reports/archived/agent_intelligence_improvement_plan.md`
- Agent SDK 文档与教程：`../archive_作业检查大师/agent/`
- 历史报告与实验数据：`../archive_作业检查大师/archive/reports/`

## 5) 报告/分析（只作为参考，不当计划执行）

> 注：归档报告已移至项目外 `../archive_作业检查大师/`。

### 5.1 审计报告归档（2026-01-29 交叉审查）

**原始审计报告**：
- Kimi Code CLI 审计：`../archive_作业检查大师/release_audit_2026-01-29.md`
- Claude 代码事实审计：`../archive_作业检查大师/RELEASE_AUDIT_REPORT_20260129.md`
- Security Review 专项审查：`../archive_作业检查大师/SECURITY_REVIEW_SSRF_JOBS_RLS_20260129.md`
- Trae 综合评估：`../archive_作业检查大师/Trae-noteacher-accessment.md`

**交叉对比审查归档**：
- 交叉对比审查反馈（我生成的）：`../archive_作业检查大师/CROSS_AUDIT_REVIEW_FEEDBACK_20260129.md`
- Trae 交叉对比审查：`../archive_作业检查大师/REVIEW_FEEDBACK_CROSS_REPORT_20260129.md`
- 我的交叉对比报告：`../archive_作业检查大师/CROSS_AUDIT_REVIEW_20260129.md`

### 5.2 历史报告

- 接手调研（阶段性快照）：`../archive_作业检查大师/archive/cto_onboarding_report.md`
- 接手结论（阶段性快照）：`../archive_作业检查大师/archive/reports/cto_takeover_report_20251229.md`
- 合规性自检：`../archive_作业检查大师/archive/code_compliance_analysis.md`
- 项目评估报告：`../archive_作业检查大师/archive/project_evaluation_report.md`
- 外部"体检报告"代码核对与口径对齐：`../archive_作业检查大师/archive/reports/healthcheck_report_code_alignment_20260103.md`
- /grade 快路径复盘（URL-only + qindex_only）：`../archive_作业检查大师/archive/reports/grade_perf_fast_path_summary_20260102.md`

## 5.1) 设计文档（Design Docs，支撑落地，不替代路线图/Backlog）

- 错题双存储 + 学情分析报告 Subagent（实施方案）：`../archive_作业检查大师/archive/design/mistakes_reports_learning_analyst_design.md`
- 家庭-子女（Profile）账户切换（技术方案与开发计划）：`docs/profile_management_plan.md`
- BT额度过期系统设计：`docs/design_bt_quota_expiry_system.md`
- 渐进披露题卡设计：`docs/design_progressive_disclosure_question_cards.md`

## 6) “不再当计划读”的约定

- 任意时间点，只允许存在 **1 份路线图**（当前为 `docs/cto_90_day_plan.md`）。
- 任意时间点，只允许存在 **1 份可执行 Backlog**（当前为 `docs/agent/next_development_worklist_and_pseudocode.md`）。
- 其他“计划/路线图/改进方案”必须：
  - 要么并入上述两份文档
  - 要么移动到 `docs/archive/reports/` 并标注“归档/仅供参考”
