# 实施方案 / Design Doc：错题双存储 + 学情分析报告 Subagent

> 状态：Draft（可执行，但允许在实施中迭代）  
> 面向：后端工程、数据/算法、产品（用于对齐范围与验收）  
> 目标：把“作业→错题→辅导→复盘→报告”闭环从 MVP 推进到可运营、可解释、可回归的工程形态。

---

## 0. 背景与问题

当前工程已经具备 `/uploads`、`/grade`、`/chat` 的主链路能力，并且把批改结果快照持久化到 `submissions.grade_result`，并基于快照提供了 `GET /api/v1/mistakes`、`POST/DELETE /api/v1/mistakes/exclusions`、`GET /api/v1/mistakes/stats`（MVP）。

但如果后续要实现“学情分析师（报告）”并支持“按知识点/错误类型/时间窗口”的聚合分析，直接从 `submissions.grade_result.wrong_items`（JSONB）遍历会带来：

- 性能风险：统计需要扫大量 JSON，数据量上来后吞吐与延迟不可控
- 工程脆弱：JSON 结构演进、字段缺失会导致统计口径漂移
- 可解释性风险：LLM 同时负责“数数 + 讲人话”，幻觉/不一致更难控

因此本方案引入两条关键工程策略：

1) **错题双存储（Source + Derived）**：`submissions` 作为真源快照；另建 `mistakes`（宽表/派生事实）用于统计与报告。  
2) **学情分析师两段式（Features + Narrative）**：确定性特征先算出来；LLM 只做解释与建议，减少幻觉面。

---

## 1. 非目标（本方案不做什么）

- 不在本阶段改变 `product_requirements.md` 的需求边界与产品话术
- 不在本阶段做 UI/前端页面（仅提供后端 API + 结构化结果）
- 不在本阶段追求“全科目/全题型”报告覆盖：先做可回归的 MVP 指标集
- 明确不做（本期范围外）：
  - 按班级/年级/教材版本的分群对比
  - “进步/退步归因到练习量”的归因结论（但允许展示练习量作为事实背景）

---

## 2. 术语与原则

- **Source of Truth（真源）**：`submissions` 中的原图/识别文本/批改快照（可追溯、可审计、可回放）
- **Derived Facts（派生事实）**：从真源提取出来的可查询/可聚合数据（可重算、可回填、可版本化）
- **排除/恢复语义**：只影响统计/报告，不修改历史批改事实（`mistake_exclusions`）

原则：

- “事实”要可复算；“解释”要可约束
- 任务要可幂等、可重跑、可防重
- 任何口径变更要可回滚、可回归（replay/baseline）

---

## 3. 数据模型（Phase 2：必须做）

### 3.1 submissions（已存在）

维持现状：保存批改快照（至少包含 `grade_result.wrong_items`、`subject`、`created_at`、`user_id`、`session_id` 等）。

### 3.2 mistake_exclusions（已存在）

维持现状：`(user_id, submission_id, item_id)` 维度的排除标记与原因。

### 3.3 mistakes（新增：派生宽表，供统计/报告快速查询）

建议表结构（示意，字段可按现有 `wrong_items` 适配）：

- 主键/唯一键：`(user_id, submission_id, item_id)`（确保幂等 upsert）
- 核心维度：`created_at`（继承 submission）、`subject`、`question_number`
- 解释维度：`severity`、`knowledge_tags`（array/text[] 或 jsonb）、`reason`、`judgment_basis`（可选：文本/结构化证据引用）
- 回溯字段：`wrong_item_raw`（jsonb，保留原条目，便于 schema 演进时回填）
- 版本字段：`extract_version`（用于在提取逻辑升级时做增量/全量回填）

索引建议（最少集）：

- `user_id, created_at desc`
- `user_id, subject, created_at desc`
- `user_id, (unnest(knowledge_tags))`：就用GIN（如 `knowledge_tags` 用 jsonb/array）

### 3.4 question_attempts（新增：全题事实表，用于“正确率/错误率/掌握度”分母）

> 结论：要做“错误率/正确率”“知识点真实掌握度”，必须有 **分母**（正确题也要入表）。  
> 数据来源优先使用 `submissions.grade_result.questions`（包含正确题与错误题）。

建议表结构（最少可用集）：

- 唯一键：`(user_id, submission_id, item_id)`（同一份作业内同一题唯一）
- 维度：`user_id`、`submission_id`、`created_at`、`subject`
- 题目标识：`item_id`（稳定）、`question_number`（纸面题号）、`question_idx`（题目序号，兜底稳定）
- 结果：`verdict`（correct/incorrect/uncertain/partial/unknown）
- 分类（报告必需）：
  - `knowledge_tags_norm`（归一化后的 tags，用于统计口径）
  - `question_type`（题型，如 choice/fill_blank/calc/proof/essay/unknown）
  - `difficulty`（难度，建议 `1-5` 或 `easy/medium/hard`，需要版本化口径）
- 诊断（报告增强）：`severity`（calculation/concept/format/unknown；对 correct 可为空）
- 回溯：`question_raw`（jsonb，保留原 question dict，便于演进与回填）
- 版本：`extract_version`、`taxonomy_version`、`classifier_version`

索引建议：

- `user_id, created_at desc`
- `user_id, subject, created_at desc`
- `user_id, question_type`
- `user_id, difficulty`
- `GIN(knowledge_tags_norm)`（jsonb/array 任选其一）

### 3.5 question_steps（新增：步骤事实表，用于“计算习惯差”等过程诊断）

> 目标：把“计算习惯差”从一句话变成可审计的事实（哪些步骤、什么类型、占比多少、证据是什么）。

建议表结构（最少可用集）：

- 唯一键：`(user_id, submission_id, item_id, step_index)`
- 维度：`user_id`、`submission_id`、`created_at`、`subject`
- 标识：`item_id`、`step_index`（1-indexed）
- 结果：`verdict`（correct/incorrect/uncertain）
- 分类：`severity`（calculation/concept/format/unknown）
- 过程字段（尽量结构化，缺失可空）：`expected`、`observed`
- 诊断标签（机器可聚合）：`diagnosis_codes`（如 sign_error/carry_error/unit_error/transpose_error/...）
- 回溯：`step_raw`（jsonb）
- 版本：`diagnosis_version`

说明：

- `diagnosis_codes` 的产出可以是“规则 + LLM 标签器”的组合：标签一旦落库，后续报告的统计是确定性的（硬计算）。

### 3.6 mistakes 与 question_attempts 的关系（推荐收敛方式）

为了减少重复存储与口径漂移，推荐把 “错题（mistakes）” 在数据侧收敛为：

- `mistakes` 表：仅作为 **查询加速/兼容层**（可选）
- 或 `mistakes_v1` 视图：`select * from question_attempts where verdict in ('incorrect','uncertain')` 并拼接 `mistake_exclusions`

报告的所有“分子/分母”统计以 `question_attempts` 为准；错题证据抽样可以来自 `question_attempts.question_raw`（或 `mistakes.wrong_item_raw`）。

---

## 3.7 数据来源查证（Data Source Audit：需求 → 数据 → 缺口 → 补齐）

> 目的：保证“要做的报告指标”在数据上真的有来源；没有就前置补齐，避免后面卡死。

### A) 现在就能稳定产出的报告（保持）

- 时间窗概览（7/14/30 天）
  - 数据：`question_attempts.created_at` / `submission_id` / `verdict`（或 Phase 1 先用 `mistakes.created_at`）
  - 缺口：无（Phase 2 以 `question_attempts` 替换统计口径即可）
- 知识点薄弱点 TopN（按错题贡献）
  - 数据：`knowledge_tags_norm` + `verdict != 'correct'`
  - 缺口：taxonomy 归一化必须单入口（见第 5 节）
- 错误类型画像（severity 分布）
  - 数据：`question_attempts.severity`（或步骤聚合）
  - 缺口：当前 `/grade` 导出的 `wrong_items` 常会丢 `severity`；提取时必须从 `questions[*]` / `math_steps[*].severity` 补齐（见下方补齐项）
- 典型错题证据抽样（可追溯）
  - 数据：`question_attempts.question_raw.reason/judgment_basis` + `(submission_id,item_id)`
  - 缺口：无（需要保证 `item_id` 稳定）

### B) 本次明确要做的能力（必须补齐数据链路）

1) “错误率/正确率”类指标（要做）
   - 分母：`count(question_attempts)`（包含 correct 与 incorrect/uncertain）
   - 分子：`count(question_attempts where verdict='correct')`
   - 依赖数据：`verdict`（全题）、`knowledge_tags_norm`、`question_type`、`difficulty`
   - 当前缺口：Phase 1 只有错题集合，**缺分母**
   - 补齐方案：新增 `question_attempts`（第 3.4 节），提取来源为 `submissions.grade_result.questions`

2) 知识点的真实掌握度（错误率）（要做）
   - 指标：每个知识点 `accuracy = correct / total` + `sample_size`（样本量必须输出）
   - 依赖数据：同上（全题 + tags 归一化）
   - 当前缺口：同上（缺分母 + 同义词治理）
   - 补齐方案：`question_attempts` + taxonomy v0 JSON（第 5 节）

3) 按题型/难度的薄弱点（要做）
   - 指标：`question_type x difficulty` 的薄弱矩阵、TopN 高难题型薄弱点
   - 依赖数据：`question_type`、`difficulty`、`verdict`
   - 当前缺口：`/grade` 产物里 **未稳定产生** `question_type/difficulty`
   - 补齐方案（优先顺序）：
     - P0：扩展 grading prompt，让模型对每题输出 `question_type/difficulty`（写入 `questions[*]`）
     - P1：若不稳定，加“题型/难度分类器”二次任务，版本化为 `classifier_version`

4) “计算习惯差”等更细过程诊断（要实现）
   - 指标：步骤级 `severity=calculation` 占比、Top 错误模式（sign/carry/unit/transpose 等）
   - 依赖数据：`question_steps`（`severity/expected/observed/diagnosis_codes`）
   - 当前缺口（关键）：当前 `LLMClient.grade_math` 默认 **只保留 incorrect 的第一个 bad step**，会导致“习惯”统计失真
   - 补齐方案：
     - 修改 grade 输出策略：对 incorrect/uncertain **保留全部 non-correct steps（或最多 K 个）**，保留 `severity/expected/observed`
     - 新增 `question_steps` 提取与落库
     - 引入 `diagnosis_codes` 产出（规则优先，不足时用 LLM 标签器补齐），并版本化

---

## 4. 任务链路：错题提取（Extraction Job）

### 4.1 触发方式（推荐）

- 在 `update_submission_after_grade(...)` 成功写入 `submissions.grade_result` 之后，**enqueue 一个错题提取任务**（解耦 /grade 的时延与故障面）。
- 同时保留“同步兜底”开关：当队列不可用或禁用 worker 时，允许在请求线程做一次轻量 upsert（但默认关闭）。

### 4.2 幂等与防重（必须）

**幂等（数据层）**：

- `mistakes` 使用唯一键 `(user_id, submission_id, item_id)`，写入统一用 upsert（insert on conflict do update）
- 允许任务重跑（例如提取逻辑升级、修复 bug、回填存量）

**防重（任务层，避免双任务并发重复写）**：

建议二选一（优先 A）：

- A. **数据库 advisory lock**（推荐）：worker 处理 `submission_id` 前先 `pg_try_advisory_lock(hash('mistake_extraction:' + submission_id))`，失败则说明已有 worker 在跑，直接跳过/重试
- B. Redis 分布式锁：`SET lock:mistake_extraction:{submission_id} NX EX <ttl>`，到期自动释放；失败则跳过/重试

说明：即便有锁，也必须保留 upsert 幂等，锁只解决“避免重复计算/重复写造成压力”。

### 4.3 Backfill（从 MVP 升级必须提供）

新增脚本（建议）：`python3 scripts/backfill_mistakes.py` 支持：

- 按时间窗口回填：`--since/--until`
- 按用户回填：`--user-id`
- 按版本重算：`--extract-version`
- dry-run：只统计将处理多少 submissions、将写多少 mistakes

---

## 5. 标签词典（knowledge_tags）治理（V0→V1）

你提出的建议采纳为默认落地：**V0 先用仓库内 JSON 映射文件**，所有变更走 PR，可追溯。

### 5.1 V0：JSON 映射（立刻可做）

- 文件建议：`homework_agent/resources/knowledge_taxonomy_v0.json`
- 内容包含：
  - `version`
  - `aliases`: 同义词 → 规范词（例：“毕达哥拉斯定理”→“勾股定理”）
  - `deprecated`: 旧标签 → 新标签（用于迁移）
  - `unknown_policy`: 未收录标签如何处理（保留原值/归一为 `__unknown__`/进入 review）

**提取时统一归一化**：Grade/Chat/Report 任何产生标签的地方都必须走同一套 normalize 函数（只允许一个入口）。

### 5.2 V1：表驱动（后续）

当标签体系需要运营化（多版本、AB、灰度、人工运营）时，再引入：

- `knowledge_taxonomy` 表（规范词、同义词、科目、层级、版本、状态）
- 版本化：报告生成时写入 `taxonomy_version`，保证可回放口径

---

## 6. 报告链路（Report Jobs + Reports）

### 6.1 数据表（建议）

- `report_jobs`：异步生成任务（id、user_id、params、status、attempt、locked_at、error、created_at/updated_at）
- `reports`：生成结果（report_id、user_id、time_window、features_json、narrative_md/json、evidence_refs、version、created_at）

### 6.2 API（建议口径）

- `POST /api/v1/reports`：创建生成任务（返回 `job_id`）
- `GET /api/v1/reports/jobs/{job_id}`：查询任务状态
- `GET /api/v1/reports/{report_id}`：获取报告（结构化 JSON 为主，可附 markdown）

---

## 7. 学情分析师 Subagent：两段式实现（核心）

### 7.1 第 1 段：Features Layer（硬计算）

输入（确定性）：

- `mistakes`（派生事实，已排除 exclusions）
- 时间窗口（7/14/30 天）、科目、可选班级/孩子维度

输出（可审计特征，JSON schema 固定）：

- 知识点维度：错误次数、错误率、趋势（环比/同比）、TopN 薄弱点
- 错误类型画像：`severity` 分布（calculation/concept/format/…）
- 典型错题证据：抽样若干条 `mistake_id/submission_id/item_id`（用于 narrative 引用）

特征必须满足：

- 所有数字来自 SQL/Python 计算，不允许 LLM “自己算”
- 每个指标可回溯到 evidence refs（至少能定位到 submissions 与 item）

### 7.2 第 2 段：Narrative Layer（软解释）

输入：

- `features_json`
- 少量典型错题（脱敏后的文本/结构化字段 + 引用 id）
- 报告模板（固定章节、输出 schema）

输出：

- 解释与建议（“归因”优先于“数数”）
- 可执行的复习计划（7 天/14 天，颗粒度到题型/知识点/练习建议）

约束（抗幻觉）：

- Prompt 明确禁止发明数字；数字只能引用 features_json 中已有字段
- 输出必须是 schema-valid（JSON schema 校验失败则重试/降级）
- 对不确定结论必须标注 `uncertain` 与依据不足原因

---

## 8. 验证与门禁（多轮验证怎么做）

### 8.1 单元验证（每步都要能自测）

- question_attempts 提取：给定固定的 `grade_result.questions` 输入，输出行数/主键/关键字段必须稳定（hash/快照测试）
- question_steps 提取：给定固定的 `math_steps` 输入，输出步骤行必须稳定（尤其是 `severity/diagnosis_codes`）
- mistakes（兼容层）提取：给定固定的 `grade_result.questions` 输入，wrong subset 必须稳定（不再依赖 `wrong_items` 是否存在/是否完整）
- taxonomy normalize：别名/弃用/未知标签策略有覆盖测试

### 8.2 回归验证（replay/baseline）

- 报告特征输出：对固定样本窗口，features_json 的关键指标必须稳定（允许小范围浮动需明确口径）
- narrative：只验证结构与约束（不验证文案好坏），例如“不得新增未在 features_json 中出现的数字”

### 8.3 生产可观测

- 每次报告生成记录：`report_version`、`taxonomy_version`、`feature_version`、`model/provider`
- 统计维度：生成耗时、token 成本、失败率、重试次数

---

## 9. 分阶段实施清单（建议顺序）

0) 先补齐“数据必需产物”（否则后面所有报告都会卡死）
   - `/grade` 写入 `submissions.grade_result.questions` 必须包含（至少）：
     - `verdict`（全题）、`knowledge_tags`（全题）
     - `question_type`、`difficulty`（全题）
     - `item_id`、`question_idx`（全题稳定标识；无题号也要稳定）
     - 数学题：`math_steps`（incorrect/uncertain 至少保留全部 non-correct steps 或最多 K 个），包含 `severity/expected/observed`
   - 同时修正 `wrong_items` 的抽取：不要丢 `severity/math_steps`（即便最终报表主要用 question_attempts）

1) 新增派生事实表（先不改现有 API，对外不破坏）
   - `question_attempts`（分母）+ `question_steps`（过程）+ 兼容层 `mistakes`（可表可视图）
2) extraction job：enqueue + worker + advisory lock（或 Redis lock）+ backfill 脚本
   - 提取来源改为 `submissions.grade_result.questions`（而不是仅 `wrong_items`）
3) taxonomy v0：引入仓库内 JSON 映射 + normalize 单入口 + 指标对齐
4) report_jobs/reports：任务表 + 查询接口（先返回 features_json：正确率/掌握度/题型难度矩阵/计算习惯画像）
5) narrative layer：接 LLM 生成解释（严格 schema + 证据引用；禁止发明数字）
6) replay/baseline：补齐报告样本与门禁阈值（再迭代“更聪明”）

---

## 10. 风险与对策

- 口径漂移：靠 `extract_version/taxonomy_version/report_version` 固化，可回放
- 并发/重复任务：锁 + upsert；任务表状态机防止无限重试
- 幻觉与不可解释：两段式；LLM 只解释不计算；证据引用与 schema 校验
- 性能：读 `mistakes` 做聚合；避免扫 JSONB；必要时引入 MV/增量汇总表
