# 《实施方案 / Design Doc》：错题宽表（Derived Facts）与学情分析师 Subagent

> 状态：Draft（可迭代）  
> 目的：把“作业→错题→辅导→复盘→报告”闭环从可用推进到可运营，并在工程上可扩展、可回归、可解释。

## 1. 背景与目标

### 1.1 现状（代码事实）
- `/grade` 会生成结构化 `wrong_items`（含 `reason/judgment_basis/knowledge_tags/severity/...`），并写入：
  - **Session 缓存**：`mistakes:{session_id}`（TTL=24h，用于 chat 上下文）
  - **Submission 快照（Source of Truth）**：`submissions.grade_result`（JSONB，长期追溯）
- 已提供错题本 MVP 接口（历史检索/排除恢复/基础统计）：见 `homework_agent/API_CONTRACT.md` 的 Mistakes API 章节。

### 1.2 目标（必须满足）
1) **双存储策略**：保留 submission 快照（保险柜）+ 引入派生事实表（可分析、可扩展）。  
2) **报告链路独立**：报告异步生成（可重跑、可审计），不挤占 `/grade` 与 `/chat` 的主链路。  
3) **学情分析师 subagent**：两段式（Hard Features + Soft Narrative），强约束输出 schema 与 evidence refs。  
4) **可治理的标签体系**：knowledge taxonomy 最小可用（避免同义词灾难，保证 Grade/Chat/Report 一致口径）。  
5) **可回归**：报告链路同样要有 replay/样本与指标口径，避免 prompt 漂移。

### 1.3 非目标（本阶段不做）
- 不做“全量知识图谱/复杂推理图数据库”；先做可落地 taxonomy v0/v1。
- 不做 MCP/复杂多代理协作平台化；subagent 先以内部模块 + worker/job 形态落地。

## 2. 总体方案（系统视图）

### 2.1 双存储（Source + Derived）
- **Source（不可变快照）**：`submissions` 表中的 `grade_result`（含 wrong_items）与 `vision_raw_text` 等。
- **Derived（可分析事实）**：新增 `mistakes` 表（或 materialized view / 物化中间表），把 JSONB 里的 wrong_items 拆出来存，服务于：
  - 历史错题页高性能查询（分页、筛选）
  - 统计聚合（按时间/学科/知识点/错误类型）
  - 报告任务的特征计算（features layer）

### 2.2 两段式学情分析师
1) **Features Layer（硬计算）**：SQL/Python 产出确定性指标与摘要（可测、可回归）。  
2) **Narrative Layer（软解释）**：LLM 仅负责“归因与建议表达”，输入为 features + 少量典型 evidence，不负责“数数”。

## 3. 数据模型设计

### 3.1 `mistakes`（Derived Facts）表（建议）
> 目标：一条 wrong_item 对应一行，可直接 group by / filter。

建议字段（MVP）：
- 主键/唯一约束：`unique(user_id, submission_id, item_id)`
- 维度列：
  - `user_id`（text）
  - `submission_id`（text）
  - `session_id`（text, nullable）
  - `subject`（text）
  - `created_at`（timestamptz，来自 submission）
  - `question_number`（text, nullable）
- 分析列：
  - `severity`（text, nullable）
  - `verdict`（text, nullable）
  - `knowledge_tags`（jsonb array / text[] / join table，按实现选型）
  - `reason`（text, nullable）
  - `judgment_basis`（jsonb array, nullable）
- 可审计列：
  - `raw`（jsonb，保存该 wrong_item 原样，便于追溯与调试）
  - `extracted_at`（timestamptz）
  - `extractor_version`（text，用于回放/回滚）

索引建议（MVP）：
- `(user_id, created_at desc)`
- `(user_id, subject, created_at desc)`
- `(user_id, severity)`
- 若 `knowledge_tags` 用数组/JSONB：增加 GIN（后续按实际 query 决定）

### 3.2 `mistake_exclusions`（排除语义）
> 已有表草案与迁移；语义保持：只影响统计/报告，不改历史事实。

### 3.3 `knowledge_taxonomy`（标签治理：v0→v1）
v0（最快落地）：
- 先用“配置/JSON 映射”实现标准化（同义词映射到 canonical tag）。
- 目标是让 Grade/Chat/Report 在统计口径上不漂移。

v1（可扩展治理）：
- 表结构（建议）：
  - `tag_id`（uuid / text）
  - `name`（canonical 名）
  - `aliases`（jsonb array）
  - `parent_id`（可选，形成树）
  - `version`（taxonomy 版本）
- 规则：Report 输出要携带 `taxonomy_version`，保证可解释与可复现。

## 4. 数据管道：提取与回填

### 4.1 触发机制（在线）
在 `/grade` 完成后：
- enqueue `mistake_extraction_job(submission_id, user_id, session_id)`（异步/解耦）
- job 从 `submissions.grade_result.wrong_items` 提取并 upsert 到 `mistakes`

原则：
- **不在请求线程内做重计算**（避免影响 `/grade` SLA）
- job 可幂等（重复执行只 upsert，不产生重复）

### 4.2 Backfill（离线）
提供脚本（示例命名）：
- `python3 scripts/backfill_mistakes.py --since 2025-01-01 --limit 1000`

策略：
- 分批扫描 submissions（按 created_at）
- 每批 upsert mistakes
- 输出进度与失败重试（可暂停/续跑）

## 5. 报告链路（Report Jobs + Subagent）

### 5.1 表与状态机（建议）
- `report_jobs`：
  - `report_job_id`
  - `user_id`
  - `time_range`（start/end）
  - `status`（pending/running/done/failed）
  - `error`（nullable）
  - `created_at/updated_at`
- `reports`：
  - `report_id`
  - `report_job_id`
  - `user_id`
  - `time_range`
  - `features`（jsonb，硬计算产物）
  - `narrative`（jsonb，LLM 输出；含 summary/insights/plan/evidence_refs）
  - `model/prompt_version/extractor_version/taxonomy_version`
  - `created_at`

### 5.2 Features Layer（硬计算：SQL/Python）
最小指标（可回归）：
- 错误类型画像：severity 分布 + 典型例子（top K）
- 知识点薄弱 TopN：按 taxonomy 后的 tag 统计（可按时间窗口与趋势）
- 趋势：近 7/14/30 天变化（可选）
- 复盘材料：选取代表性错题 evidence（限制数量、脱敏）

输出：固定 schema（见 6.1）。

### 5.3 Narrative Layer（LLM subagent）
