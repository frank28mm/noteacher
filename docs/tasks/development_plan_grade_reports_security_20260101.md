# 开发执行计划（Grade 性能/质量 + Reports/Worker/RLS + 密钥治理）

> 本计划是“当前一轮执行计划/跟踪表”，从 `docs/cto_90_day_plan.md`（路线图）与 `docs/agent/next_development_worklist_and_pseudocode.md`（Backlog）中抽取必要条目，并补齐我们最近讨论的 Ark Responses API、image_process、RLS/权限与 schema 口径对齐的落地细节。
>
> 原则：**不新增第二份路线图/Backlog**；本文件只负责“把要做的事列清楚、可验收、可追踪”。

## 0) 目标与非目标

### 0.1 目标（用户可感知）

- **差异化质量**：对错判定必须可解释（judgment_basis/证据链），证据不足明确标注 `uncertain/needs_review`，拒绝“看起来很快但互相矛盾”的输出。
- **体验可控**：把 `/grade` 的慢拆解成可量化分项（抓图/压缩/定位/LLM 推理/DB 写入），能定位瓶颈并做优化决策。
- **闭环可扩展**：报告链路从 grade/chat 解耦（异步、可重跑、可审计），为“学情分析师 subagent”提供稳定输入。

### 0.2 明确不做（本阶段不做）

- 不做“按班级/年级/教材版本分群对比”。
- 不做“进步/退步归因到练习量”。

## 1) 现状核对（基于代码/DB 真相）

### 1.1 已落地（已完成）

- Ark Responses API：
  - 将 system prompt 从 `system role message` 迁移到顶层 `instructions=...`（降低兼容性风险）。
  - 支持 `ARK_IMAGE_PROCESS_ENABLED` 开关（开启内置 `image_process` 工具；失败自动回退无 tools）。
  - `/grade` 记录并持久化 Ark `response_id`（便于用官方 GET API 查证“拉图/工具/输入”）。
- `/grade` 性能拆解：
  - 在 qbank meta 写入 `timings_ms`（preprocess/tools/compress/LLM/DB 等分项）。
  - 增加 `/grade` 图片输入策略实验：`GRADE_IMAGE_INPUT_VARIANT=auto|url|proxy|data_url_first_page|data_url_on_small_figure`（支持 header 覆盖）。
- A/B/C 结论留档：
  - 已生成并留档：`docs/archive/reports/perf_audit_ab_test_results.md`

### 1.2 当前口径偏差（必须修）

- `GET /reports/{report_id}`：DB schema 为 `reports.id`，但代码曾按 `reports.report_id` 查询（已修为按 `id` 查询，并保留路由参数名不变）。
- `report_jobs` 状态：`supabase/schema.sql` 默认 `queued`，而 `report_worker` 只拉 `pending`（会导致 worker 永远拿不到任务）。
- `report_jobs` 缺少锁字段（`locked_at/locked_by/...`），且 `report_jobs` 无 UPDATE policy（anon key 下 update 可能被 RLS 拒绝）。
- `question_attempts/question_steps`：migrations 里有设计，但现库未必存在；报告特征/过程诊断要落地仍需事实表或等价宽表。

## 2) 工作流拆分（Workstreams）

### WS‑A：/grade 性能与质量（Ark 作为主线）

**目标**：把“慢”拆解为确定瓶颈；把“快但不严谨”改成“可审计 + 可控降级”。

#### A‑1 选择默认图片输入策略（基于现有数据）

- 决策：**当前默认固定 `url`**（先把快路径跑稳 + 提升可解释性）；`proxy` 待闭环修复后再做最小验证并考虑切默认。
- 备注：`data_url_*` 仅用于“少量复核/争议 recheck”，不作为默认全量策略。
- 验收：
  - `/grade` P95（同步场景）显著下降或至少瓶颈可解释；
  - `needs_review_rate` 可控且有原因字段；
  - 产生 `response_id` 且可回查。

#### A‑2 “慢到底慢在哪”持续审计（日志驱动）

- 交付物：
  - 固化关键日志事件与字段：`grade_total_duration_ms`、`preprocess_*`、`compress_*`、`llm_*`、`submission_persist_*`。
  - 对比三组：`Ark URL 拉图 vs base64 少量复核 vs 预生成 proxy`。
    - 日常迭代：每个 variant 先跑 **N=5**，输出 `p50 + max + 失败率/needs_review率`（更快、更省钱，用于判断方向）。
    - 决策/验收：再补一轮 **N=5**（不同时间段/清空队列或隔离前缀后），两轮合并视作 **≈N=10**，再看 `p50/p95` 以减少抽样偶然性。
  - 固化可复跑脚本：`scripts/bench_grade_variants_async.py`（输出 `docs/reports/grade_perf_variants_*.md/.json`）。
- 已跑 N=10（IMG_0699）：`docs/reports/grade_perf_variants_qindex_only_n10_img0699_20260101.md`
- 最新快路径基线（URL-only + qindex_only）：`docs/reports/grade_perf_url_n3_fast_finalize_12000_20260102.md`
- 复盘摘要（含关键实现策略）：`docs/reports/grade_perf_fast_path_summary_20260102.md`
- 验收：每次优化前后都有“可对比的量化证据”，不会凭感觉换策略。

#### A‑3 image_process 的收益验证（不做 A/B 也要可复现）

- 交付物：
  - 在相同输入/相同 `GRADE_IMAGE_INPUT_VARIANT` 下，跑 `ARK_IMAGE_PROCESS_ENABLED=0/1` 两组：
    - 日常迭代：每组先跑 **N=5**
    - 决策/验收：两轮 N=5 合并（≈N=10）
  - 输出：速度（总耗时 + 分项）与质量（wrong_items 稳定性/互斥率/uncertain）对比。
- 验收：明确“哪些题型/哪些场景开启有效”，再决定是否扩大范围。

补充：当前快路径默认不启用 `image_process`（避免 deep-vision 在快路径中长时间思考/拉图）；仅当存在明确图形证据（figure slices）时启用。

#### A‑4 本轮新增：快路径预处理降级 + 实验隔离 + 验收阈值（来自第二轮实测结论）

> 说明：以下是基于两轮实测（Demo + bench）与同事复核形成的“立即可落地”优先级建议；证据留档见：
> - `docs/reports/demo_ui2_run_20260101_133600.md`
> - `docs/reports/grade_perf_root_cause_findings_20260101.md`
> - `docs/reports/grade_perf_variants_full_after_fix_20260101.md`
> - `docs/reports/grade_perf_variants_off_variantprop_20260101.md`

- P0（现在就做，直接改善体验）
  - 默认把 grade 快路径设为 `AUTONOMOUS_PREPROCESS_MODE=qindex_only`（仅复用 qindex 缓存切片；未命中则跳过），把 VLM locator/切片移出快路径，仅在“视觉风险/复核”时触发。
  - 若 qindex 缓存长期未命中/worker 未启用，临时回退到 `AUTONOMOUS_PREPROCESS_MODE=off`（避免被预处理拖慢快路径）。
  - “清除测试干扰”落地为隔离策略：优先用新的 `CACHE_PREFIX` / `DEMO_USER_ID` 做实验隔离（优先级高于 `redis-cli FLUSHDB`）。
- P1（让对比结论更可信、让策略更可运营）
  - 统计策略：日常迭代用 **N=5**（看 `p50 + max + 失败率`），需要做默认策略/验收结论时再补一轮 N=5（合并≈N=10 后看 p50/p95）。
  - 让 `proxy` 变体名副其实：当前更偏 “prefer_proxy”，缺少稳定生成 proxy 资产的机制，导致对比口径不纯；需补齐“生成/回写/复用 proxy_page_image_urls”的闭环后再定默认策略。
  - 增加“单次作业报告”：给 `/reports` 增加 `submission_id` 模式（Demo 展示更符合用户预期；周期性报告 `window_days` 继续保留）。
- P2（工程一致性/文档）
  - `homework_agent/utils/settings.py` 中 `REPORT_NARRATIVE_ENABLED` 的注释与默认值不一致（注释写“keep off by default”，但 `default=True`）；需统一口径，避免误读。

- 验收阈值（用于 /grade 体验达标）
  - 在“无排队干扰”（队列为空/隔离前缀）前提下：同一张图 `p50 < 60s`，`p95 < 120s`（以 `grade_total_duration_ms` 为准，且同时记录分项）。

#### A‑5 视觉题验证（几何/函数图像/复杂示意图）

> 目标：在快路径固定后，用真实视觉题样本验证“何时必须切到视觉证据路径”，并把门槛固化为可解释的规则（宁可 `uncertain` 也不误判为 `correct`）。

- 输入：至少 2 张真实样本（优先：几何 1 张、函数坐标系 1 张）。本轮已用 2 张几何样本完成验证（函数图像待补样复核）。
- 统计：同图重复 **N=5**（与快路径验收口径对齐），记录 `p50/p95` + 失败率/`needs_review_rate`。
- 对比：
  - `AUTONOMOUS_PREPROCESS_MODE=qindex_only`（默认快路径；验证是否需要触发“轻量视觉路径”）
  - `AUTONOMOUS_PREPROCESS_MODE=full`（视觉证据链上限基线；不作为默认）
- 产物：
  - 统一汇总：`docs/reports/grade_perf_visual_validation_20260102.md`
  - 明细（N=5）：`docs/reports/grade_perf_visual_img0699_qindex_only_url_n5_20260102.md`、`docs/reports/grade_perf_visual_img0699_full_url_n5_20260102.md`、`docs/reports/grade_perf_visual_img1100_qindex_only_url_n5_20260102.md`、`docs/reports/grade_perf_visual_img1100_full_url_n5_20260102.md`
- 固化结论（触发规则，已落地实现）：
  - 默认快路径仍是 `qindex_only + url`，但当命中 `visual_risk`（OCR 关键字）或存在 slices 时，切换到“带图 + image_process”（宁可不确定也不误判）。
  - `full` 仅用于“离线复核/正确性上限”，避免把 ~70–100s 的预处理成本带入默认快路径。

### WS‑B：Supabase Schema/RLS/权限（支撑 Worker 稳定运行）

**决策偏好**：因为现阶段数据可丢，可选择“重置到真源 schema + 增量补齐缺失表/字段”。但**禁止**再引入“DROP SCHEMA + 迁移文件强对齐”这套会导致口径漂移的方案。

#### B‑1 Schema 真源与变更方式

- 真源：`supabase/schema.sql`（现网/现库真实口径）。
- 变更方式：
  - 增量 SQL（推荐）：为 `report_jobs` 增加锁字段；创建 `question_attempts/question_steps` 或等价宽表；补齐索引。
  - 或重置（允许）：若决定清库，可在 Supabase SQL Editor 重新执行 `supabase/schema.sql` 后再执行增量 SQL。
- 验收：DB schema 与代码/worker 口径一致（字段/状态值/可写权限），不再需要“适配层”绕来绕去。

参考增量脚本：`supabase/patches/20260101_add_facts_tables_and_report_job_locks.sql`

#### B‑2 RLS/权限路线（Phase 1.5）

- 推荐：**worker 使用 service role key**（绕过 RLS），API 仍使用 anon key（开发期）或 auth key（生产）。
- 风险控制（必须执行）：
  - service role key 只存在于 worker 进程运行环境（Secret Manager/部署环境变量），不进入仓库文件。
  - CI 增加“误提交检测”（已落地，见 `scripts/check_no_secrets.py` 与 `.github/workflows/ci.yml`）。
  - 建议（可选）：制定轮换策略（例如每月/每次疑似泄露后立刻轮换）。

### WS‑C：Reports/Facts Worker 端到端闭环

#### C‑1 report_jobs 状态与锁

- **明确决策：选择方案 A（改 DB，加锁字段）**。
  - 理由：`locked_at/locked_by` 是业界标准实践；一次性在 DB 层解决并发抢占与可观测性问题，能让 worker 代码更简洁、更可维护。
  - 备注：方案 B（只改代码）仅作为应急兜底（当 DB 无法变更/权限受限时），否则会把“锁/重试/幂等”的复杂度转移到代码侧。

- DB 侧（方案 A，推荐）：
  - `report_jobs` 增加：`locked_at/locked_by/attempt_count/last_error`。
  - 允许 worker 用原子条件更新（`status in ('queued','pending')` 且 `locked_at is null or expired`）。
- 代码侧：
  - `report_worker` 支持拉取 `queued|pending`，并在锁成功后改为 `running`。
- 验收：多实例 worker 下同一 job 只会被一个 worker 处理；失败可重试且有 attempt 记录。

#### C‑2 facts_worker 与小批量回填

- 交付物：
  - 支持“最近 N 条 submissions 回填”为事实表（进度日志/速率统计/可中断续跑）。
  - 回填后跑一次“统计对比”（与 submissions.grade_result.questions 的分母/分子口径一致）。
- 验收：
  - `question_attempts/question_steps` 的行数随回填增长，且 `mistake_exclusions` 能正确过滤；
  - 生成报告的 Features Layer 结果稳定可审计。

#### C‑3 报告 API 与产物

- API：
  - `POST /reports` 创建 job（status 初始与 DB 默认一致：`queued`）。
  - `GET /reports/jobs/{job_id}` 查询状态；`GET /reports/{report_id}` 按 `reports.id` 查询（已修）。
- 验收：创建→worker 消费→写入 `reports`→查询返回闭环跑通。

## 3) 验证与测试方案（必须写进交付）

### 3.1 代码级（CI）

- `pytest -q`：保证单元测试/契约测试全绿。
- `scripts/check_no_secrets.py`：阻止 service role key/JWT 误进仓库（已落地）。

### 3.2 端到端（本地/联调）

- `/grade`：
  - 同一张图重复跑 3 次，记录 `timings_ms` 与 `response_id`；
  - 切换 `GRADE_IMAGE_INPUT_VARIANT` 与 `ARK_IMAGE_PROCESS_ENABLED`，输出对比表。
- `/reports`：
  - 创建 job → worker 抢占 → done/failed → 查询 report。

## 4) 风险清单（Risk Register）

- service role key 泄露：最高风险 → CI 检测 + Secret Manager + 轮换。
- schema 口径漂移：会导致 worker/报告“看似跑了但全是空/错” → 以 `supabase/schema.sql` 为真源 + 增量 SQL。
- RLS 误配置：worker 无法 UPDATE → worker 用 service role 或明确的最小 UPDATE policy（仅开发期）。
- 盲目追求速度：导致“互斥/幻觉/误判” → 强制证据链、uncertain、回查 response_id。

## 5) 与 90 天路线图/Backlog 的对齐结论

### 5.1 对齐点（一致）

- 路线图 Week 1 的 “Schema 对齐（P0）/运行手册/可观测性” 与本计划 WS‑B 完全一致。
- 路线图 Week 2–4 的 “报告链路打底/Worker 拓扑/Redis 必选” 与本计划 WS‑C 一致。
- Backlog 的 WL‑P1‑010（报告 jobs + 学情分析师）与本计划 WS‑C 方向一致。

### 5.2 需要回写到 Backlog 的口径修正（建议）

- `report_jobs` 状态：Backlog 文案从 `pending` 修正为 `queued`（与 `supabase/schema.sql` 一致，代码也需兼容）。
- Design Doc 路径：仓库内实际文件位于 `docs/archive/design/mistakes_reports_learning_analyst_design.md`（需统一引用路径）。
- 新增两条 P0 工程任务（建议加入 Backlog）：
  - `WL‑P0‑0xx：/grade 性能拆解与输入策略对比（url/proxy/data_url + image_process）`
  - `WL‑P0‑0xx：Worker service role key 治理（CI 防泄露 + 运行手册）`
